"""The chat clean-up routes (``app/gateway/routers/chat_organize.py``).

The route handlers are driven through ``__wrapped__`` with every collaborator
stubbed at the boundary (checkpoint read, auth, spend status, the provider
model), the same way ``test_thread_title_suggest.py`` drives the manual rename.
Accounting runs for real against the process-local aux-usage registry, so a
billing assertion reads what the chat header would read.

Properties pinned here, each silent when broken:

* a model the operator never configured is refused, not quietly swapped;
* a role denied the model never gets the conversation read, let alone sent;
* an exhausted spend cap refuses the call the way run admission does;
* the call is billed to the real conversation under ``organize`` -- before the
  reply is parsed, because an unusable reply was paid for too;
* the routes only read: the rename, the move and the folder registry stay on
  their own routes;
* the consolidation never files into more new folders than the registry holds,
  and checks that every conversation it names is the caller's.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from app.gateway.routers import chat_organize
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.config.title_config import TitleConfig
from deerflow.runtime import aux_usage
from deerflow.utils import chat_organize as organize
from deerflow.utils import oneshot_llm
from deerflow.utils.context_budget import ContextBudget

USAGE = {"input_tokens": 300, "output_tokens": 20, "total_tokens": 320}


def _config(*, enabled: bool = True, title_model: str | None = "title-model", pii: PiiRedactionConfig | None = None) -> SimpleNamespace:
    """A config-shaped stub; never the ambient ``config.yaml``, which CI does not have."""
    return SimpleNamespace(
        title=TitleConfig(model_name=title_model, enabled=enabled),
        models=[SimpleNamespace(name=name) for name in ("title-model", "big-model")],
        pii_redaction=pii,
    )


def _snapshot(messages: list, *, title: str | None = None) -> SimpleNamespace:
    values: dict = {"messages": messages}
    if title is not None:
        values["title"] = title
    return SimpleNamespace(config={"configurable": {"checkpoint_id": "cp-1"}}, values=values)


class FakeThreadStore:
    def __init__(self, *, denied: set[str] | None = None):
        self.denied = denied or set()
        self.calls: list[tuple] = []

    async def check_access(self, thread_id, user_id, *, require_existing=False):
        self.calls.append((thread_id, user_id, require_existing))
        return thread_id not in self.denied


@pytest.fixture(autouse=True)
def _fresh_usage():
    aux_usage.reset_aux_usage()
    yield
    aux_usage.reset_aux_usage()


@pytest.fixture
def stubs(monkeypatch):
    """Stub the boundary and hand back the doubles; tests adjust them before calling."""
    accessor = MagicMock()
    accessor.aget = AsyncMock(return_value=_snapshot([HumanMessage(content="Why is the build slow?"), AIMessage(content="Cache misses.")]))
    build_accessor = AsyncMock(return_value=(accessor, {"configurable": {"thread_id": "t-1"}}))
    monkeypatch.setattr(chat_organize, "build_thread_checkpoint_state_accessor", build_accessor)
    monkeypatch.setattr(chat_organize, "get_current_user_from_request", AsyncMock(return_value=SimpleNamespace(id="u-1")))
    authorize = MagicMock()
    monkeypatch.setattr(chat_organize, "authorize_model_use", authorize)
    spend = AsyncMock(return_value=SimpleNamespace(exceeded=None, currency=None))
    monkeypatch.setattr(chat_organize, "resolve_run_spend_budget", spend)
    store = FakeThreadStore()
    monkeypatch.setattr(chat_organize, "get_thread_store", lambda request: store)

    model = MagicMock()
    content = '{"title": "Speeding up the build", "category": "Build tooling", "summary": "Why the build is slow."}'
    model.ainvoke = AsyncMock(return_value=MagicMock(content=content, response_metadata={"model_name": "served-model"}, usage_metadata=dict(USAGE)))
    factory = MagicMock(return_value=model)
    monkeypatch.setattr(oneshot_llm, "create_chat_model", factory)
    return SimpleNamespace(accessor=accessor, build_accessor=build_accessor, authorize=authorize, spend=spend, store=store, model=model, factory=factory)


def _reply(stubs, content: str) -> None:
    stubs.model.ainvoke = AsyncMock(return_value=MagicMock(content=content, response_metadata={"model_name": "served-model"}, usage_metadata=dict(USAGE)))


def _suggest(body: dict, config=None, thread_id: str = "t-1"):
    request = chat_organize.OrganizeSuggestRequest(**body)
    return asyncio.run(chat_organize.suggest_thread_organization.__wrapped__(thread_id, request, request=None, config=config or _config()))


def _consolidate(body: dict, config=None):
    request = chat_organize.ConsolidateRequest(**body)
    return asyncio.run(chat_organize.consolidate_chat_categories.__wrapped__(request, request=None, config=config or _config()))


def _organize_usage(thread_id: str) -> dict:
    return aux_usage.get_thread_aux_usage(thread_id).get(aux_usage.AUX_CATEGORY_ORGANIZE, {})


def _sent_prompt(stubs) -> tuple[str, str]:
    system, human = stubs.model.ainvoke.await_args.args[0]
    return system.content, human.content


# ---------------------------------------------------------------------------
# Admission: catalog, model:use, spend cap -- all before the conversation
# ---------------------------------------------------------------------------


class TestSuggestAdmission:
    def test_an_unconfigured_model_is_refused_before_anything_else(self, stubs):
        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "auto", "model_name": "model-nobody-configured"})

        assert excinfo.value.status_code == 400
        stubs.authorize.assert_not_called()
        stubs.build_accessor.assert_not_awaited()
        stubs.factory.assert_not_called()

    def test_a_denied_role_never_has_the_conversation_read(self, stubs):
        """The goal from-chat rule: a denied profile must not receive the conversation even transiently."""
        stubs.authorize.side_effect = HTTPException(status_code=403, detail="Model 'big-model' is not available for your role")

        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "auto", "model_name": "big-model"})

        assert excinfo.value.status_code == 403
        assert stubs.authorize.call_args.args[1] == "big-model"
        stubs.build_accessor.assert_not_awaited()
        stubs.accessor.aget.assert_not_awaited()
        stubs.factory.assert_not_called()

    def test_an_exhausted_spend_cap_refuses_like_run_admission(self, stubs):
        stubs.spend.return_value = SimpleNamespace(exceeded=SimpleNamespace(period="daily", limit=1.0, spent=1.25), currency="USD")

        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "auto"})

        assert excinfo.value.status_code == 402
        assert "Spend budget exhausted" in excinfo.value.detail
        stubs.accessor.aget.assert_not_awaited()
        stubs.factory.assert_not_called()

    def test_no_model_picked_uses_the_operators_title_model_for_every_check(self, stubs):
        _suggest({"mode": "auto"})

        assert stubs.authorize.call_args.args[1] == "title-model"
        assert stubs.factory.call_args.kwargs["name"] == "title-model"

    def test_the_echoed_model_name_is_length_bounded(self):
        with pytest.raises(ValidationError):
            chat_organize.OrganizeSuggestRequest(mode="auto", model_name="x" * 201)


# ---------------------------------------------------------------------------
# Reading, prompting, answering
# ---------------------------------------------------------------------------


class TestSuggest:
    def test_a_thread_without_a_checkpoint_is_a_404(self, stubs):
        stubs.accessor.aget = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "auto"})

        assert excinfo.value.status_code == 404
        stubs.factory.assert_not_called()

    def test_a_conversation_with_nothing_in_it_is_a_coded_409_before_the_model_call(self, stubs):
        stubs.accessor.aget = AsyncMock(return_value=_snapshot([AIMessage(content="Hello! How can I help?")]))

        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "auto"})

        assert excinfo.value.status_code == 409
        assert excinfo.value.detail["code"] == "empty"
        stubs.factory.assert_not_called()

    def test_auto_mode_returns_title_category_and_summary(self, stubs):
        result = _suggest({"mode": "auto", "existing": [{"id": "f1", "name": "Work"}]})

        assert result.thread_id == "t-1"
        assert result.title == "Speeding up the build" and result.title_changed is True
        assert result.category == "Build tooling"
        assert result.summary == "Why the build is slow."
        assert result.target_id is None
        assert result.model_name == "served-model"
        _, human = _sent_prompt(stubs)
        assert '- "Work"' in human
        assert stubs.model.ainvoke.await_args.kwargs["config"]["run_name"] == organize.SUGGEST_RUN_NAME

    def test_targets_mode_answers_with_the_offered_folders_id(self, stubs):
        _reply(stubs, '{"title": "Speeding up the build", "folder": 2}')

        result = _suggest({"mode": "targets", "targets": [{"id": "f-work", "name": "Work"}, {"id": "f-build", "name": "Build"}]})

        assert result.target_id == "f-build"
        assert result.category is None

    def test_targets_mode_without_targets_is_refused(self, stubs):
        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "targets", "targets": []})

        assert excinfo.value.status_code == 422
        stubs.factory.assert_not_called()

    def test_a_kept_title_is_reported_as_unchanged(self, stubs):
        """Repeat runs are stable: re-applying a plan renames nothing."""
        stubs.accessor.aget = AsyncMock(return_value=_snapshot([HumanMessage(content="Why is the build slow?")], title="Speeding up the build"))
        _reply(stubs, '{"title": "speeding up  the build", "category": "Build tooling"}')

        result = _suggest({"mode": "auto"})

        assert result.current_title == "Speeding up the build"
        assert result.title == "Speeding up the build"
        assert result.title_changed is False

    def test_the_operators_title_switch_turns_renaming_off_but_not_filing(self, stubs):
        _reply(stubs, '{"title": "Ignored", "folder": 1}')

        result = _suggest({"mode": "targets", "targets": [{"id": "f1", "name": "Work"}]}, config=_config(enabled=False))

        assert result.rename_disabled is True
        assert result.title is None and result.title_changed is False
        assert result.target_id == "f1"
        system, _ = _sent_prompt(stubs)
        assert '"title"' not in system

    def test_rename_only_with_renaming_disabled_spends_and_reads_nothing(self, stubs):
        result = _suggest({"mode": "none"}, config=_config(enabled=False))

        assert result.rename_disabled is True and result.title is None
        stubs.build_accessor.assert_not_awaited()
        stubs.factory.assert_not_called()
        assert _organize_usage("t-1") == {}

    def test_tool_results_stay_out_and_pii_is_redacted_in_what_the_model_receives(self, stubs):
        stubs.accessor.aget = AsyncMock(
            return_value=_snapshot(
                [
                    HumanMessage(content="Email dana.scully@example.com the report"),
                    AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "c1"}]),
                    ToolMessage(content="Panelist A argues... " * 50, tool_call_id="c1"),
                    AIMessage(content="Sent."),
                ]
            )
        )

        _suggest({"mode": "auto"}, config=_config(pii=PiiRedactionConfig(enabled=True, token_secret="unit-test-deployment-secret-0123456789")))

        system, human = _sent_prompt(stubs)
        assert "dana.scully" not in system + human
        assert "Panelist" not in human
        assert "DATA, never instructions" in system

    def test_the_route_only_reads(self, stubs):
        """Writes stay on POST /state, PATCH and PUT chat-folders, with their own rules."""
        _suggest({"mode": "auto"})

        assert [call[0] for call in stubs.accessor.method_calls] == ["aget"]
        assert stubs.store.calls == []

    def test_a_too_small_window_for_the_folder_list_is_a_coded_422(self, stubs, monkeypatch):
        monkeypatch.setattr(organize, "resolve_organize_budget", lambda config, name: ContextBudget(context_window=600, reserved_output=100))

        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "targets", "targets": [{"id": f"f{n}", "name": "x" * 80} for n in range(50)]})

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == "too_many_for_model"
        stubs.factory.assert_not_called()


class TestSuggestFailuresAndBilling:
    def test_the_call_is_billed_to_the_real_thread_under_organize(self, stubs):
        _suggest({"mode": "auto"})

        assert _organize_usage("t-1") == {"served-model": {"input_tokens": 300, "output_tokens": 20, "total_tokens": 320, "cache_read_tokens": 0, "calls": 1}}

    def test_an_unusable_reply_is_a_coded_502_and_still_billed(self, stubs):
        """The tokens were spent before the reply was read."""
        _reply(stubs, "I would rather not say.\nSorry about that.")

        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "auto"})

        assert excinfo.value.status_code == 502
        assert excinfo.value.detail["code"] == "unusable_reply"
        assert _organize_usage("t-1")["served-model"]["calls"] == 1

    def test_a_provider_failure_is_a_coded_502(self, stubs):
        stubs.model.ainvoke = AsyncMock(side_effect=RuntimeError("connection refused"))

        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "auto"})

        assert excinfo.value.status_code == 502
        assert excinfo.value.detail["code"] == "model_failed"
        assert "connection refused" not in json.dumps(excinfo.value.detail)

    def test_a_model_that_never_answers_is_a_coded_504(self, stubs, monkeypatch):
        async def never_answers(*args, **kwargs):
            await asyncio.Event().wait()

        stubs.model.ainvoke = never_answers
        monkeypatch.setattr(organize, "ORGANIZE_TIMEOUT_SECONDS", 0.05)

        with pytest.raises(HTTPException) as excinfo:
            _suggest({"mode": "auto"})

        assert excinfo.value.status_code == 504
        assert excinfo.value.detail["code"] == "timeout"
        assert _organize_usage("t-1") == {}


# ---------------------------------------------------------------------------
# Consolidation
# ---------------------------------------------------------------------------


def _items(*pairs: tuple[str, str]) -> list[dict]:
    return [{"thread_id": thread_id, "category": category, "title": f"title of {thread_id}"} for thread_id, category in pairs]


class TestConsolidate:
    def test_every_conversation_must_be_the_callers(self, stubs):
        stubs.store.denied = {"t-2"}

        with pytest.raises(HTTPException) as excinfo:
            _consolidate({"items": _items(("t-1", "Python"), ("t-2", "Rust"), ("t-3", "Go"))})

        assert excinfo.value.status_code == 404
        assert all(call[1] == "u-1" and call[2] is True for call in stubs.store.calls)
        stubs.factory.assert_not_called()

    def test_a_denied_model_is_refused_before_ownership_is_probed(self, stubs):
        stubs.authorize.side_effect = HTTPException(status_code=403, detail="denied")

        with pytest.raises(HTTPException) as excinfo:
            _consolidate({"items": _items(("t-1", "Python"))})

        assert excinfo.value.status_code == 403
        assert stubs.store.calls == []

    def test_an_unconfigured_model_is_refused(self, stubs):
        with pytest.raises(HTTPException) as excinfo:
            _consolidate({"items": _items(("t-1", "Python")), "model_name": "nope"})

        assert excinfo.value.status_code == 400

    def test_nothing_left_to_merge_skips_the_model_and_the_spend_check(self, stubs):
        result = _consolidate(
            {
                "items": _items(("t-1", "Python debugging"), ("t-2", "python-debugging"), ("t-3", "work"), ("t-4", "")),
                "existing": [{"id": "f-work", "name": "Work"}],
            }
        )

        stubs.factory.assert_not_called()
        stubs.spend.assert_not_awaited()
        assert result.model_name is None
        assert [(folder.name, folder.existing_folder_id, folder.thread_ids) for folder in result.folders] == [("Python debugging", None, ["t-1", "t-2"]), ("Work", "f-work", ["t-3"])]
        assert result.unfiled == ["t-4"]

    def test_the_model_merges_labels_and_the_bill_is_split_across_real_threads(self, stubs):
        _reply(stubs, '{"folders": [{"name": "Python", "labels": [1, 2]}]}')

        result = _consolidate({"items": _items(("t-1", "Python debugging"), ("t-2", "Python debugging"), ("t-3", "Debugging Python"), ("t-4", "Recipes"))})

        assert result.model_name == "served-model"
        assert [(folder.name, folder.thread_ids) for folder in result.folders] == [("Python", ["t-1", "t-2", "t-3"])]
        assert result.unfiled == ["t-4"]
        shares = [_organize_usage(thread_id)["served-model"] for thread_id in ("t-1", "t-2", "t-3", "t-4")]
        assert sum(share["total_tokens"] for share in shares) == USAGE["total_tokens"]
        assert sum(share["calls"] for share in shares) == 1
        assert aux_usage.get_thread_aux_usage("agent-generation") == {}
        assert stubs.model.ainvoke.await_args.kwargs["config"]["run_name"] == organize.CONSOLIDATE_RUN_NAME

    def test_an_unusable_reply_keeps_the_deterministic_plan_and_is_still_billed(self, stubs):
        _reply(stubs, "Sorry, I cannot do that.")

        result = _consolidate({"items": _items(("t-1", "Rust"), ("t-2", "Rust"), ("t-3", "Go"))})

        assert [(folder.name, folder.thread_ids) for folder in result.folders] == [("Rust", ["t-1", "t-2"])]
        assert result.unfiled == ["t-3"]
        assert sum(_organize_usage(thread_id)["served-model"]["calls"] for thread_id in ("t-1", "t-2", "t-3")) == 1

    def test_new_folders_never_exceed_the_registrys_room(self, stubs):
        """49 existing folders leave room for one: the registry would silently drop the rest."""
        _reply(stubs, json.dumps({"folders": [{"name": "Alpha", "labels": [1]}, {"name": "Beta", "labels": [2]}, {"name": "Gamma", "labels": [3]}]}))
        items = _items(*[(f"a-{n}", "Alpha") for n in range(3)], *[(f"b-{n}", "Beta") for n in range(2)], *[(f"c-{n}", "Gamma") for n in range(2)])

        result = _consolidate({"items": items, "existing": [{"id": f"e-{n}", "name": f"Existing {n}"} for n in range(49)], "max_new_folders": 8})

        assert [folder.name for folder in result.folders] == ["Alpha"]
        assert sorted(result.unfiled) == ["b-0", "b-1", "c-0", "c-1"]
        system, _ = _sent_prompt(stubs)
        assert "at most 1 new folder." in system

    def test_an_exhausted_spend_cap_refuses_a_merge_that_needs_the_model(self, stubs):
        stubs.spend.return_value = SimpleNamespace(exceeded=SimpleNamespace(period="daily", limit=1.0, spent=2.0), currency=None)

        with pytest.raises(HTTPException) as excinfo:
            _consolidate({"items": _items(("t-1", "Rust"), ("t-2", "Go"))})

        assert excinfo.value.status_code == 402
        stubs.factory.assert_not_called()

    def test_duplicate_thread_ids_count_once(self, stubs):
        result = _consolidate({"items": _items(("t-1", "Rust"), ("t-1", "Rust"), ("t-2", "Rust"))})

        assert result.folders[0].thread_ids == ["t-1", "t-2"]
        assert [call[0] for call in stubs.store.calls] == ["t-1", "t-2"]

    @pytest.mark.parametrize(
        "body",
        [
            {"items": []},
            {"items": _items(*[(f"t-{n}", "x") for n in range(organize.MAX_CONSOLIDATE_ITEMS + 1)])},
            {"items": _items(("bad.thread.id", "x"))},
            {"items": _items(("t-1", "x")), "max_new_folders": 0},
            {"items": _items(("t-1", "x")), "max_new_folders": organize.MAX_NEW_FOLDERS_LIMIT + 1},
            {"items": _items(("t-1", "x")), "min_group_size": 0},
            {"items": _items(("t-1", "x")), "existing": [{"id": f"e-{n}", "name": "n"} for n in range(51)]},
        ],
        ids=["no-items", "too-many-items", "bad-thread-id", "no-new-folders", "too-many-new-folders", "zero-group-size", "too-many-existing"],
    )
    def test_request_bounds(self, body):
        with pytest.raises(ValidationError):
            chat_organize.ConsolidateRequest(**body)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_the_routes_are_mounted_on_the_gateway():
    from app.gateway.app import create_app

    paths = {(method, route.path) for route in create_app().routes for method in (getattr(route, "methods", None) or ())}

    assert ("POST", "/api/threads/{thread_id}/organize/suggest") in paths
    assert ("POST", "/api/chat-organize/consolidate") in paths


def test_owner_check_guards_the_suggest_route(stubs):
    """Through the real decorator: another user's thread is a 404 before anything is read."""
    from _router_auth_helpers import make_authed_test_app
    from fastapi.testclient import TestClient

    from app.gateway.deps import get_config

    app = make_authed_test_app(owner_check_passes=False)
    app.include_router(chat_organize.router)
    app.dependency_overrides[get_config] = _config

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/threads/t-1/organize/suggest", json={"mode": "auto"})

    assert response.status_code == 404
    stubs.build_accessor.assert_not_awaited()
    stubs.factory.assert_not_called()
