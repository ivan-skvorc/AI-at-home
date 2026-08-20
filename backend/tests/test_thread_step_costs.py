"""Per-step cost: what each turn of a conversation cost, in order.

The header's cost overview reports one running total. That answers "what has
this conversation cost" but not "which turn got expensive", which is the
question a mixed-model thread actually raises — and the one the chart in the
cost dropdown exists to answer.

A *step* is one completed run: one user message and the answer to it. The
properties that matter:

* Steps are chronological and 1-based, so "step 3" is the third thing the user
  asked, not the third row a store happened to return.
* A step is priced exactly like the thread total is — each model in the run at
  its own rate — so the sum of the steps equals the thread total. If those two
  numbers could disagree, the chart would quietly contradict the headline
  figure sitting right above it.
* The promo basis follows the same convention as ``promo_total_cost``: null
  when nothing in the step is discounted, so the UI never prints the same
  number twice in two colours.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.pricing import build_pricing_map
from app.gateway.routers import thread_runs
from deerflow.runtime import aux_usage
from deerflow.runtime.runs.store.memory import MemoryRunStore


def _priced_map():
    """Opus lead + Haiku subagent + a discounted routed model."""
    return build_pricing_map(
        [
            SimpleNamespace(name="Opus", model="claude-opus-5", pricing={"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            SimpleNamespace(name="Haiku", model="claude-haiku-4-5", pricing={"currency": "USD", "input_per_million": 1, "output_per_million": 5}),
            SimpleNamespace(
                name="GLM",
                model="z-ai/glm-5.2",
                pricing={
                    "currency": "USD",
                    "input_per_million": 1.15,
                    "output_per_million": 3.6,
                    "promo_input_per_million": 0.28,
                    "promo_output_per_million": 0.87,
                },
            ),
        ],
    )


def _make_app(run_store):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    return app


async def _turn(store: MemoryRunStore, thread: str, run_id: str, usage: dict[str, dict], *, created_at: str) -> None:
    total = sum(u.get("total_tokens", 0) for u in usage.values())
    await store.put(run_id, thread_id=thread, status="pending", model_name=next(iter(usage)), created_at=created_at)
    await store.update_run_completion(
        run_id,
        status="success",
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


@pytest.mark.anyio
async def test_store_reports_one_bucket_per_run_oldest_first():
    store = MemoryRunStore()
    thread = "t-steps"
    await _turn(store, thread, "r1", {"claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 100_000, "total_tokens": 1_100_000}}, created_at="2026-08-01T10:00:00Z")
    await _turn(store, thread, "r2", {"claude-opus-5": {"input_tokens": 2_000_000, "output_tokens": 200_000, "total_tokens": 2_200_000}}, created_at="2026-08-01T10:05:00Z")

    agg = await store.aggregate_tokens_by_thread(thread)
    assert [b["run_id"] for b in agg["by_run"]] == ["r1", "r2"]
    assert [b["tokens"] for b in agg["by_run"]] == [1_100_000, 2_200_000]


@pytest.mark.anyio
async def test_runs_recorded_out_of_order_are_still_chronological():
    # A resumed or replayed run can land in the thread index out of order; the
    # chart's x axis must still read as the conversation happened.
    store = MemoryRunStore()
    thread = "t-order"
    await _turn(store, thread, "later", {"claude-opus-5": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11}}, created_at="2026-08-01T12:00:00Z")
    await _turn(store, thread, "earlier", {"claude-opus-5": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11}}, created_at="2026-08-01T09:00:00Z")

    agg = await store.aggregate_tokens_by_thread(thread)
    assert [b["run_id"] for b in agg["by_run"]] == ["earlier", "later"]


@pytest.mark.anyio
async def test_per_run_buckets_keep_the_model_split():
    # An Ultra-mode turn: expensive lead + cheap subagent. Collapsing the step
    # to a single token count would bill the subagent at the lead's rate.
    store = MemoryRunStore()
    thread = "t-ultra"
    await _turn(
        store,
        thread,
        "r1",
        {
            "claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 100_000, "total_tokens": 1_100_000},
            "claude-haiku-4-5": {"input_tokens": 4_000_000, "output_tokens": 500_000, "total_tokens": 4_500_000},
        },
        created_at="2026-08-01T10:00:00Z",
    )
    agg = await store.aggregate_tokens_by_thread(thread)
    assert set(agg["by_run"][0]["by_model"]) == {"claude-opus-5", "claude-haiku-4-5"}


def _endpoint_json(monkeypatch: pytest.MonkeyPatch, agg: dict, pricing=None) -> dict:
    aux_usage.reset_aux_usage()
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=agg)
    run_store.list_by_thread = AsyncMock(return_value=[])
    monkeypatch.setattr(thread_runs, "build_context_usage", AsyncMock(return_value=None))
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", lambda: pricing if pricing is not None else _priced_map())
    with TestClient(_make_app(run_store)) as client:
        response = client.get("/api/threads/t/token-usage")
    assert response.status_code == 200
    return response.json()


def _agg(by_run: list[dict], by_model: dict | None = None) -> dict:
    return {
        "total_tokens": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_runs": len(by_run),
        "by_model": by_model or {},
        "by_run": by_run,
        "by_caller": {"lead_agent": 0, "subagent": 0, "middleware": 0},
    }


class TestEndpointSteps:
    def test_each_step_is_priced_at_its_own_models_rates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": "2026-08-01T10:00:00Z",
                        "tokens": 1_100_000,
                        "by_model": {"claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0, "total_tokens": 1_100_000}},
                    },
                    {
                        "run_id": "r2",
                        "created_at": "2026-08-01T10:05:00Z",
                        "tokens": 4_500_000,
                        "by_model": {"claude-haiku-4-5": {"input_tokens": 4_000_000, "output_tokens": 500_000, "cache_read_tokens": 0, "total_tokens": 4_500_000}},
                    },
                ]
            ),
        )
        steps = payload["steps"]
        assert [s["index"] for s in steps] == [1, 2]
        # Opus: 1M @ $5 + 0.1M @ $25 = 5 + 2.5 = 7.5
        assert steps[0]["cost"] == pytest.approx(7.5)
        # Haiku: 4M @ $1 + 0.5M @ $5 = 4 + 2.5 = 6.5
        assert steps[1]["cost"] == pytest.approx(6.5)

    def test_a_step_sums_every_model_in_that_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": None,
                        "tokens": 5_600_000,
                        "by_model": {
                            "claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0, "total_tokens": 1_100_000},
                            "claude-haiku-4-5": {"input_tokens": 4_000_000, "output_tokens": 500_000, "cache_read_tokens": 0, "total_tokens": 4_500_000},
                        },
                    }
                ]
            ),
        )
        # 7.5 (Opus lead) + 6.5 (Haiku subagent), each at its own rate.
        assert payload["steps"][0]["cost"] == pytest.approx(14.0)

    def test_steps_sum_to_the_thread_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The chart must never contradict the headline figure above it."""
        by_run = [
            {
                "run_id": "r1",
                "created_at": None,
                "tokens": 1_100_000,
                "by_model": {"claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0, "total_tokens": 1_100_000}},
            },
            {
                "run_id": "r2",
                "created_at": None,
                "tokens": 4_500_000,
                "by_model": {"claude-haiku-4-5": {"input_tokens": 4_000_000, "output_tokens": 500_000, "cache_read_tokens": 0, "total_tokens": 4_500_000}},
            },
        ]
        by_model = {
            "claude-opus-5": {"tokens": 1_100_000, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0},
            "claude-haiku-4-5": {"tokens": 4_500_000, "runs": 1, "input_tokens": 4_000_000, "output_tokens": 500_000, "cache_read_tokens": 0},
        }
        payload = _endpoint_json(monkeypatch, _agg(by_run, by_model))
        assert sum(s["cost"] for s in payload["steps"]) == pytest.approx(payload["total_cost"])

    def test_cache_reads_are_billed_at_the_cache_rate_within_a_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pricing = build_pricing_map(
            [SimpleNamespace(name="Opus", model="claude-opus-5", pricing={"currency": "USD", "input_per_million": 5, "output_per_million": 25, "input_cache_hit_per_million": 0.5})],
        )
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": None,
                        "tokens": 2_000_000,
                        # 1M total input of which 1M are cache reads → all at 0.5.
                        "by_model": {"claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 1_000_000, "total_tokens": 2_000_000}},
                    }
                ]
            ),
            pricing=pricing,
        )
        assert payload["steps"][0]["cost"] == pytest.approx(0.5)

    def test_an_unpriced_step_reports_null_not_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A local Ollama turn contributed no cost. Reporting 0 would draw a real
        # point at zero; null lets the chart show a gap instead.
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": None,
                        "tokens": 500,
                        "by_model": {"qwen3:8b": {"input_tokens": 400, "output_tokens": 100, "cache_read_tokens": 0, "total_tokens": 500}},
                    }
                ]
            ),
        )
        assert payload["steps"][0]["cost"] is None

    def test_a_partly_priced_step_reports_only_the_priced_part(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": None,
                        "tokens": 1_100_500,
                        "by_model": {
                            "claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0, "total_tokens": 1_100_000},
                            "qwen3:8b": {"input_tokens": 400, "output_tokens": 100, "cache_read_tokens": 0, "total_tokens": 500},
                        },
                    }
                ]
            ),
        )
        assert payload["steps"][0]["cost"] == pytest.approx(7.5)


