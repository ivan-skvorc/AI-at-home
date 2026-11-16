"""The chat clean-up routes bill a durable SQLite store and must not block the loop.

``POST /api/threads/{id}/organize/suggest`` records one call per conversation
and ``POST /api/chat-organize/consolidate`` splits one call across many
conversations, both into the durable aux-usage store (a local SQLite file). A
clean-up pass fires these back to back for every selected chat, so a sync write
on the event loop would stall every other request once per conversation. The
routes are driven under the strict gate with the real store; only the checkpoint
read, auth, the spend status and the provider model are stubbed.

The recorders are best-effort and swallow the gate's ``BlockingError``, so an
on-loop write shows up here as *missing usage*: the assertions on the recorded
totals are what fail, not the gate itself.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.gateway.routers import chat_organize
    from deerflow.config.title_config import TitleConfig
    from deerflow.runtime import aux_usage
    from deerflow.utils import oneshot_llm

    monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(tmp_path / "aux_usage.sqlite3"))
    aux_usage.reset_aux_usage_cache()

    snapshot = SimpleNamespace(config={"configurable": {"checkpoint_id": "cp-1"}}, values={"messages": [HumanMessage(content="Why is the build slow?"), AIMessage(content="Cache misses.")]})
    accessor = SimpleNamespace(aget=AsyncMock(return_value=snapshot))
    monkeypatch.setattr(chat_organize, "build_thread_checkpoint_state_accessor", AsyncMock(return_value=(accessor, {})))
    monkeypatch.setattr(chat_organize, "get_current_user_from_request", AsyncMock(return_value=SimpleNamespace(id="u-1")))
    monkeypatch.setattr(chat_organize, "authorize_model_use", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_organize, "resolve_run_spend_budget", AsyncMock(return_value=SimpleNamespace(exceeded=None, currency=None)))
    monkeypatch.setattr(chat_organize, "get_thread_store", lambda request: SimpleNamespace(check_access=AsyncMock(return_value=True)))

    replies: list[str] = []
    model = MagicMock()

    async def invoke(messages, *, config):
        return AIMessage(content=replies.pop(0), response_metadata={"model_name": "served-model"}, usage_metadata={"input_tokens": 90, "output_tokens": 9, "total_tokens": 99})

    model.ainvoke = invoke
    monkeypatch.setattr(oneshot_llm, "create_chat_model", lambda **kwargs: model)
    config = SimpleNamespace(title=TitleConfig(model_name=None), models=[SimpleNamespace(name="local")], pii_redaction=None)
    yield SimpleNamespace(router=chat_organize, aux_usage=aux_usage, replies=replies, config=config)
    aux_usage.reset_aux_usage()


async def test_suggest_bills_the_conversation_off_the_event_loop(wired) -> None:
    wired.replies.append('{"title": "Speeding up the build", "category": "Build tooling", "summary": "Slow builds."}')
    body = wired.router.OrganizeSuggestRequest(mode="auto")

    result = await wired.router.suggest_thread_organization.__wrapped__("t-1", body, request=None, config=wired.config)

    assert result.category == "Build tooling"
    usage = await wired.aux_usage.aget_thread_aux_usage("t-1")
    assert usage["organize"]["served-model"]["calls"] == 1


async def test_consolidate_splits_its_bill_off_the_event_loop(wired) -> None:
    wired.replies.append('{"folders": [{"name": "Builds", "labels": [1, 2]}]}')
    body = wired.router.ConsolidateRequest(items=[{"thread_id": "t-1", "category": "Build tooling"}, {"thread_id": "t-2", "category": "CI speed"}])

    result = await wired.router.consolidate_chat_categories.__wrapped__(body, request=None, config=wired.config)

    assert [(folder.name, folder.thread_ids) for folder in result.folders] == [("Builds", ["t-1", "t-2"])]
    first = await wired.aux_usage.aget_thread_aux_usage("t-1")
    second = await wired.aux_usage.aget_thread_aux_usage("t-2")
    assert first["organize"]["served-model"]["total_tokens"] + second["organize"]["served-model"]["total_tokens"] == 99
