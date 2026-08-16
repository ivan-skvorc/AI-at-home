"""Tests that the memory and suggestions LLM paths record auxiliary usage.

These pin the wiring from each auxiliary LLM call into the per-thread aux
registry that backs the sidebar's separate memory/suggestions counters, and
that both sinks land in the durable store rather than only in process memory.
"""

from __future__ import annotations

import asyncio

import pytest

from app.gateway.routers.suggestions import _record_suggestions_usage
from deerflow.agents.memory.manager import _host_default_extraction_callback
from deerflow.runtime import aux_usage


@pytest.fixture(autouse=True)
def _durable_registry(tmp_path, monkeypatch):
    """Exercise the wiring against a real (per-test) durable store."""
    monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(tmp_path / "aux_usage.sqlite3"))
    aux_usage.reset_aux_usage()
    yield
    aux_usage.reset_aux_usage()


def test_memory_extraction_callback_records_usage_with_cache_read():
    _host_default_extraction_callback(
        {
            "thread_id": "t-mem",
            "model_name": "mem-model",
            "success": True,
            "token_usage": {
                "input_tokens": 500,
                "output_tokens": 100,
                "total_tokens": 600,
                "input_token_details": {"cache_read": 200},
            },
        },
    )
    usage = aux_usage.get_thread_aux_usage("t-mem")
    assert usage["memory"]["mem-model"] == {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600, "cache_read_tokens": 200, "calls": 1}


def test_memory_extraction_callback_no_usage_records_nothing():
    _host_default_extraction_callback({"thread_id": "t-mem", "model_name": "mem-model", "facts_extracted": 3, "facts_passed_confidence": 2})
    assert aux_usage.get_thread_aux_usage("t-mem") == {}


def test_memory_extraction_callback_ignores_non_dict_payload():
    _host_default_extraction_callback(None)  # must not raise
    assert aux_usage.get_thread_aux_usage("t-mem") == {}


def test_suggestions_helper_records_usage():
    asyncio.run(
        _record_suggestions_usage(
            "t-sug",
            "sug-model",
            {"input_tokens": 40, "output_tokens": 12, "total_tokens": 52},
        )
    )
    usage = aux_usage.get_thread_aux_usage("t-sug")
    assert usage["suggestions"]["sug-model"]["total_tokens"] == 52
    assert usage["suggestions"]["sug-model"]["calls"] == 1


def test_suggestions_helper_ignores_missing_usage():
    asyncio.run(_record_suggestions_usage("t-sug", "sug-model", None))
    assert aux_usage.get_thread_aux_usage("t-sug") == {}


def test_both_sinks_survive_a_gateway_restart():
    """The `Done when` for roadmap item 1, end to end through both writers."""
    _host_default_extraction_callback(
        {
            "thread_id": "t-restart",
            "model_name": "mem-model",
            "success": True,
            "token_usage": {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600, "input_token_details": {"cache_read": 200}},
        },
    )
    asyncio.run(_record_suggestions_usage("t-restart", "sug-model", {"input_tokens": 40, "output_tokens": 12, "total_tokens": 52}))
    before = aux_usage.get_thread_aux_usage("t-restart")

    # Restart: process-local cache and store handle dropped, SQLite file kept.
    aux_usage.reset_aux_usage_cache()

    assert aux_usage.get_thread_aux_usage("t-restart") == before
    assert before["memory"]["mem-model"]["cache_read_tokens"] == 200
    assert before["suggestions"]["sug-model"]["total_tokens"] == 52
