"""Tests for the process-local auxiliary-usage registry.

Backs the sidebar's separate memory / suggestions token+cost counters.
"""

from __future__ import annotations

import threading

import pytest

from deerflow.runtime import aux_usage


@pytest.fixture(autouse=True)
def _clean_registry():
    aux_usage.reset_aux_usage()
    yield
    aux_usage.reset_aux_usage()


def test_record_and_read_single_call():
    aux_usage.record_aux_usage("t1", "memory", model_name="mem-model", input_tokens=100, output_tokens=20)
    usage = aux_usage.get_thread_aux_usage("t1")
    assert usage == {
        "memory": {
            "mem-model": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "cache_read_tokens": 0, "calls": 1},
        },
    }


def test_totals_default_to_input_plus_output_and_accumulate():
    aux_usage.record_aux_usage("t1", "suggestions", model_name="s", input_tokens=10, output_tokens=5)
    aux_usage.record_aux_usage("t1", "suggestions", model_name="s", input_tokens=1, output_tokens=2, cache_read_tokens=1)
    usage = aux_usage.get_thread_aux_usage("t1")
    assert usage["suggestions"]["s"] == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18, "cache_read_tokens": 1, "calls": 2}


def test_categories_and_models_are_isolated():
    aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=1, output_tokens=1)
    aux_usage.record_aux_usage("t1", "suggestions", model_name="b", input_tokens=2, output_tokens=2)
    usage = aux_usage.get_thread_aux_usage("t1")
    assert set(usage) == {"memory", "suggestions"}
    assert set(usage["memory"]) == {"a"}
    assert set(usage["suggestions"]) == {"b"}


def test_threads_isolated_and_unknown_thread_empty():
    aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=1, output_tokens=1)
    assert aux_usage.get_thread_aux_usage("t2") == {}
    assert aux_usage.get_thread_aux_usage(None) == {}


def test_explicit_total_tokens_respected():
    aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=100, output_tokens=50, total_tokens=999)
    assert aux_usage.get_thread_aux_usage("t1")["memory"]["a"]["total_tokens"] == 999


def test_missing_model_name_falls_back_to_unknown():
    aux_usage.record_aux_usage("t1", "memory", model_name=None, input_tokens=1, output_tokens=1)
    assert "unknown" in aux_usage.get_thread_aux_usage("t1")["memory"]


def test_noops_are_ignored():
    aux_usage.record_aux_usage(None, "memory", model_name="a", input_tokens=1, output_tokens=1)
    aux_usage.record_aux_usage("t1", "", model_name="a", input_tokens=1, output_tokens=1)
    # Zero usage is not recorded (no counter row created).
    aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=0, output_tokens=0)
    assert aux_usage.get_thread_aux_usage("t1") == {}


def test_non_numeric_tokens_coerce_to_zero():
    aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens="oops", output_tokens=None, total_tokens=7)
    assert aux_usage.get_thread_aux_usage("t1")["memory"]["a"] == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 7, "cache_read_tokens": 0, "calls": 1}


def test_read_returns_deep_copy():
    aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=1, output_tokens=1)
    snapshot = aux_usage.get_thread_aux_usage("t1")
    snapshot["memory"]["a"]["input_tokens"] = 9999
    # Mutating the snapshot must not corrupt the registry.
    assert aux_usage.get_thread_aux_usage("t1")["memory"]["a"]["input_tokens"] == 1


def test_thread_cap_evicts_oldest():
    original = aux_usage._MAX_THREADS
    aux_usage._MAX_THREADS = 3
    try:
        for i in range(5):
            aux_usage.record_aux_usage(f"thread-{i}", "memory", model_name="a", input_tokens=1, output_tokens=1)
        # Oldest two evicted; newest three retained.
        assert aux_usage.get_thread_aux_usage("thread-0") == {}
        assert aux_usage.get_thread_aux_usage("thread-1") == {}
        for i in (2, 3, 4):
            assert aux_usage.get_thread_aux_usage(f"thread-{i}") != {}
    finally:
        aux_usage._MAX_THREADS = original


def test_concurrent_recording_is_thread_safe():
    def worker():
        for _ in range(200):
            aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=1, output_tokens=1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    entry = aux_usage.get_thread_aux_usage("t1")["memory"]["a"]
    assert entry["input_tokens"] == 8 * 200
    assert entry["calls"] == 8 * 200
