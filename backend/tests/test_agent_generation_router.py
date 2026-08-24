"""Tests for the agent-generation HTTP route.

Covers the parts the pure layer cannot: the feature switches, per-source
ownership checks, source de-duplication and capping, and the failure modes of
the single LLM call. The route handler is invoked through ``__wrapped__`` to
bypass the ``require_permission`` decorator (which needs a real request and
thread store); ownership is exercised directly against the fake thread store.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.gateway.routers import agent_generation
from deerflow.config.agent_generation_config import AgentGenerationConfig
from deerflow.utils import oneshot_llm

PROPOSE_REPLY = '{"verdict": "propose", "rationale": "recurring weekly reporting", "proposal": {"name": "Report Writer", "description": "writes the weekly report", "soul": "**Identity**\\nA report writer."}}'
NO_GAP_REPLY = '{"verdict": "no_gap", "rationale": "one-off work", "covered_by": "researcher"}'


class FakeThreadStore:
    def __init__(self, *, allowed: bool = True, display_name: str = "Weekly report"):
        self._allowed = allowed
        self._display_name = display_name

    async def check_access(self, thread_id, user_id, *, require_existing=False):
        return self._allowed

    async def get(self, thread_id):
        return {"thread_id": thread_id, "display_name": self._display_name}


class FakeEventStore:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else [{"event_type": "llm.human.input", "category": "message", "content": {"content": "Write the weekly report"}}]
        self.calls: list[dict] = []

    async def list_messages(self, thread_id, *, limit=50, before_seq=None, after_seq=None, user_id=None):
        self.calls.append({"thread_id": thread_id, "limit": limit, "user_id": user_id})
        return self._rows


class FakeTaskRepo:
    def __init__(self, task=None):
        self._task = task if task is not None else {"title": "Monday digest", "prompt": "Summarize the week", "schedule_type": "cron", "status": "active"}

    async def get(self, task_id, *, user_id=None):
        return self._task


class FakeTaskRunRepo:
    async def list_by_task(self, task_id, *, limit=50, offset=0):
        return [{"status": "succeeded", "started_at": "2026-01-05T09:00:00Z"}]


@pytest.fixture
def wiring(monkeypatch):
    """Stub every collaborator the route reaches for, and hand the fakes back."""
    thread_store = FakeThreadStore()
    event_store = FakeEventStore()
    task_repo = FakeTaskRepo()
    task_run_repo = FakeTaskRunRepo()

    monkeypatch.setattr(agent_generation, "get_thread_store", lambda request: thread_store)
    monkeypatch.setattr(agent_generation, "get_run_event_store", lambda request: event_store)
    monkeypatch.setattr(agent_generation, "get_scheduled_task_repo", lambda request: task_repo)
    monkeypatch.setattr(agent_generation, "get_scheduled_task_run_repo", lambda request: task_run_repo)
    monkeypatch.setattr(agent_generation, "get_optional_user_from_request", AsyncMock(return_value=SimpleNamespace(id="u1")))
    monkeypatch.setattr(agent_generation, "get_agents_api_config", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(agent_generation, "list_custom_agents", lambda user_id=None: [SimpleNamespace(name="researcher", description="digs into papers")])
    # Aux accounting writes to a durable store; keep the unit tests off the disk.
    monkeypatch.setattr(agent_generation, "arecord_aux_usage", AsyncMock())

    return SimpleNamespace(thread_store=thread_store, event_store=event_store, task_repo=task_repo, task_run_repo=task_run_repo)


def _config(**overrides):
    return SimpleNamespace(agent_generation=AgentGenerationConfig(enabled=True, **overrides))


def _stub_model(monkeypatch, content: str):
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content=content, response_metadata={"model_name": "test-model"}, usage_metadata={"input_tokens": 10, "output_tokens": 5}))
    monkeypatch.setattr(oneshot_llm, "create_chat_model", lambda **kwargs: fake_model)
    return fake_model


def _analyze(body, config=None):
    return asyncio.run(agent_generation.analyze_sources.__wrapped__(body, request=None, config=config or _config()))


def _thread_request(*ids):
    return agent_generation.AnalyzeRequest(sources=[agent_generation.GenerationSource(kind="thread", id=i) for i in ids])


# ---------------------------------------------------------------------------
# Feature switches
# ---------------------------------------------------------------------------


def test_config_route_reports_disabled_when_generation_is_off(monkeypatch):
    monkeypatch.setattr(agent_generation, "get_agents_api_config", lambda: SimpleNamespace(enabled=True))
    result = asyncio.run(agent_generation.get_generation_config(config=SimpleNamespace(agent_generation=AgentGenerationConfig(enabled=False))))
    assert result.enabled is False


def test_config_route_reports_disabled_when_agents_api_is_off(monkeypatch):
    # A draft the user cannot save is a dead end, so the UI entry point must be
    # hidden when the create route is unavailable — not only when generation is.
    monkeypatch.setattr(agent_generation, "get_agents_api_config", lambda: SimpleNamespace(enabled=False))
    result = asyncio.run(agent_generation.get_generation_config(config=_config()))
    assert result.enabled is False


def test_config_route_reports_limits(monkeypatch):
    monkeypatch.setattr(agent_generation, "get_agents_api_config", lambda: SimpleNamespace(enabled=True))
    result = asyncio.run(agent_generation.get_generation_config(config=_config(max_sources=3, model_name="fast-model")))
    assert (result.enabled, result.max_sources, result.default_model_name) == (True, 3, "fast-model")


def test_analyze_is_404_when_generation_is_disabled(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_thread_request("t1"), config=SimpleNamespace(agent_generation=AgentGenerationConfig(enabled=False)))
    assert exc.value.status_code == 404


def test_analyze_is_403_when_agents_api_is_disabled(wiring, monkeypatch):
    monkeypatch.setattr(agent_generation, "get_agents_api_config", lambda: SimpleNamespace(enabled=False))
    _stub_model(monkeypatch, NO_GAP_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_thread_request("t1"))
    assert exc.value.status_code == 403


def test_analyze_requires_an_authenticated_user(wiring, monkeypatch):
    monkeypatch.setattr(agent_generation, "get_optional_user_from_request", AsyncMock(return_value=None))
    _stub_model(monkeypatch, NO_GAP_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_thread_request("t1"))
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Source handling
# ---------------------------------------------------------------------------


def test_analyze_rejects_threads_the_caller_does_not_own(wiring, monkeypatch):
    wiring.thread_store._allowed = False
    _stub_model(monkeypatch, NO_GAP_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_thread_request("someone-elses-thread"))
    assert exc.value.status_code == 404


def test_analyze_scopes_message_reads_to_the_caller(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    _analyze(_thread_request("t1"))
    assert wiring.event_store.calls[0]["user_id"] == "u1"


def test_analyze_rejects_a_missing_scheduled_task(wiring, monkeypatch):
    wiring.task_repo._task = None
    _stub_model(monkeypatch, NO_GAP_REPLY)
    body = agent_generation.AnalyzeRequest(sources=[agent_generation.GenerationSource(kind="scheduled_task", id="s1")])
    with pytest.raises(HTTPException) as exc:
        _analyze(body)
    assert exc.value.status_code == 404


def test_analyze_deduplicates_repeated_sources(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    result = _analyze(_thread_request("t1", "t1", "t1"))
    assert result.analyzed_sources == 1
    assert len(wiring.event_store.calls) == 1


def test_analyze_rejects_more_sources_than_configured(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_thread_request("t1", "t2", "t3"), config=_config(max_sources=2))
    assert exc.value.status_code == 422


def test_analyze_rejects_sources_with_no_readable_content(wiring, monkeypatch):
    wiring.event_store._rows = [{"event_type": "llm.tool.result", "category": "message", "content": {"content": "x"}}]
    _stub_model(monkeypatch, NO_GAP_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_thread_request("t1"))
    assert exc.value.status_code == 422


def test_analyze_reads_more_rows_than_the_message_cap(wiring, monkeypatch):
    # Tool results and empty turns are dropped during digestion, so fetching
    # exactly max_messages rows would leave a busy conversation nearly empty.
    _stub_model(monkeypatch, NO_GAP_REPLY)
    _analyze(_thread_request("t1"), config=_config(max_messages_per_source=10))
    assert wiring.event_store.calls[0]["limit"] > 10


def test_analyze_accepts_a_mixed_selection_of_threads_and_tasks(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    body = agent_generation.AnalyzeRequest(
        sources=[
            agent_generation.GenerationSource(kind="thread", id="t1"),
            agent_generation.GenerationSource(kind="scheduled_task", id="s1"),
        ]
    )
    assert _analyze(body).analyzed_sources == 2


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def test_analyze_returns_a_no_gap_verdict(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    result = _analyze(_thread_request("t1"))
    assert result.verdict == "no_gap"
    assert result.covered_by == "researcher"
    assert result.proposal is None
    assert result.model_name == "test-model"


def test_analyze_returns_a_proposal(wiring, monkeypatch):
    _stub_model(monkeypatch, PROPOSE_REPLY)
    result = _analyze(_thread_request("t1"))
    assert result.verdict == "propose"
    assert result.proposal is not None
    assert result.proposal.name == "report-writer"
    assert result.proposal.soul.startswith("**Identity**")


def test_analyze_never_creates_the_agent_itself(wiring, monkeypatch):
    # The proposal must reach the user for review; persisting it here would let
    # a hallucinated draft become a real agent with no human in the loop.
    from deerflow.persistence import agents as agents_persistence

    store = MagicMock()
    monkeypatch.setattr(agents_persistence, "get_agent_store", lambda: store)
    _stub_model(monkeypatch, PROPOSE_REPLY)
    _analyze(_thread_request("t1"))
    store.create.assert_not_called()
    store.update.assert_not_called()


def test_analyze_proposal_name_avoids_the_users_existing_agents(wiring, monkeypatch):
    monkeypatch.setattr(agent_generation, "list_custom_agents", lambda user_id=None: [SimpleNamespace(name="report-writer", description="d")])
    _stub_model(monkeypatch, PROPOSE_REPLY)
    result = _analyze(_thread_request("t1"))
    assert result.proposal is not None
    assert result.proposal.name == "report-writer-2"


def test_analyze_passes_existing_agents_to_the_model(wiring, monkeypatch):
    fake_model = _stub_model(monkeypatch, NO_GAP_REPLY)
    _analyze(_thread_request("t1"))
    system_message = fake_model.ainvoke.await_args.args[0][0]
    assert "researcher" in system_message.content


def test_analyze_uses_the_requested_model(wiring, monkeypatch):
    captured: dict = {}

    def _create(**kwargs):
        captured.update(kwargs)
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=MagicMock(content=NO_GAP_REPLY, response_metadata={}, usage_metadata=None))
        return model

    monkeypatch.setattr(oneshot_llm, "create_chat_model", _create)
    body = agent_generation.AnalyzeRequest(sources=[agent_generation.GenerationSource(kind="thread", id="t1")], model_name="picked-model")
    _analyze(body)
    assert captured["name"] == "picked-model"


def test_analyze_falls_back_to_the_configured_model(wiring, monkeypatch):
    captured: dict = {}

    def _create(**kwargs):
        captured.update(kwargs)
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=MagicMock(content=NO_GAP_REPLY, response_metadata={}, usage_metadata=None))
        return model

    monkeypatch.setattr(oneshot_llm, "create_chat_model", _create)
    _analyze(_thread_request("t1"), config=_config(model_name="configured-model"))
    assert captured["name"] == "configured-model"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_analyze_reports_an_unreachable_model_as_502(wiring, monkeypatch):
    def _create(**kwargs):
        model = MagicMock()
        model.ainvoke = AsyncMock(side_effect=RuntimeError("connection refused"))
        return model

    monkeypatch.setattr(oneshot_llm, "create_chat_model", _create)
    with pytest.raises(HTTPException) as exc:
        _analyze(_thread_request("t1"))
    assert exc.value.status_code == 502


def test_analyze_reports_an_unusable_reply_as_502(wiring, monkeypatch):
    _stub_model(monkeypatch, "I think you should make an agent!")
    with pytest.raises(HTTPException) as exc:
        _analyze(_thread_request("t1"))
    assert exc.value.status_code == 502


def test_analyze_records_aux_usage(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    _analyze(_thread_request("t1"))
    agent_generation.arecord_aux_usage.assert_awaited_once()
    args, kwargs = agent_generation.arecord_aux_usage.await_args
    assert args[1] == agent_generation.USAGE_CATEGORY
    assert kwargs["input_tokens"] == 10


def test_analyze_survives_an_aux_usage_failure(wiring, monkeypatch):
    # Accounting is best-effort: a broken counter must not cost the user their
    # analysis, which has already been paid for at the provider.
    monkeypatch.setattr(agent_generation, "arecord_aux_usage", AsyncMock(side_effect=RuntimeError("store down")))
    _stub_model(monkeypatch, NO_GAP_REPLY)
    assert _analyze(_thread_request("t1")).verdict == "no_gap"


# ---------------------------------------------------------------------------
# Goal, forced drafts, and revision
# ---------------------------------------------------------------------------


def _goal_request(goal, *, force=False, revise_from=None, ids=("t1",)):
    return agent_generation.AnalyzeRequest(
        sources=[agent_generation.GenerationSource(kind="thread", id=i) for i in ids],
        goal=goal,
        force_proposal=force,
        revise_from=revise_from,
    )


def _draft_input(soul="**Identity**\nA report writer."):
    return agent_generation.DraftInput(name="report-writer", description="writes reports", soul=soul)


def _sent_messages(fake_model):
    return fake_model.ainvoke.await_args.args[0]


def test_config_route_reports_the_goal_cap(monkeypatch):
    monkeypatch.setattr(agent_generation, "get_agents_api_config", lambda: SimpleNamespace(enabled=True))
    result = asyncio.run(agent_generation.get_generation_config(config=_config(max_goal_chars=500)))
    assert result.max_goal_chars == 500


def test_goal_reaches_the_model(wiring, monkeypatch):
    fake_model = _stub_model(monkeypatch, NO_GAP_REPLY)
    _analyze(_goal_request("write my weekly client updates"))
    user_message = _sent_messages(fake_model)[1]
    assert "<goal>\nwrite my weekly client updates\n</goal>" in user_message.content


def test_goal_switches_the_system_instruction(wiring, monkeypatch):
    fake_model = _stub_model(monkeypatch, NO_GAP_REPLY)
    _analyze(_goal_request("write my weekly client updates"))
    assert "<goal> block" in _sent_messages(fake_model)[0].content


def test_a_goal_does_not_force_a_proposal(wiring, monkeypatch):
    # The goal steers the analysis; the verdict stays the model's to make.
    _stub_model(monkeypatch, NO_GAP_REPLY)
    result = _analyze(_goal_request("write my weekly client updates"))
    assert result.verdict == "no_gap"
    assert result.forced is False


def test_blank_goal_is_treated_as_absent(wiring, monkeypatch):
    fake_model = _stub_model(monkeypatch, NO_GAP_REPLY)
    _analyze(_goal_request("   "))
    assert "<goal>" not in _sent_messages(fake_model)[1].content


def test_goal_over_the_cap_is_rejected(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_goal_request("x" * 51), config=_config(max_goal_chars=50))
    assert exc.value.status_code == 422
    assert "50" in exc.value.detail


def test_goal_at_the_cap_is_accepted(wiring, monkeypatch):
    _stub_model(monkeypatch, NO_GAP_REPLY)
    assert _analyze(_goal_request("x" * 50), config=_config(max_goal_chars=50)).verdict == "no_gap"


def test_force_proposal_marks_the_result_forced(wiring, monkeypatch):
    _stub_model(monkeypatch, PROPOSE_REPLY)
    result = _analyze(_goal_request(None, force=True))
    assert result.forced is True
    assert result.proposal is not None


def test_force_proposal_rejects_a_no_gap_reply(wiring, monkeypatch):
    # The user overrode the verdict; the model returning it anyway is a failure
    # to follow instructions, not an answer to surface.
    _stub_model(monkeypatch, NO_GAP_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_goal_request(None, force=True))
    assert exc.value.status_code == 502


def test_revision_requires_guidance(wiring, monkeypatch):
    # "Refine" with an empty box has nothing to act on.
    _stub_model(monkeypatch, PROPOSE_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_goal_request(None, revise_from=_draft_input()))
    assert exc.value.status_code == 422


def test_revision_implies_force(wiring, monkeypatch):
    _stub_model(monkeypatch, PROPOSE_REPLY)
    assert _analyze(_goal_request("make it shorter", revise_from=_draft_input())).forced is True


def test_revision_sends_the_draft_and_the_guidance(wiring, monkeypatch):
    fake_model = _stub_model(monkeypatch, PROPOSE_REPLY)
    _analyze(_goal_request("make it shorter", revise_from=_draft_input()))
    system, user = _sent_messages(fake_model)
    assert "revising a DRAFT" in system.content
    assert '<draft name="report-writer"' in user.content
    assert "<goal>\nmake it shorter\n</goal>" in user.content


def test_revision_uses_its_own_run_name(wiring, monkeypatch):
    fake_model = _stub_model(monkeypatch, PROPOSE_REPLY)
    _analyze(_goal_request("shorter", revise_from=_draft_input()))
    assert fake_model.ainvoke.await_args.kwargs["config"]["run_name"] == "agent_generation_revision"


def test_revision_keeps_the_drafts_own_name(wiring, monkeypatch):
    # Uniquifying against the roster on every refine would rename the agent out
    # from under the user mid-edit.
    monkeypatch.setattr(agent_generation, "list_custom_agents", lambda user_id=None: [SimpleNamespace(name="report-writer", description="d")])
    _stub_model(monkeypatch, PROPOSE_REPLY)
    result = _analyze(_goal_request("shorter", revise_from=_draft_input()))
    assert result.proposal is not None
    assert result.proposal.name == "report-writer"


def test_a_fresh_analysis_still_uniquifies_the_name(wiring, monkeypatch):
    monkeypatch.setattr(agent_generation, "list_custom_agents", lambda user_id=None: [SimpleNamespace(name="report-writer", description="d")])
    _stub_model(monkeypatch, PROPOSE_REPLY)
    result = _analyze(_goal_request("write reports"))
    assert result.proposal is not None
    assert result.proposal.name == "report-writer-2"


def test_revision_still_never_creates_the_agent(wiring, monkeypatch):
    from deerflow.persistence import agents as agents_persistence

    store = MagicMock()
    monkeypatch.setattr(agents_persistence, "get_agent_store", lambda: store)
    _stub_model(monkeypatch, PROPOSE_REPLY)
    _analyze(_goal_request("shorter", revise_from=_draft_input()))
    store.create.assert_not_called()
    store.update.assert_not_called()


def test_revision_still_checks_source_ownership(wiring, monkeypatch):
    # The override skips the verdict, never the authorization.
    wiring.thread_store._allowed = False
    _stub_model(monkeypatch, PROPOSE_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_goal_request("shorter", revise_from=_draft_input()))
    assert exc.value.status_code == 404


def test_forced_draft_still_checks_source_ownership(wiring, monkeypatch):
    wiring.thread_store._allowed = False
    _stub_model(monkeypatch, PROPOSE_REPLY)
    with pytest.raises(HTTPException) as exc:
        _analyze(_goal_request(None, force=True))
    assert exc.value.status_code == 404
