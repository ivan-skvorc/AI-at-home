"""The cost estimate has to survive the three things a real conversation does.

The header's cost number is only useful if it still tells the truth after the
conversation has been lived in. Three events break a naive implementation, and
each one is a section below:

1. **The Gateway restarts** (or the user hits stop, or a run times out). The
   run's tokens were already sent to the provider and already persisted by the
   journal, but the run never reaches ``success``. Counting only successful runs
   makes a restart *delete money* from the header — while the spend page and the
   currency cap, which have no status filter, keep charging for it. A header
   that disagrees with the cap displayed beside it is worse than no header.

2. **The model changes mid-conversation**, which is the whole point of a
   personal deployment that mixes premium, cheap, and local models. Every turn
   has to be priced at the rate of the model that actually ran it, and a model
   later removed from ``config.yaml`` has to be *named* rather than quietly
   dropped from the total.

3. **An earlier message is edited**, which supersedes the turns that followed
   it. That spend really happened, so it stays in the total; but the superseded
   runs are no longer turns of the conversation, so they must not be steps in
   the chart — otherwise the chart shows more steps than the thread has turns
   and "step 3" is not the third thing the user asked. The discarded spend is
   reported on its own, so the total can be read as
   ``what you can still see + what you replaced``.

These are the regression tests to run (and extend) whenever anything touching
pricing, the run stores, or the token-usage endpoint changes; FORK.md §7 lists
them under *Verify it works*.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.pricing import build_pricing_map
from app.gateway.routers import thread_runs
from deerflow.runtime import RunStatus, aux_usage
from deerflow.runtime.runs.store.base import ACTIVE_RUN_STATUS, COUNTED_RUN_STATUSES
from deerflow.runtime.runs.store.memory import MemoryRunStore

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _priced_map():
    """An expensive lead model and a cheap one, so a switch is visible."""
    return build_pricing_map(
        [
            SimpleNamespace(name="Opus", model="claude-opus-5", pricing={"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            SimpleNamespace(name="Haiku", model="claude-haiku-4-5", pricing={"currency": "USD", "input_per_million": 1, "output_per_million": 5}),
        ],
    )


async def _turn(
    store: MemoryRunStore,
    thread: str,
    run_id: str,
    usage: dict[str, dict],
    *,
    created_at: str,
    status: str = "success",
) -> None:
    """Record one run that burned ``usage`` and ended in ``status``."""
    total = sum(u.get("total_tokens", 0) for u in usage.values())
    await store.put(run_id, thread_id=thread, status="pending", model_name=next(iter(usage)), created_at=created_at)
    await store.update_run_completion(
        run_id,
        status=status,
        total_input_tokens=sum(u.get("input_tokens", 0) for u in usage.values()),
        total_output_tokens=sum(u.get("output_tokens", 0) for u in usage.values()),
        total_tokens=total,
        llm_call_count=1,
        lead_agent_tokens=total,
        subagent_tokens=0,
        middleware_tokens=0,
        token_usage_by_model=usage,
        message_count=0,
    )


def _opus(input_tokens: int, output_tokens: int) -> dict[str, dict]:
    return {"claude-opus-5": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_tokens": 0, "total_tokens": input_tokens + output_tokens}}


def _haiku(input_tokens: int, output_tokens: int) -> dict[str, dict]:
    return {"claude-haiku-4-5": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_tokens": 0, "total_tokens": input_tokens + output_tokens}}


def _make_app(run_store, run_manager=None):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    if run_manager is not None:
        app.state.run_manager = run_manager
    return app


def _fake_run_manager(*, hidden_sources: set[str] | None = None, hidden_attempts: set[str] | None = None, regenerate_sources: set[str] | None = None) -> MagicMock:
    """A run manager that reports which runs the history hides."""
    manager = MagicMock()
    manager.list_successful_regenerate_sources = AsyncMock(return_value=set(regenerate_sources or ()))
    manager.list_edit_replay_visibility = AsyncMock(
        return_value=SimpleNamespace(
            hidden_source_run_ids=set(hidden_sources or ()),
            hidden_attempt_run_ids=set(hidden_attempts or ()),
        )
    )
    return manager


def _endpoint_json(monkeypatch: pytest.MonkeyPatch, store, *, run_manager=None, pricing=None) -> dict:
    aux_usage.reset_aux_usage()
    monkeypatch.setattr(thread_runs, "build_context_usage", AsyncMock(return_value=None))
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", lambda: _priced_map() if pricing is None else pricing)
    with TestClient(_make_app(store, run_manager)) as client:
        response = client.get("/api/threads/t/token-usage")
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# 1. The spend survives a restart
# ---------------------------------------------------------------------------


class TestSpendSurvivesARestart:
    """A run the Gateway never got to finish still spent the money it spent."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("status", ["interrupted", "timeout"])
    async def test_a_run_that_never_reached_success_keeps_its_spend(self, status: str) -> None:
        # The shape of a restart: the drain marks every in-flight run
        # ``interrupted`` after the journal has already persisted its tokens.
        store = MemoryRunStore()
        await _turn(store, "t", "finished", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "killed", _opus(2_000_000, 200_000), created_at="2026-08-01T10:05:00Z", status=status)

        agg = await store.aggregate_tokens_by_thread("t")

        assert agg["total_runs"] == 2
        assert agg["total_tokens"] == 3_300_000
        assert [b["run_id"] for b in agg["by_run"]] == ["finished", "killed"]

    @pytest.mark.anyio
    async def test_a_pending_run_that_never_called_a_model_adds_nothing(self) -> None:
        # Not every unfinished run spent something: one that never started has
        # no tokens to count and no step to draw.
        store = MemoryRunStore()
        await store.put("queued", thread_id="t", status="pending", created_at="2026-08-01T10:00:00Z")

        agg = await store.aggregate_tokens_by_thread("t")

        assert agg["total_runs"] == 0
        assert agg["by_run"] == []

    @pytest.mark.anyio
    async def test_the_endpoint_prices_an_interrupted_turn_like_any_other(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryRunStore()
        await _turn(store, "t", "killed", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z", status="interrupted")

        payload = _endpoint_json(monkeypatch, store)

        # 1M input @ $5 + 0.1M output @ $25 = 7.5
        assert payload["total_cost"] == pytest.approx(7.5)
        assert [s["cost"] for s in payload["steps"]] == [pytest.approx(7.5)]

    @pytest.mark.anyio
    async def test_the_sql_store_agrees_with_the_memory_store(self, tmp_path) -> None:
        # Two implementations of one number: a restart that changes the total
        # only on the SQL path is the version a user would actually hit.
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.persistence.run import RunRepository

        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}", sqlite_dir=str(tmp_path))
        try:
            repo = RunRepository(get_session_factory())
            memory = MemoryRunStore()
            for store in (repo, memory):
                await _turn(store, "t", "finished", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
                await _turn(store, "t", "killed", _haiku(2_000_000, 200_000), created_at="2026-08-01T10:05:00Z", status="interrupted")

            sql_agg = await repo.aggregate_tokens_by_thread("t")
            memory_agg = await memory.aggregate_tokens_by_thread("t")

            assert sql_agg["total_tokens"] == memory_agg["total_tokens"] == 3_300_000
            assert sql_agg["by_model"] == memory_agg["by_model"]
            assert [b["run_id"] for b in sql_agg["by_run"]] == [b["run_id"] for b in memory_agg["by_run"]]
        finally:
            await close_engine()

    def test_every_terminal_status_is_decided_on_deliberately(self) -> None:
        # A new lifecycle status must not join the enum and silently fall out of
        # the cost total. Counted or excluded is a decision; defaulting to
        # "excluded" by omission is the bug this file exists for.
        decided = set(COUNTED_RUN_STATUSES) | {ACTIVE_RUN_STATUS, RunStatus.pending.value}
        assert {status.value for status in RunStatus} == decided

    def test_the_counted_statuses_are_the_ones_the_spend_cap_charges_for(self) -> None:
        # ``resolve_spend_budget_status`` prices every run row in the window
        # regardless of status, so any terminal status it charges for must also
        # reach the header. Only ``pending`` (never ran, no tokens) is exempt.
        terminal = {status.value for status in RunStatus} - {RunStatus.pending.value, RunStatus.running.value}
        assert terminal <= set(COUNTED_RUN_STATUSES)


# ---------------------------------------------------------------------------
# 2. The model changes mid-conversation
# ---------------------------------------------------------------------------


class TestModelChangedMidConversation:
    @pytest.mark.anyio
    async def test_each_turn_is_priced_at_the_model_that_ran_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryRunStore()
        await _turn(store, "t", "r1", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "r2", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:05:00Z")

        payload = _endpoint_json(monkeypatch, store)

        # Opus 1M@5 + 0.1M@25 = 7.5; Haiku 1M@1 + 0.1M@5 = 1.5.
        assert [s["cost"] for s in payload["steps"]] == [pytest.approx(7.5), pytest.approx(1.5)]
        assert payload["total_cost"] == pytest.approx(9.0)

    @pytest.mark.anyio
    async def test_a_model_dropped_from_the_config_is_named_not_silently_lost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Switching to a model and later removing it from ``config.yaml`` is the
        # realistic way a historical thread loses its price. The total must keep
        # what it can price and say which model it could not.
        store = MemoryRunStore()
        await _turn(store, "t", "r1", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "r2", {"gone-from-config": {"input_tokens": 500_000, "output_tokens": 50_000, "cache_read_tokens": 0, "total_tokens": 550_000}}, created_at="2026-08-01T10:05:00Z")

        payload = _endpoint_json(monkeypatch, store)

        assert payload["total_cost"] == pytest.approx(7.5)
        assert payload["unpriced_models"] == ["gone-from-config"]
        # A gap, not a zero: an unpriced turn draws no column.
        assert [s["cost"] for s in payload["steps"]] == [pytest.approx(7.5), None]


# ---------------------------------------------------------------------------
# 3. An earlier message is edited
# ---------------------------------------------------------------------------


class TestEditingAnEarlierMessage:
    """Editing rewrites the conversation; it does not refund the old one."""

    @pytest.mark.anyio
    async def test_a_superseded_turn_stays_in_the_thread_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryRunStore()
        await _turn(store, "t", "replaced", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "replacement", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:05:00Z")

        payload = _endpoint_json(monkeypatch, store, run_manager=_fake_run_manager(hidden_sources={"replaced"}))

        # 7.5 spent on the turn the edit threw away + 1.5 on its replacement.
        assert payload["total_cost"] == pytest.approx(9.0)

    @pytest.mark.anyio
    async def test_a_superseded_turn_is_not_a_step_in_the_chart(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryRunStore()
        await _turn(store, "t", "replaced", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "replacement", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:05:00Z")

        payload = _endpoint_json(monkeypatch, store, run_manager=_fake_run_manager(hidden_sources={"replaced"}))

        assert [s["run_id"] for s in payload["steps"]] == ["replacement"]

    @pytest.mark.anyio
    async def test_steps_are_renumbered_so_step_n_is_the_nth_visible_turn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryRunStore()
        await _turn(store, "t", "r1", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "replaced", _opus(1_000_000, 100_000), created_at="2026-08-01T10:05:00Z")
        await _turn(store, "t", "replacement", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:10:00Z")

        payload = _endpoint_json(monkeypatch, store, run_manager=_fake_run_manager(hidden_sources={"replaced"}))

        assert [(s["index"], s["run_id"]) for s in payload["steps"]] == [(1, "r1"), (2, "replacement")]

    @pytest.mark.anyio
    async def test_the_replaced_spend_is_reported_on_its_own(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryRunStore()
        await _turn(store, "t", "replaced", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "replacement", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:05:00Z")

        payload = _endpoint_json(monkeypatch, store, run_manager=_fake_run_manager(hidden_sources={"replaced"}))

        assert payload["superseded_cost"] == pytest.approx(7.5)
        assert payload["superseded_runs"] == 1
        assert payload["superseded_tokens"] == 1_100_000

    @pytest.mark.anyio
    async def test_the_visible_steps_plus_the_replaced_spend_equal_the_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The chart's last cumulative point no longer equals the headline total
        # once a turn has been replaced — so the relationship that has to hold
        # is this one, and the header states it in words.
        store = MemoryRunStore()
        await _turn(store, "t", "r1", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "replaced", _opus(1_000_000, 100_000), created_at="2026-08-01T10:05:00Z")
        await _turn(store, "t", "replacement", _haiku(2_000_000, 200_000), created_at="2026-08-01T10:10:00Z")

        payload = _endpoint_json(monkeypatch, store, run_manager=_fake_run_manager(hidden_sources={"replaced"}))

        visible = sum(step["cost"] or 0.0 for step in payload["steps"])
        assert visible + payload["superseded_cost"] == pytest.approx(payload["total_cost"])

    @pytest.mark.anyio
    async def test_a_failed_edit_attempt_counts_as_replaced_spend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An edit that errored is hidden from the transcript but still burned
        # tokens on the way to failing.
        store = MemoryRunStore()
        await _turn(store, "t", "r1", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "attempt", _opus(1_000_000, 100_000), created_at="2026-08-01T10:05:00Z", status="error")

        payload = _endpoint_json(monkeypatch, store, run_manager=_fake_run_manager(hidden_attempts={"attempt"}))

        assert [s["run_id"] for s in payload["steps"]] == ["r1"]
        assert payload["superseded_cost"] == pytest.approx(7.5)

    @pytest.mark.anyio
    async def test_a_regenerated_answer_counts_as_replaced_spend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryRunStore()
        await _turn(store, "t", "first-answer", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        await _turn(store, "t", "regenerated", _haiku(1_000_000, 100_000), created_at="2026-08-01T10:05:00Z")

        payload = _endpoint_json(monkeypatch, store, run_manager=_fake_run_manager(regenerate_sources={"first-answer"}))

        assert [s["run_id"] for s in payload["steps"]] == ["regenerated"]
        assert payload["superseded_cost"] == pytest.approx(7.5)

    @pytest.mark.anyio
    async def test_an_unedited_thread_reports_no_replaced_spend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Null rather than 0.0, so the UI can drop the row entirely instead of
        # printing "$0.00 replaced" on every conversation that was never edited.
        store = MemoryRunStore()
        await _turn(store, "t", "r1", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")

        payload = _endpoint_json(monkeypatch, store, run_manager=_fake_run_manager())

        assert payload["superseded_cost"] is None
        assert payload["superseded_runs"] == 0

    @pytest.mark.anyio
    async def test_a_missing_run_manager_still_reports_every_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A broken counter never breaks the feature it is counting: if the
        # visibility lookup is unavailable, show every step rather than 500.
        store = MemoryRunStore()
        await _turn(store, "t", "r1", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")

        payload = _endpoint_json(monkeypatch, store)  # no run_manager on app.state

        assert [s["run_id"] for s in payload["steps"]] == ["r1"]
        assert payload["total_cost"] == pytest.approx(7.5)
        assert payload["superseded_cost"] is None

    @pytest.mark.anyio
    async def test_a_visibility_lookup_failure_degrades_to_every_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryRunStore()
        await _turn(store, "t", "r1", _opus(1_000_000, 100_000), created_at="2026-08-01T10:00:00Z")
        manager = _fake_run_manager()
        manager.list_edit_replay_visibility = AsyncMock(side_effect=RuntimeError("store down"))

        payload = _endpoint_json(monkeypatch, store, run_manager=manager)

        assert [s["run_id"] for s in payload["steps"]] == ["r1"]
        assert payload["total_cost"] == pytest.approx(7.5)