class TestStepPromoBasis:
    def test_a_discounted_step_carries_both_bases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": None,
                        "tokens": 2_000_000,
                        "by_model": {"z-ai/glm-5.2": {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0, "total_tokens": 2_000_000}},
                    }
                ]
            ),
        )
        step = payload["steps"][0]
        assert step["cost"] == pytest.approx(1.15 + 3.6)
        assert step["promo_cost"] == pytest.approx(0.28 + 0.87)

    def test_an_undiscounted_step_reports_no_promo_basis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Same rule as promo_total_cost: printing the same number twice in two
        # colours claims a discount that does not exist.
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": None,
                        "tokens": 1_100_000,
                        "by_model": {"claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0, "total_tokens": 1_100_000}},
                    }
                ]
            ),
        )
        assert payload["steps"][0]["promo_cost"] is None

    def test_a_mixed_step_bills_the_undiscounted_model_at_its_ordinary_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Both bases must cover the whole step, or the two figures are not
        # comparable — the same rule the thread total follows.
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": None,
                        "tokens": 3_100_000,
                        "by_model": {
                            "claude-opus-5": {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0, "total_tokens": 1_100_000},
                            "z-ai/glm-5.2": {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0, "total_tokens": 2_000_000},
                        },
                    }
                ]
            ),
        )
        step = payload["steps"][0]
        assert step["cost"] == pytest.approx(7.5 + 4.75)
        assert step["promo_cost"] == pytest.approx(7.5 + 1.15)
        # The saving is the discounted model's alone.
        assert step["cost"] - step["promo_cost"] == pytest.approx(4.75 - 1.15)


