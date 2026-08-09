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
