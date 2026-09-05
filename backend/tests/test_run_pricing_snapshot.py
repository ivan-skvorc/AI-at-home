"""A reply keeps the price it was billed at.

Cost used to be recomputed from the live ``config.yaml`` on every read, which
made a historical figure a statement about today's roster rather than about what
the run cost. Two ways that goes wrong, and neither raises anything:

* **A price moves.** Re-pricing a model rewrites every total that model ever
  appeared in — last month's conversation quietly reports a different bill.
* **A model leaves the roster.** ``lookup_pricing`` stops resolving it, so its
  runs contribute *nothing* and the conversation gets **cheaper**. This is not a
  hypothetical: rolling an entry forward (Grok 4.5 → 4.6, a ``*-latest`` alias
  pinned to a dated id) is a routine outcome of the model audit in FORK.md, so
  the roster is *expected* to move out from under old runs.

``runs.pricing_snapshot`` records the rates in effect when the run finished, and
the read path prefers it per model. What that has to keep true is asserted here:
the snapshot wins, an absent snapshot still falls back to the live config, a
deployment that switched currency is not silently summed, and cost reporting
that is switched off stays off.

Run from ``backend/``:
    uv run pytest tests/test_run_pricing_snapshot.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from deerflow.pricing import (
    build_pricing_map,
    pricing_map_from_snapshot,
    resolve_run_pricing,
    run_cost,
    snapshot_pricing,
)


def _model(name: str, model: str, price_in: float, price_out: float, **extra) -> SimpleNamespace:
    return SimpleNamespace(name=name, model=model, display_name=name, pricing=None, price={"currency": "USD", "input": price_in, "output": price_out, **extra}, discount=None)


def _live_map(*models: SimpleNamespace) -> dict:
    return build_pricing_map(list(models))


# ---------------------------------------------------------------------------
# Taking the snapshot
# ---------------------------------------------------------------------------


class TestSnapshotCapture:
    def test_it_records_the_models_the_run_actually_used(self):
        models = [_model("Lead", "lead-model", 5.0, 25.0), _model("Unused", "other-model", 99.0, 99.0)]
        snapshot = snapshot_pricing(models, {"lead-model": {"input_tokens": 1000, "output_tokens": 10}})

        assert set(snapshot) == {"lead-model"}, "a run should not carry prices for models it never called"
        assert snapshot["lead-model"]["input_per_million"] == 5.0
        assert snapshot["lead-model"]["output_per_million"] == 25.0
        assert snapshot["lead-model"]["currency"] == "USD"

    def test_a_provider_reported_alias_is_snapshotted_under_the_key_the_reader_uses(self):
        # LangChain records the API-resolved id, so an undated Anthropic alias
        # comes back dated. The snapshot has to be keyed the way the token
        # buckets are keyed or the read path cannot find it.
        snapshot = snapshot_pricing([_model("Opus", "claude-opus-5", 5.0, 25.0)], {"claude-opus-5-20260115": {"input_tokens": 10}})

        assert set(snapshot) == {"claude-opus-5-20260115"}
        assert snapshot["claude-opus-5-20260115"]["input_per_million"] == 5.0

    def test_an_unpriced_model_is_simply_absent(self):
        # Absent means "fall back to the live config", which is also what a run
        # written before the column existed says. One meaning, not two.
        assert snapshot_pricing([], {"ollama-local": {"input_tokens": 10}}) == {}

    def test_a_live_discount_is_captured_beside_the_standard_rate(self):
        model = _model("MiniMax", "minimax-m3", 0.6, 2.4)
        model.discount = {"input": 0.24, "output": 0.96}
        snapshot = snapshot_pricing([model], {"minimax-m3": {"input_tokens": 10}})

        entry = snapshot["minimax-m3"]
        assert entry["input_per_million"] == 0.6, "cost is billed at the standard rate, so it must survive"
        assert entry["promo_input_per_million"] == 0.24

    def test_it_never_raises_on_a_broken_config(self):
        # Cost bookkeeping must not be able to fail a run that already answered.
        class Exploding:
            def __iter__(self):
                raise RuntimeError("config blew up")

        assert snapshot_pricing(Exploding(), {"m": {"input_tokens": 1}}) == {}


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------


class TestSnapshotReplay:
    def test_a_discount_is_not_re_expired_on_replay(self):
        # build_pricing_map drops an expired discount so a *live* config cannot
        # advertise a promotion that has ended. A snapshot is the opposite kind
        # of statement — what was in effect at the time — so re-expiring it would
        # reintroduce the retroactive rewriting this whole column exists to stop.
        snapshot = {
            "m": {
                "currency": "USD",
                "input_per_million": 1.0,
                "output_per_million": 2.0,
                "promo_input_per_million": 0.5,
                "promo_output_per_million": 1.0,
                "discount_until": "2020-01-01T00:00:00+00:00",
            }
        }
        restored = pricing_map_from_snapshot(snapshot)["m"]

        assert restored.promo() is not None
        assert restored.promo().input_per_million == 0.5

    def test_a_malformed_entry_falls_back_instead_of_raising(self):
        live = _live_map(_model("Lead", "lead-model", 5.0, 25.0))
        resolved = resolve_run_pricing(live, {"lead-model": {"currency": "USD", "input_per_million": "not-a-number"}}, currency="USD")

        assert resolved["lead-model"].input_per_million == 5.0


class TestRunCostPrefersTheSnapshot:
    def test_a_later_price_change_does_not_rewrite_an_old_run(self):
        usage = {"lead-model": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
        snapshot = snapshot_pricing([_model("Lead", "lead-model", 5.0, 25.0)], usage)
        # The operator (or the audit) re-prices the model afterwards.
        repriced = _live_map(_model("Lead", "lead-model", 50.0, 250.0))

        billed = run_cost(repriced, model_name="lead-model", total_input_tokens=None, total_output_tokens=None, token_usage_by_model=usage, pricing_snapshot=snapshot)

        assert billed == pytest.approx(30.0), "the run cost $30 when it ran; a later price edit is not a refund or a surcharge"

    def test_a_model_dropped_from_the_roster_keeps_its_cost(self):
        # The failure that motivated the column: an audit rolls the roster
        # forward, the old entry disappears, and the run's spend goes to zero.
        usage = {"grok-4.5": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
        snapshot = snapshot_pricing([_model("Grok 4.5", "grok-4.5", 2.0, 6.0)], usage)
        rolled_forward = _live_map(_model("Grok 4.6", "grok-4.6", 2.0, 6.0))

        assert run_cost(rolled_forward, model_name="grok-4.5", total_input_tokens=None, total_output_tokens=None, token_usage_by_model=usage, pricing_snapshot=snapshot) == pytest.approx(8.0)
        # ...and without the snapshot it is exactly the bug, which is what makes
        # this pair worth keeping: the assertion below is the old behaviour.
        assert run_cost(rolled_forward, model_name="grok-4.5", total_input_tokens=None, total_output_tokens=None, token_usage_by_model=usage, pricing_snapshot=None) is None

    def test_a_run_without_a_snapshot_still_prices_from_the_live_config(self):
        usage = {"lead-model": {"input_tokens": 1_000_000, "output_tokens": 0}}
        live = _live_map(_model("Lead", "lead-model", 5.0, 25.0))

        assert run_cost(live, model_name="lead-model", total_input_tokens=None, total_output_tokens=None, token_usage_by_model=usage, pricing_snapshot={}) == pytest.approx(5.0)

    def test_a_currency_switch_re_prices_rather_than_summing_two_currencies(self):
        # Preferring the snapshot here would put old USD figures inside a total
        # labelled EUR. Re-pricing is visibly wrong; a mixed sum is invisibly so.
        usage = {"lead-model": {"input_tokens": 1_000_000, "output_tokens": 0}}
        snapshot = snapshot_pricing([_model("Lead", "lead-model", 5.0, 25.0)], usage)
        eur = build_pricing_map([SimpleNamespace(name="Lead", model="lead-model", display_name="Lead", pricing=None, discount=None, price={"currency": "EUR", "input": 9.0, "output": 9.0})])

        assert run_cost(eur, model_name="lead-model", total_input_tokens=None, total_output_tokens=None, token_usage_by_model=usage, pricing_snapshot=snapshot) == pytest.approx(9.0)

    def test_a_snapshot_cannot_switch_cost_reporting_back_on(self):
        # An empty live map is the operator's current answer ("cost is hidden"),
        # and there is no display currency to render a figure in.
        usage = {"lead-model": {"input_tokens": 1_000_000, "output_tokens": 0}}
        snapshot = snapshot_pricing([_model("Lead", "lead-model", 5.0, 25.0)], usage)

        assert run_cost({}, model_name="lead-model", total_input_tokens=None, total_output_tokens=None, token_usage_by_model=usage, pricing_snapshot=snapshot) is None


# ---------------------------------------------------------------------------
# End to end through the endpoint the chat header reads
# ---------------------------------------------------------------------------


def _make_app(run_store: MagicMock):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    return app


def _thread_with(by_run: list[dict], by_model: dict) -> MagicMock:
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
            "total_tokens": sum(entry.get("tokens") or 0 for entry in by_run),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_runs": len(by_run),
            "by_model": by_model,
            "by_run": by_run,
            "by_caller": {"lead_agent": 0, "subagent": 0, "middleware": 0},
        }
    )
    run_store.list_by_thread = AsyncMock(return_value=[])
    return run_store


def _usage(input_tokens: int, output_tokens: int) -> dict:
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_tokens": 0, "total_tokens": input_tokens + output_tokens}


class TestThreadTokenUsageEndpoint:
    def test_each_turn_is_billed_at_the_price_that_turn_recorded(self):
        # One conversation, one model, two turns — priced differently because the
        # entry was re-priced between them. A single thread-level rate cannot
        # express this, which is why the endpoint sums per run.
        old_price = {"currency": "USD", "input_per_million": 5.0, "output_per_million": 25.0}
        by_run = [
            {"run_id": "r1", "created_at": "2026-01-01T00:00:00Z", "tokens": 2_000_000, "by_model": {"lead-model": _usage(1_000_000, 1_000_000)}, "pricing_snapshot": {"lead-model": old_price}},
            {"run_id": "r2", "created_at": "2026-02-01T00:00:00Z", "tokens": 2_000_000, "by_model": {"lead-model": _usage(1_000_000, 1_000_000)}, "pricing_snapshot": {}},
        ]
        by_model = {"lead-model": {"tokens": 4_000_000, "runs": 2, "input_tokens": 2_000_000, "output_tokens": 2_000_000, "cache_read_tokens": 0}}
        app = _make_app(_thread_with(by_run, by_model))

        with (
            patch.object(thread_runs, "_thread_pricing_map", side_effect=lambda: _live_map(_model("Lead", "lead-model", 10.0, 50.0))),
            patch.object(thread_runs, "build_context_usage", AsyncMock(return_value=None)),
            patch.object(thread_runs, "_superseded_run_ids", AsyncMock(return_value=set())),
            TestClient(app) as client,
        ):
            data = client.get("/api/threads/t/token-usage").json()

        # r1 at the recorded $5/25 = 30; r2 has no snapshot so it takes today's
        # $10/50 = 60.
        assert [step["cost"] for step in data["steps"]] == [pytest.approx(30.0), pytest.approx(60.0)]
        assert data["total_cost"] == pytest.approx(90.0)
        assert data["by_model"]["lead-model"]["cost"] == pytest.approx(90.0), "the per-model breakdown must agree with the steps it is made of"

    def test_a_retired_model_is_not_reported_as_unpriced(self):
        retired_price = {"grok-4.5": {"currency": "USD", "input_per_million": 2.0, "output_per_million": 6.0}}
        by_run = [{"run_id": "r1", "created_at": "2026-01-01T00:00:00Z", "tokens": 1_000_000, "by_model": {"grok-4.5": _usage(1_000_000, 0)}, "pricing_snapshot": retired_price}]
        by_model = {"grok-4.5": {"tokens": 1_000_000, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 0}}
        app = _make_app(_thread_with(by_run, by_model))

        with (
            patch.object(thread_runs, "_thread_pricing_map", side_effect=lambda: _live_map(_model("Grok 4.6", "grok-4.6", 2.0, 6.0))),
            patch.object(thread_runs, "build_context_usage", AsyncMock(return_value=None)),
            patch.object(thread_runs, "_superseded_run_ids", AsyncMock(return_value=set())),
            TestClient(app) as client,
        ):
            data = client.get("/api/threads/t/token-usage").json()

        assert data["total_cost"] == pytest.approx(2.0)
        assert data["unpriced_models"] == [], "a model with a recorded price is priced, not a gap for the operator to fix"

    def test_the_headers_stated_relation_still_holds_across_an_edit(self):
        # sum(steps) + superseded_cost == total_cost. An edited turn is hidden
        # from the chart and stays inside the total, and that must survive the
        # move to per-run pricing — the money was spent either way.
        price = {"currency": "USD", "input_per_million": 5.0, "output_per_million": 25.0}
        by_run = [
            {"run_id": "replaced", "created_at": "2026-01-01T00:00:00Z", "tokens": 2_000_000, "by_model": {"lead-model": _usage(1_000_000, 1_000_000)}, "pricing_snapshot": {"lead-model": price}},
            {"run_id": "kept", "created_at": "2026-01-02T00:00:00Z", "tokens": 1_000_000, "by_model": {"lead-model": _usage(1_000_000, 0)}, "pricing_snapshot": {"lead-model": price}},
        ]
        by_model = {"lead-model": {"tokens": 3_000_000, "runs": 2, "input_tokens": 2_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0}}
        app = _make_app(_thread_with(by_run, by_model))

        with (
            patch.object(thread_runs, "_thread_pricing_map", side_effect=lambda: _live_map(_model("Lead", "lead-model", 5.0, 25.0))),
            patch.object(thread_runs, "build_context_usage", AsyncMock(return_value=None)),
            patch.object(thread_runs, "_superseded_run_ids", AsyncMock(return_value={"replaced"})),
            TestClient(app) as client,
        ):
            data = client.get("/api/threads/t/token-usage").json()

        assert [step["run_id"] for step in data["steps"]] == ["kept"], "an edited turn is not a step of the conversation on screen"
        assert data["superseded_cost"] == pytest.approx(30.0)
        assert data["superseded_runs"] == 1
        assert sum(step["cost"] for step in data["steps"]) + data["superseded_cost"] == pytest.approx(data["total_cost"])


# ---------------------------------------------------------------------------
# The plumbing: a snapshot has to survive the write to disk and back
# ---------------------------------------------------------------------------


class TestSnapshotPersistence:
    """The column, the completion write, and the aggregation read, end to end.

    The unit tests above prove the pricing rules; this proves the value actually
    reaches them. A snapshot that is computed correctly and then dropped by the
    store looks exactly like no snapshot at all — the read path falls back to the
    live config and every assertion above still passes.
    """

    @pytest.mark.anyio
    async def test_it_round_trips_through_the_sql_store(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.persistence.run.sql import RunRepository

        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}", sqlite_dir=str(tmp_path))
        try:
            repo = RunRepository(get_session_factory())
            usage = {"lead-model": {"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000}}
            snapshot = snapshot_pricing([_model("Lead", "lead-model", 5.0, 25.0)], usage)

            await repo.put("r1", thread_id="t1", status="running")
            await repo.update_run_completion("r1", status="success", total_input_tokens=1_000_000, total_tokens=1_000_000, token_usage_by_model=usage, pricing_snapshot=snapshot)

            agg = await repo.aggregate_tokens_by_thread("t1")
            assert agg["by_run"][0]["pricing_snapshot"] == snapshot
        finally:
            await close_engine()

    @pytest.mark.anyio
    async def test_a_completion_retry_without_one_does_not_erase_it(self, tmp_path):
        # ``update_run_completion`` is retried on the recovery paths, and a retry
        # that could not rebuild the snapshot must leave the stored one alone
        # rather than blanking the run's price.
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.persistence.run.sql import RunRepository

        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}", sqlite_dir=str(tmp_path))
        try:
            repo = RunRepository(get_session_factory())
            snapshot = {"lead-model": {"currency": "USD", "input_per_million": 5.0, "output_per_million": 25.0}}
            await repo.put("r1", thread_id="t1", status="running")
            await repo.update_run_completion("r1", status="success", total_tokens=1, pricing_snapshot=snapshot)
            await repo.update_run_completion("r1", status="success", total_tokens=1)

            agg = await repo.aggregate_tokens_by_thread("t1")
            assert agg["by_run"][0]["pricing_snapshot"] == snapshot
        finally:
            await close_engine()

    @pytest.mark.anyio
    async def test_the_memory_store_reports_it_the_same_way(self, tmp_path):
        # The two stores share ``new_per_run_usage_entry`` precisely so their
        # aggregations cannot drift; assert the snapshot rides along in both.
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        store = MemoryRunStore()
        snapshot = {"lead-model": {"currency": "USD", "input_per_million": 5.0, "output_per_million": 25.0}}
        await store.put("r1", thread_id="t1", status="running")
        await store.update_run_completion("r1", status="success", total_tokens=1, token_usage_by_model={"lead-model": {"input_tokens": 1, "total_tokens": 1}}, pricing_snapshot=snapshot)

        agg = await store.aggregate_tokens_by_thread("t1")
        assert agg["by_run"][0]["pricing_snapshot"] == snapshot

    def test_the_worker_attaches_it_to_completion_data(self):
        # The one wiring assert: the worker must snapshot from the config the run
        # executed under (``ctx.app_config``), not from whatever the process
        # reloads later.
        from deerflow.runtime.runs.worker import _with_pricing_snapshot

        app_config = SimpleNamespace(models=[_model("Lead", "lead-model", 5.0, 25.0)])
        completion = _with_pricing_snapshot({"token_usage_by_model": {"lead-model": {"input_tokens": 10}}}, app_config)

        assert completion["pricing_snapshot"]["lead-model"]["input_per_million"] == 5.0

    def test_the_worker_degrades_rather_than_failing_a_finished_run(self):
        from deerflow.runtime.runs.worker import _with_pricing_snapshot

        assert _with_pricing_snapshot({"token_usage_by_model": {"m": {"input_tokens": 1}}}, None)["pricing_snapshot"] == {}
