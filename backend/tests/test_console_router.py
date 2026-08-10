"""Tests for the console router (cross-thread observability endpoints).

Covers:
1. /api/console/stats — headline counters
2. /api/console/runs — cross-thread listing, thread-title join, pagination, status filter
3. /api/console/usage — daily zero-filled buckets + per-model breakdown (incl. legacy fallback)
4. user scoping — rows filtered when the request resolves to a user
5. 503 when no SQL session factory is available (memory backend)

Uses a real temp-file SQLite database (NullPool, so seeding in one event loop
and serving TestClient requests in another never share a connection).
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.gateway.routers import console
from deerflow.persistence.base import Base
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

# Pinned to noon UTC so hour-level seed offsets (NOW - 1h, NOW - 2h) never cross
# the midnight boundary into the previous calendar day, which would otherwise
# make "today" rows bucket into yesterday whenever the suite runs within a few
# hours of UTC midnight. The client fixture freezes the console router's
# `datetime.now` to this same instant, keeping the router's view of "today"
# (and active-run durations) aligned with these seed timestamps.
NOW = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


class _FrozenDatetime(datetime):
    """``datetime`` subclass whose ``now()`` returns a fixed instant.

    Everything else (``combine``, ``replace``, arithmetic, ``isinstance``) is
    inherited unchanged from ``datetime``; only ``now`` is redirected so the
    router derives its day-bucket window and live durations from ``NOW``.
    """

    _frozen: datetime | None = None

    @classmethod
    def now(cls, tz=None):
        if cls._frozen is None:  # pragma: no cover - defensive fallback
            return super().now(tz)
        return cls._frozen if tz is None else cls._frozen.astimezone(tz)


def _seed_rows() -> tuple[list[ThreadMetaRow], list[RunRow]]:
    threads = [
        ThreadMetaRow(thread_id="t1", user_id="user-a", display_name="调研鹿角再生"),
        ThreadMetaRow(thread_id="t2", user_id="user-a", display_name="Card assistant chat"),
    ]
    runs = [
        RunRow(
            run_id="r1",
            thread_id="t1",
            user_id="user-a",
            status="success",
            model_name="minimax-m2",
            total_tokens=1200,
            total_input_tokens=800,
            total_output_tokens=400,
            token_usage_by_model={"minimax-m2": {"input_tokens": 800, "output_tokens": 400, "total_tokens": 1200, "cache_read_tokens": 500}},
            message_count=4,
            created_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1) + timedelta(seconds=30),
        ),
        RunRow(
            run_id="r2",
            thread_id="t1",
            user_id="user-a",
            status="running",
            model_name="minimax-m2",
            total_tokens=300,
            total_input_tokens=200,
            total_output_tokens=100,
            token_usage_by_model={"minimax-m2": {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300}},
            message_count=1,
            created_at=NOW - timedelta(seconds=60),
            updated_at=NOW - timedelta(seconds=1),
        ),
        RunRow(
            run_id="r3",
            thread_id="t2",
            user_id="user-a",
            status="error",
            model_name="gpt-x",
            error="Boom: provider exploded",
            total_tokens=50,
            total_input_tokens=50,
            total_output_tokens=0,
            token_usage_by_model={},  # legacy row → model_name fallback path
            message_count=2,
            created_at=NOW - timedelta(days=1),
            updated_at=NOW - timedelta(days=1) + timedelta(seconds=5),
        ),
        RunRow(
            run_id="r4",
            thread_id="t2",
            user_id="user-a",
            status="success",
            model_name="minimax-m2",
            total_tokens=999,
            token_usage_by_model={"minimax-m2": {"input_tokens": 600, "output_tokens": 399, "total_tokens": 999}},
            created_at=NOW - timedelta(days=40),  # outside the default usage window
            updated_at=NOW - timedelta(days=40) + timedelta(seconds=10),
        ),
        RunRow(
            run_id="r5",
            thread_id="t3",  # no threads_meta row → exercises the outer join
            user_id="user-b",
            status="success",
            model_name="qwen",
            total_tokens=70,
            total_input_tokens=40,
            total_output_tokens=30,
            token_usage_by_model={"qwen": {"input_tokens": 40, "output_tokens": 30, "total_tokens": 70}},
            created_at=NOW - timedelta(hours=2),
            updated_at=NOW - timedelta(hours=2) + timedelta(seconds=8),
        ),
        RunRow(
            run_id="checkpoint-write-1",
            thread_id="t1",
            user_id="user-a",
            operation_kind="checkpoint_write",
            status="error",
            created_at=NOW - timedelta(minutes=30),
            updated_at=NOW - timedelta(minutes=29),
        ),
    ]
    return threads, runs


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'console.db'}", poolclass=NullPool)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        threads, runs = _seed_rows()
        async with sf() as session:
            session.add_all(threads)
            session.add_all(runs)
            await session.commit()

    asyncio.run(_setup())
    yield sf
    asyncio.run(engine.dispose())


@pytest.fixture()
def client(session_factory, monkeypatch):
    monkeypatch.setattr(console, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(console, "get_current_user", AsyncMock(return_value=None))
    monkeypatch.setattr(console, "list_custom_agents", lambda: [object(), object()])
    # No pricing configured by default; TestPricing patches its own config.
    monkeypatch.setattr(console, "get_app_config", lambda: SimpleNamespace(models=[]))
    # Pin the router's wall-clock to NOW so day-bucketing and durations are
    # independent of when the suite runs (see NOW's docstring).
    _FrozenDatetime._frozen = NOW
    monkeypatch.setattr(console, "datetime", _FrozenDatetime)
    app = make_authed_test_app()
    app.include_router(console.router)
    return TestClient(app)


class TestConsoleStats:
    def test_headline_counters(self, client):
        resp = client.get("/api/console/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_runs"] == 5
        assert data["active_runs"] == 1  # r2 running
        assert data["failed_runs"] == 1  # r3 error
        assert data["total_threads"] == 2
        assert data["total_agents"] == 2
        assert data["total_tokens"] == 1200 + 300 + 50 + 999 + 70


class TestConsoleRuns:
    def test_listing_orders_paginates_and_joins_titles(self, client):
        resp = client.get("/api/console/runs", params={"limit": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_more"] is True
        ids = [r["run_id"] for r in data["runs"]]
        assert ids == ["r2", "r1", "r5"]  # newest first
        by_id = {r["run_id"]: r for r in data["runs"]}
        assert by_id["r2"]["thread_title"] == "调研鹿角再生"
        assert by_id["r5"]["thread_title"] is None  # t3 has no threads_meta row
        # Terminal run: duration from created→updated; active run: live elapsed > 0.
        assert by_id["r1"]["duration_seconds"] == pytest.approx(30.0, abs=1.0)
        assert by_id["r2"]["duration_seconds"] > 0

    def test_offset_pagination(self, client):
        resp = client.get("/api/console/runs", params={"limit": 3, "offset": 3})
        data = resp.json()
        assert [r["run_id"] for r in data["runs"]] == ["r3", "r4"]
        assert data["has_more"] is False

    def test_status_filter(self, client):
        resp = client.get("/api/console/runs", params={"status": "error"})
        data = resp.json()
        assert [r["run_id"] for r in data["runs"]] == ["r3"]
        assert data["runs"][0]["error"].startswith("Boom")


class TestConsoleUsage:
    def test_daily_buckets_and_model_breakdown(self, client):
        resp = client.get("/api/console/usage", params={"days": 14})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["days"]) == 14
        # r4 (40 days old) excluded from the window
        assert data["total_runs"] == 4
        assert data["total_tokens"] == 1200 + 300 + 50 + 70
        # Zero-filled series sums to the window total
        assert sum(d["total_tokens"] for d in data["days"]) == data["total_tokens"]
        yesterday = (NOW - timedelta(days=1)).date().isoformat()
        day_map = {d["date"]: d for d in data["days"]}
        assert day_map[yesterday]["total_tokens"] == 50
        assert data["by_model"]["minimax-m2"]["tokens"] == 1500
        assert data["by_model"]["qwen"]["tokens"] == 70
        # Legacy row (empty token_usage_by_model) falls back to model_name
        assert data["by_model"]["gpt-x"]["tokens"] == 50

    def test_window_excludes_old_rows_but_stats_include_them(self, client):
        usage = client.get("/api/console/usage", params={"days": 7}).json()
        assert all(r != 999 for d in usage["days"] for r in [d["total_tokens"]])
        stats = client.get("/api/console/stats").json()
        assert stats["total_tokens"] >= 999


def _priced_config(*, cache_hit_price: float | None = 0.8):
    pricing = {"currency": "CNY", "input_per_million": 8, "output_per_million": 32}
    if cache_hit_price is not None:
        pricing["input_cache_hit_per_million"] = cache_hit_price
    return SimpleNamespace(
        models=[
            SimpleNamespace(name="minimax-m2", model="MiniMax-M2", pricing=pricing),
            SimpleNamespace(name="gpt-x", model="gpt-x-1", pricing=None),  # explicitly unpriced
        ]
    )


# Expected per-run costs at 8 (miss) / 0.8 (hit) / 32 (output) per million:
# r1: 500 of 800 input tokens were cache hits → 300*8 + 500*0.8 + 400*32 (µ¥)
_R1_COST_CACHED = 300 * 8e-6 + 500 * 0.8e-6 + 400 * 32e-6  # 0.0156
_R1_COST_UNCACHED = 800 * 8e-6 + 400 * 32e-6  # 0.0192 (no hit price configured)
_R2_COST = 200 * 8e-6 + 100 * 32e-6  # 0.0048 (no cache hits recorded)
_R4_COST = 600 * 8e-6 + 399 * 32e-6  # 0.017568


class TestPricing:
    def test_mixed_currencies_disable_cost_reporting(self, client, monkeypatch, caplog):
        monkeypatch.setattr(
            console,
            "get_app_config",
            lambda: SimpleNamespace(
                models=[
                    SimpleNamespace(
                        name="minimax-m2",
                        model="MiniMax-M2",
                        pricing={"currency": "CNY", "input_per_million": 8, "output_per_million": 32},
                    ),
                    SimpleNamespace(
                        name="gpt-x",
                        model="gpt-x-1",
                        pricing={"currency": "USD", "input_per_million": 1, "output_per_million": 4},
                    ),
                ]
            ),
        )

        with caplog.at_level(logging.WARNING, logger=console.logger.name):
            stats = client.get("/api/console/stats").json()
        assert stats["currency"] is None
        assert stats["total_cost"] is None
        # The warning names both offending models so operators can locate the misconfiguration.
        assert any("minimax-m2" in rec.getMessage() and "gpt-x" in rec.getMessage() for rec in caplog.records)

        usage = client.get("/api/console/usage").json()
        assert usage["currency"] is None
        assert usage["total_cost"] is None
        assert all(day["cost"] == 0 for day in usage["days"])
        assert all(model["cost"] is None for model in usage["by_model"].values())

        runs = client.get("/api/console/runs", params={"limit": 50}).json()
        assert all(run["cost"] is None for run in runs["runs"])

    def test_shared_currency_across_models_prices_normally(self, client, monkeypatch):
        """Multiple priced models on one currency (incl. case variants) must not trip the guard."""
        monkeypatch.setattr(
            console,
            "get_app_config",
            lambda: SimpleNamespace(
                models=[
                    SimpleNamespace(
                        name="minimax-m2",
                        model="MiniMax-M2",
                        pricing={"currency": "CNY", "input_per_million": 8, "output_per_million": 32},
                    ),
                    SimpleNamespace(
                        name="qwen",
                        model="qwen",
                        pricing={"currency": "cny", "input_per_million": 8, "output_per_million": 32},
                    ),
                ]
            ),
        )
        # qwen's only run (r5) is now priced alongside the minimax runs.
        qwen_cost = 40 * 8e-6 + 30 * 32e-6

        stats = client.get("/api/console/stats").json()
        assert stats["currency"] == "CNY"
        # No cache-hit price configured → r1 billed at the miss price.
        assert stats["total_cost"] == pytest.approx(_R1_COST_UNCACHED + _R2_COST + _R4_COST + qwen_cost)

        usage = client.get("/api/console/usage").json()
        assert usage["currency"] == "CNY"
        assert usage["by_model"]["qwen"]["cost"] == pytest.approx(qwen_cost)

    def test_costs_use_cache_hit_price(self, client, monkeypatch):
        monkeypatch.setattr(console, "get_app_config", lambda: _priced_config())
        stats = client.get("/api/console/stats").json()
        assert stats["currency"] == "CNY"
        # r3 (gpt-x) and r5 (qwen) are unpriced and excluded.
        assert stats["total_cost"] == pytest.approx(_R1_COST_CACHED + _R2_COST + _R4_COST)

        usage = client.get("/api/console/usage").json()
        assert usage["currency"] == "CNY"
        assert usage["total_cost"] == pytest.approx(_R1_COST_CACHED + _R2_COST)  # r4 outside window
        assert usage["by_model"]["minimax-m2"]["cost"] == pytest.approx(_R1_COST_CACHED + _R2_COST)
        assert usage["by_model"]["minimax-m2"]["input_tokens"] == 1000
        assert usage["by_model"]["minimax-m2"]["cache_read_tokens"] == 500
        assert usage["by_model"]["gpt-x"]["cost"] is None
        assert sum(d["cost"] for d in usage["days"]) == pytest.approx(_R1_COST_CACHED + _R2_COST)

        runs = client.get("/api/console/runs", params={"limit": 50}).json()
        by_id = {r["run_id"]: r for r in runs["runs"]}
        assert by_id["r1"]["cost"] == pytest.approx(_R1_COST_CACHED)
        assert by_id["r3"]["cost"] is None  # unpriced model

    def test_cache_hits_billed_at_miss_price_without_hit_price(self, client, monkeypatch):
        """No input_cache_hit_per_million configured → conservative upper bound."""
        monkeypatch.setattr(console, "get_app_config", lambda: _priced_config(cache_hit_price=None))
        runs = client.get("/api/console/runs", params={"limit": 50}).json()
        by_id = {r["run_id"]: r for r in runs["runs"]}
        assert by_id["r1"]["cost"] == pytest.approx(_R1_COST_UNCACHED)

    def test_costs_null_without_pricing(self, client):
        stats = client.get("/api/console/stats").json()
        assert stats["total_cost"] is None
        assert stats["currency"] is None
        usage = client.get("/api/console/usage").json()
        assert usage["total_cost"] is None
        runs = client.get("/api/console/runs").json()
        assert all(r["cost"] is None for r in runs["runs"])


class TestUserScoping:
    def test_rows_filtered_by_resolved_user(self, client, monkeypatch):
        monkeypatch.setattr(console, "get_current_user", AsyncMock(return_value="user-a"))
        stats = client.get("/api/console/stats").json()
        assert stats["total_runs"] == 4  # r5 (user-b) excluded
        assert stats["total_tokens"] == 1200 + 300 + 50 + 999
        runs = client.get("/api/console/runs", params={"limit": 50}).json()
        assert all(r["run_id"] != "r5" for r in runs["runs"])
        usage = client.get("/api/console/usage").json()
        assert "qwen" not in usage["by_model"]


class TestNoSqlBackend:
    def test_503_when_memory_backend(self, session_factory, monkeypatch):
        monkeypatch.setattr(console, "get_session_factory", lambda: None)
        monkeypatch.setattr(console, "get_current_user", AsyncMock(return_value=None))
        app = make_authed_test_app()
        app.include_router(console.router)
        c = TestClient(app)
        for path in ("/api/console/stats", "/api/console/runs", "/api/console/usage"):
            resp = c.get(path)
            assert resp.status_code == 503
            assert "SQL database backend" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Spend attribution (roadmap item 3)
# ---------------------------------------------------------------------------


@pytest.fixture()
def aux_store(tmp_path, monkeypatch):
    """A per-test durable auxiliary store, seeded through the store directly."""
    from deerflow.runtime import aux_usage
    from deerflow.runtime.aux_usage_store import get_aux_usage_store

    monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(tmp_path / "aux.sqlite3"))
    aux_usage.reset_aux_usage()
    store = get_aux_usage_store()
    assert store is not None
    yield store
    aux_usage.reset_aux_usage()


def _seed_aux(store, thread_id, category, model, *, when, input_tokens=1_000_000, output_tokens=0):
    store.add(
        thread_id,
        category,
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cache_read_tokens=0,
        calls=1,
        recorded_at=when.timestamp(),
    )


def _spend_pricing():
    # $1/M in, $5/M out on minimax-m2; gpt-x priced too; qwen deliberately not.
    return {
        "minimax-m2": console.ModelPricing(1.0, 5.0, "USD"),
        "gpt-x": console.ModelPricing(2.0, 10.0, "USD"),
    }


class TestConsoleSpend:
    def test_groups_the_same_window_by_model_thread_and_feature(self, client, monkeypatch, aux_store):
        monkeypatch.setattr(console, "_build_pricing_map", _spend_pricing)
        _seed_aux(aux_store, "t1", "memory", "minimax-m2", when=NOW - timedelta(hours=3))

        data = client.get("/api/console/spend?days=30").json()

        assert data["currency"] == "USD"
        # Inside the 30-day window on minimax-m2: r1 (800 in / 400 out =
        # $0.0028), r2 (200 / 100 = $0.0007) and the 1M-token memory call ($1).
        # r4 is 40 days old and drops out. gpt-x carries r3's legacy 50 input
        # tokens ($0.0001).
        models = {row["model"]: row for row in data["by_model"]}
        assert models["minimax-m2"]["aux_calls"] == 1
        assert models["minimax-m2"]["cost"] == pytest.approx(1.0035)
        assert models["gpt-x"]["cost"] == pytest.approx(0.0001)
        threads = {row["thread_id"]: row for row in data["by_thread"]}
        assert threads["t1"]["title"] == "调研鹿角再生"
        categories = {row["category"]: row for row in data["by_category"]}
        assert set(categories) == {"conversation", "memory"}
        assert categories["memory"]["cost"] == pytest.approx(1.0)

    def test_the_groupings_agree_with_the_total(self, client, monkeypatch, aux_store):
        monkeypatch.setattr(console, "_build_pricing_map", _spend_pricing)
        _seed_aux(aux_store, "t2", "suggestions", "gpt-x", when=NOW - timedelta(days=1))

        data = client.get("/api/console/spend?days=30").json()

        by_model_total = sum(row["cost"] for row in data["by_model"] if row["cost"] is not None)
        by_thread_total = sum(row["cost"] for row in data["by_thread"] if row["cost"] is not None)
        by_category_total = sum(row["cost"] for row in data["by_category"] if row["cost"] is not None)
        assert data["total_cost"] == pytest.approx(by_model_total)
        assert data["total_cost"] == pytest.approx(by_thread_total)
        assert data["total_cost"] == pytest.approx(by_category_total)

    def test_unpriced_models_are_named_rather_than_quietly_dropped(self, client, monkeypatch, aux_store):
        monkeypatch.setattr(console, "_build_pricing_map", _spend_pricing)

        data = client.get("/api/console/spend?days=30").json()

        # r5 ran on `qwen`, which has no configured price.
        assert "qwen" in data["unpriced_models"]
        qwen = next(row for row in data["by_model"] if row["model"] == "qwen")
        assert qwen["cost"] is None
        # ...and it sorts last, so it never looks like the cheapest model.
        assert data["by_model"][-1]["model"] == "qwen"

    def test_the_window_excludes_older_runs(self, client, monkeypatch, aux_store):
        monkeypatch.setattr(console, "_build_pricing_map", _spend_pricing)
        # r4 is 40 days old; a 30-day window drops it, a 60-day one keeps it.
        short = client.get("/api/console/spend?days=30").json()
        long = client.get("/api/console/spend?days=60").json()
        assert long["total_runs"] == short["total_runs"] + 1

    def test_no_pricing_configured_reports_null_cost(self, client, aux_store):
        data = client.get("/api/console/spend?days=30").json()
        assert data["total_cost"] is None
        assert data["currency"] is None
        assert data["unpriced_models"] == []
        # Token counts still work, so the page is useful before pricing exists.
        assert data["total_tokens"] > 0

    def test_empty_window_is_an_empty_report_not_an_error(self, client, monkeypatch, aux_store):
        monkeypatch.setattr(console, "_build_pricing_map", _spend_pricing)
        monkeypatch.setattr(console, "get_current_user", AsyncMock(return_value="nobody"))
        data = client.get("/api/console/spend?days=30").json()
        assert data["total_runs"] == 0
        assert data["by_model"] == []
        assert data["by_thread"] == []
        assert data["by_category"] == []

    def test_requires_a_sql_backend(self, client, monkeypatch):
        monkeypatch.setattr(console, "get_session_factory", lambda: None)
        assert client.get("/api/console/spend").status_code == 503