class TestDegradation:
    def test_a_store_without_by_run_yields_an_empty_chart(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Old aggregate shape (no by_run key): no steps, no error.
        agg = _agg([])
        del agg["by_run"]
        assert _endpoint_json(monkeypatch, agg)["steps"] == []

    def test_no_pricing_configured_yields_steps_with_null_costs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Token counts still work with no pricing, so the step list is still
        # useful (and the UI hides the cost chart rather than showing zeros).
        payload = _endpoint_json(
            monkeypatch,
            _agg(
                [
                    {
                        "run_id": "r1",
                        "created_at": None,
                        "tokens": 500,
                        "by_model": {"claude-opus-5": {"input_tokens": 400, "output_tokens": 100, "cache_read_tokens": 0, "total_tokens": 500}},
                    }
                ]
            ),
            pricing={},
        )
        assert payload["steps"][0]["cost"] is None
        assert payload["steps"][0]["tokens"] == 500


async def _make_sql_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository

    url = f"sqlite+aiosqlite:///{tmp_path / 'steps.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return RunRepository(get_session_factory())


async def _close_sql_engine() -> None:
    from deerflow.persistence.engine import close_engine

    await close_engine()


@pytest.mark.anyio
async def test_memory_and_sql_stores_agree_on_by_run(tmp_path):
    """The two stores must not disagree about the conversation's steps.

    The header renders whichever backend ``database.backend`` selected, so a
    divergence here would show one user a different chart from another for the
    same conversation.
    """
    sql_store = await _make_sql_repo(tmp_path)
    memory_store = MemoryRunStore()
    thread = "t-parity"
    usage = [
        ("r1", {"claude-opus-5": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}}, "2026-08-01T10:00:00+00:00"),
        ("r2", {"claude-haiku-4-5": {"input_tokens": 200, "output_tokens": 20, "total_tokens": 220}}, "2026-08-01T10:05:00+00:00"),
    ]
    try:
        for store in (memory_store, sql_store):
            for run_id, models, created_at in usage:
                await _turn(store, thread, run_id, models, created_at=created_at)

        mem = await memory_store.aggregate_tokens_by_thread(thread)
        sql = await sql_store.aggregate_tokens_by_thread(thread)
        assert [b["run_id"] for b in mem["by_run"]] == [b["run_id"] for b in sql["by_run"]]
        assert [b["tokens"] for b in mem["by_run"]] == [b["tokens"] for b in sql["by_run"]]
        assert [b["by_model"] for b in mem["by_run"]] == [b["by_model"] for b in sql["by_run"]]
        assert [b["created_at"] for b in mem["by_run"]] == [b["created_at"] for b in sql["by_run"]]
    finally:
        await _close_sql_engine()
