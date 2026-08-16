"""Tests for currency-denominated spend caps — the accounting half.

Roadmap item 2. Covers window aggregation over persisted runs plus the durable
auxiliary counters, the "unpriced models are free" rule that keeps a local-only
run from ever being blocked, and each way the feature self-disables.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.gateway import spend_budget as sb
from deerflow.config.spend_budget_config import SpendBudgetConfig
from deerflow.persistence.base import Base
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime import aux_usage
from deerflow.runtime.aux_usage_store import get_aux_usage_store

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

# $10/M in, $50/M out — round numbers so the arithmetic in each assertion is
# readable: 100k in + 20k out = $1 + $1 = $2.
PRICED = SimpleNamespace(
    name="premium",
    model="premium-1",
    display_name="Premium",
    pricing={"currency": "USD", "input_per_million": 10.0, "output_per_million": 50.0},
)
LOCAL = SimpleNamespace(name="local", model="qwen3:8b", display_name="Qwen3 8B (Ollama)", pricing=None)


def _run(run_id: str, *, created_at: datetime, model: str = "premium-1", input_tokens: int = 100_000, output_tokens: int = 20_000, user_id: str = "user-a", thread_id: str = "t1") -> RunRow:
    return RunRow(
        run_id=run_id,
        thread_id=thread_id,
        user_id=user_id,
        status="success",
        model_name=model,
        total_tokens=input_tokens + output_tokens,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        token_usage_by_model={model: {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}},
        created_at=created_at,
    )


@pytest.fixture()
def aux_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(tmp_path / "aux.sqlite3"))
    aux_usage.reset_aux_usage()
    yield
    aux_usage.reset_aux_usage()


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'spend.db'}", poolclass=NullPool)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    yield sf
    asyncio.run(engine.dispose())


def _seed(session_factory, rows) -> None:
    async def _insert() -> None:
        async with session_factory() as session:
            session.add_all(rows)
            await session.commit()

    asyncio.run(_insert())


def _resolve(monkeypatch, session_factory, *, config: SpendBudgetConfig, models=(PRICED,), user_id: str | None = "user-a", now: datetime = NOW):
    monkeypatch.setattr(sb, "get_session_factory", lambda: session_factory)
    app_config = SimpleNamespace(models=list(models), spend_budget=config)
    return asyncio.run(sb.resolve_spend_budget_status(app_config=app_config, user_id=user_id, now=now))


class TestWindowAggregation:
    def test_runs_inside_the_window_are_summed(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [_run("r1", created_at=NOW - timedelta(hours=2)), _run("r2", created_at=NOW - timedelta(hours=5))])
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10))
        assert status.active is True
        assert status.currency == "USD"
        assert status.limits[0].period == "daily"
        assert status.limits[0].spent == pytest.approx(4.0)
        assert status.limits[0].remaining == pytest.approx(6.0)

    def test_runs_outside_the_window_are_excluded(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [_run("recent", created_at=NOW - timedelta(hours=2)), _run("old", created_at=NOW - timedelta(days=3))])
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10))
        assert status.limits[0].spent == pytest.approx(2.0)

    def test_each_window_gets_its_own_total(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [_run("today", created_at=NOW - timedelta(hours=2)), _run("last_week", created_at=NOW - timedelta(days=3))])
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10, weekly_limit=50))
        by_period = {limit.period: limit.spent for limit in status.limits}
        assert by_period["daily"] == pytest.approx(2.0)
        assert by_period["weekly"] == pytest.approx(4.0)

    def test_calendar_mode_uses_the_local_day_boundary(self, monkeypatch, session_factory, aux_db):
        # 12:00Z. A run at 01:00Z today is inside the calendar day but a run at
        # 23:00Z yesterday is not — while a 24h rolling window would count both.
        _seed(session_factory, [_run("early_today", created_at=NOW.replace(hour=1)), _run("late_yesterday", created_at=NOW.replace(hour=23) - timedelta(days=1))])
        calendar = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10, window="calendar"))
        rolling = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10, window="rolling"))
        assert calendar.limits[0].spent == pytest.approx(2.0)
        assert rolling.limits[0].spent == pytest.approx(4.0)

    def test_another_users_runs_do_not_count(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [_run("mine", created_at=NOW - timedelta(hours=1)), _run("theirs", created_at=NOW - timedelta(hours=1), user_id="user-b")])
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10))
        assert status.limits[0].spent == pytest.approx(2.0)

    def test_reservations_are_not_runs(self, monkeypatch, session_factory, aux_db):
        row = _run("checkpoint", created_at=NOW - timedelta(hours=1))
        row.operation_kind = "checkpoint_write"
        _seed(session_factory, [_run("real", created_at=NOW - timedelta(hours=1)), row])
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10))
        assert status.limits[0].spent == pytest.approx(2.0)


def _seed_aux(thread_id: str, model: str, *, when: datetime, category: str = "memory", input_tokens: int = 100_000, output_tokens: int = 20_000) -> None:
    """Append an auxiliary-usage row at an explicit instant.

    Written through the store rather than ``record_aux_usage`` so the row can
    be dated relative to the tests' frozen ``NOW``; the recorder-to-store wiring
    is covered by ``test_aux_usage.py``.
    """
    store = get_aux_usage_store()
    assert store is not None
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


class TestLocalModelsAreFree:
    def test_an_unpriced_model_contributes_nothing(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [_run("local", created_at=NOW - timedelta(hours=1), model="qwen3:8b", input_tokens=5_000_000, output_tokens=5_000_000)])
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=1), models=(PRICED, LOCAL))
        assert status.limits[0].spent == 0.0
        # The hard requirement: a fully local run is never blocked by a cap.
        assert status.exceeded is None

    def test_an_unpriced_auxiliary_model_is_free_too(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [ThreadMetaRow(thread_id="t1", user_id="user-a")])
        _seed_aux("t1", "qwen3:8b", when=NOW - timedelta(hours=1), input_tokens=9_000_000, output_tokens=1_000_000)
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=1), models=(PRICED, LOCAL))
        assert status.limits[0].spent == 0.0


class TestAuxiliarySpendCounts:
    def test_memory_and_suggestions_spend_counts_against_the_cap(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [ThreadMetaRow(thread_id="t1", user_id="user-a")])
        # 100k in + 20k out on the priced model = $2, same as one run.
        _seed_aux("t1", "premium-1", when=NOW - timedelta(hours=1))
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10))
        assert status.limits[0].spent == pytest.approx(2.0)

    def test_aux_from_another_users_thread_is_excluded(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [ThreadMetaRow(thread_id="mine", user_id="user-a"), ThreadMetaRow(thread_id="theirs", user_id="user-b")])
        _seed_aux("mine", "premium-1", when=NOW - timedelta(hours=1))
        _seed_aux("theirs", "premium-1", when=NOW - timedelta(hours=1))
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10))
        assert status.limits[0].spent == pytest.approx(2.0)

    def test_aux_outside_the_window_is_excluded(self, monkeypatch, session_factory, aux_db):
        _seed(session_factory, [ThreadMetaRow(thread_id="t1", user_id="user-a")])
        _seed_aux("t1", "premium-1", when=NOW - timedelta(days=3))
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=10))
        assert status.limits[0].spent == 0.0


class TestSelfDisabling:
    def test_off_by_default(self, monkeypatch, session_factory):
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig())
        assert status.active is False
        assert status.disabled_reason == sb.DISABLED_NOT_CONFIGURED
        assert status.exceeded is None

    def test_no_pricing_disables_the_feature_with_a_reason(self, monkeypatch, session_factory):
        status = _resolve(monkeypatch, session_factory, config=SpendBudgetConfig(enabled=True, daily_limit=1), models=(LOCAL,))
        assert status.active is False
        assert status.disabled_reason == sb.DISABLED_NO_PRICING
        assert "nothing to measure" in sb.disabled_reason_text(status.disabled_reason)

    def test_memory_backend_disables_the_feature_with_a_reason(self, monkeypatch):
        monkeypatch.setattr(sb, "get_session_factory", lambda: None)
        app_config = SimpleNamespace(models=[PRICED], spend_budget=SpendBudgetConfig(enabled=True, daily_limit=1))
        status = asyncio.run(sb.resolve_spend_budget_status(app_config=app_config, user_id=None, now=NOW))
        assert status.active is False
        assert status.disabled_reason == sb.DISABLED_NO_DATABASE

    def test_an_inactive_status_never_reports_a_breach(self):
        status = sb.inactive_status(SpendBudgetConfig(), sb.DISABLED_NO_PRICING)
        assert status.exceeded is None
        assert status.warning is None
        assert status.tightest is None


class TestStatusHelpers:
    def _status(self, spent_daily: float, spent_weekly: float = 0.0) -> sb.SpendBudgetStatus:
        return sb.SpendBudgetStatus(
            active=True,
            currency="USD",
            limits=(sb.SpendLimitStatus("daily", 10.0, spent_daily), sb.SpendLimitStatus("weekly", 50.0, spent_weekly)),
            warn_threshold=0.8,
            hard_stop_threshold=1.0,
        )

    def test_warning_fires_at_the_threshold(self):
        assert self._status(7.9).warning is None
        assert self._status(8.0).warning.period == "daily"

    def test_exceeded_fires_at_the_hard_stop(self):
        assert self._status(9.99).exceeded is None
        assert self._status(10.0).exceeded.period == "daily"

    def test_tightest_is_the_least_headroom(self):
        assert self._status(1.0, 49.0).tightest.period == "weekly"
        assert self._status(9.0, 1.0).tightest.period == "daily"

    def test_with_additional_spend_applies_to_every_window(self):
        bumped = self._status(1.0, 2.0).with_additional_spend(3.0)
        assert [limit.spent for limit in bumped.limits] == [4.0, 5.0]

    def test_with_additional_spend_is_a_no_op_when_inactive(self):
        inactive = sb.inactive_status(SpendBudgetConfig(), sb.DISABLED_NOT_CONFIGURED)
        assert inactive.with_additional_spend(5.0) is inactive

    def test_baseline_round_trips_as_json_safe_data(self):
        baseline = self._status(1.5).to_baseline()
        assert baseline["currency"] == "USD"
        assert baseline["limits"][0] == {"period": "daily", "limit": 10.0, "spent": 1.5}

    def test_exhausted_message_names_the_period_and_the_fix(self):
        message = sb.exhausted_message(sb.SpendLimitStatus("daily", 10.0, 12.0), "USD")
        assert "daily" in message
        assert "10 USD" in message
        assert "spend_budget" in message
