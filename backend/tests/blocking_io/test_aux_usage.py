"""Regression anchor: the durable aux-usage registry must not block the loop.

``deerflow.runtime.aux_usage`` is write-through to a local SQLite file, so its
sync API (``record_aux_usage`` / ``get_thread_aux_usage``) performs filesystem
IO by design — that is what lets the memory updater's loop-less debounce worker
record durably. The two async entry points into it, used by the Gateway's
suggestions route and the ``token-usage`` endpoint, must therefore offload with
``asyncio.to_thread``.

This anchor drives ``arecord_aux_usage`` (write, including the first-touch
hydrate) and ``aget_thread_aux_usage`` (cold-cache read) under the strict
Blockbuster gate, so re-pointing either caller at the sync function fails CI
instead of quietly stalling the event loop on every answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def durable_aux_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Enable the durable store (the suite default turns it off) on a tmp file."""
    from deerflow.runtime import aux_usage

    monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(tmp_path / "aux_usage.sqlite3"))
    aux_usage.reset_aux_usage_cache()
    yield aux_usage
    aux_usage.reset_aux_usage()


async def test_async_aux_usage_api_does_not_block_event_loop(durable_aux_store) -> None:
    aux_usage = durable_aux_store

    # Write path: the first call opens the SQLite file, creates the schema and
    # hydrates the cache; the second exercises the steady-state insert.
    await aux_usage.arecord_aux_usage("t-block", "memory", model_name="mem", input_tokens=100, output_tokens=20, cache_read_tokens=5)
    await aux_usage.arecord_aux_usage("t-block", "suggestions", model_name="sug", input_tokens=10, output_tokens=2)

    # Read path with a warm cache.
    usage = await aux_usage.aget_thread_aux_usage("t-block")
    assert usage["memory"]["mem"]["input_tokens"] == 100

    # Read path with a cold cache: this is the one that hits the disk, and the
    # one the token-usage endpoint takes after a Gateway restart.
    aux_usage.reset_aux_usage_cache()
    cold = await aux_usage.aget_thread_aux_usage("t-block")
    assert cold == usage


async def test_spend_budget_resolution_does_not_block_event_loop(durable_aux_store, tmp_path: Path) -> None:
    """The spend cap reads the same store on the run-admission hot path.

    ``resolve_spend_budget_status`` runs on every run creation and on every
    header poll once a cap is configured, and it aggregates the auxiliary store
    (a SQLite file) alongside the runs table. Both must be offloaded.
    """
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.gateway.spend_budget import resolve_spend_budget_status
    from deerflow.config.spend_budget_config import SpendBudgetConfig
    from deerflow.persistence.base import Base

    aux_usage = durable_aux_store
    await aux_usage.arecord_aux_usage("t-spend", "memory", model_name="premium-1", input_tokens=1000, output_tokens=100)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'spend.db'}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    import app.gateway.spend_budget as spend_budget_module

    original = spend_budget_module.get_session_factory
    spend_budget_module.get_session_factory = lambda: session_factory
    try:
        app_config = SimpleNamespace(
            models=[SimpleNamespace(name="premium", model="premium-1", display_name="Premium", pricing={"currency": "USD", "input_per_million": 1.0, "output_per_million": 5.0})],
            spend_budget=SpendBudgetConfig(enabled=True, daily_limit=10),
        )
        status = await resolve_spend_budget_status(app_config=app_config, user_id=None)
        assert status.active is True
        assert status.limits[0].period == "daily"
    finally:
        spend_budget_module.get_session_factory = original
        await engine.dispose()
