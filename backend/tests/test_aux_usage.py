"""Tests for the durable auxiliary-usage registry.

Backs the sidebar's separate memory / suggestions token+cost counters. The
registry is an in-memory write-through cache over a small dedicated SQLite
store, so the totals survive a Gateway restart (roadmap item 1).
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from deerflow.runtime import aux_usage
from deerflow.runtime.aux_usage_store import AuxUsageStore, resolve_aux_usage_db_path


@pytest.fixture(autouse=True)
def aux_db(tmp_path, monkeypatch):
    """Run every test in this module against a per-test durable store.

    Production defaults durability ON; the suite-wide conftest fixture turns it
    off so unrelated tests never touch the developer's checkout, so this module
    opts back in explicitly.
    """
    path = tmp_path / "aux_usage.sqlite3"
    monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(path))
    aux_usage.reset_aux_usage()
    yield path
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


def test_unknown_thread_read_does_not_populate_the_cache():
    # A read miss must not occupy an LRU slot, or polling unknown threads could
    # evict live ones.
    aux_usage.get_thread_aux_usage("never-seen")
    assert "never-seen" not in aux_usage._USAGE


def test_thread_cap_evicts_cache_entries_not_data():
    original = aux_usage._MAX_THREADS
    aux_usage._MAX_THREADS = 3
    try:
        for i in range(5):
            aux_usage.record_aux_usage(f"thread-{i}", "memory", model_name="a", input_tokens=1, output_tokens=1)
        # The cache holds only the newest three...
        assert set(aux_usage._USAGE) == {"thread-2", "thread-3", "thread-4"}
        # ...but eviction is now lossless: an evicted thread re-hydrates from
        # the durable store on its next touch.
        assert aux_usage.get_thread_aux_usage("thread-0")["memory"]["a"]["input_tokens"] == 1
        assert aux_usage.get_thread_aux_usage("thread-1")["memory"]["a"]["calls"] == 1
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


class TestDurability:
    """The counters survive a Gateway restart (roadmap item 1's `Done when`)."""

    def test_totals_are_identical_after_a_cold_start(self):
        aux_usage.record_aux_usage("t-cold", "memory", model_name="mem", input_tokens=500, output_tokens=100, cache_read_tokens=200)
        aux_usage.record_aux_usage("t-cold", "suggestions", model_name="sug", input_tokens=40, output_tokens=12)
        before = aux_usage.get_thread_aux_usage("t-cold")

        # Simulate a Gateway restart: the process-local cache and the store
        # handle go away; the SQLite file does not.
        aux_usage.reset_aux_usage_cache()
        assert aux_usage._USAGE == {}

        assert aux_usage.get_thread_aux_usage("t-cold") == before

    def test_recording_after_a_cold_start_accumulates_without_double_counting(self):
        aux_usage.record_aux_usage("t-cold", "memory", model_name="mem", input_tokens=100, output_tokens=10)
        aux_usage.reset_aux_usage_cache()

        # A read hydrates the cache; the following write must extend the
        # hydrated totals rather than replaying them.
        aux_usage.get_thread_aux_usage("t-cold")
        aux_usage.record_aux_usage("t-cold", "memory", model_name="mem", input_tokens=50, output_tokens=5)

        assert aux_usage.get_thread_aux_usage("t-cold")["memory"]["mem"] == {
            "input_tokens": 150,
            "output_tokens": 15,
            "total_tokens": 165,
            "cache_read_tokens": 0,
            "calls": 2,
        }
        # And the durable side agrees with the cached view.
        aux_usage.reset_aux_usage_cache()
        assert aux_usage.get_thread_aux_usage("t-cold")["memory"]["mem"]["input_tokens"] == 150

    def test_writing_before_hydration_is_not_replayed_by_a_later_read(self):
        # A thread whose first touch is a write must not later merge its own
        # persisted rows on top of the in-memory copy.
        aux_usage.record_aux_usage("t-first-write", "memory", model_name="mem", input_tokens=7, output_tokens=3)
        aux_usage.record_aux_usage("t-first-write", "memory", model_name="mem", input_tokens=7, output_tokens=3)
        assert aux_usage.get_thread_aux_usage("t-first-write")["memory"]["mem"]["input_tokens"] == 14

    def test_a_second_reader_of_the_same_file_sees_the_same_totals(self, aux_db):
        aux_usage.record_aux_usage("t-shared", "memory", model_name="mem", input_tokens=11, output_tokens=2, cache_read_tokens=3)
        # Stand in for a sibling process reading the same store file.
        other = AuxUsageStore(aux_db)
        try:
            assert other.read_thread("t-shared") == {
                "memory": {"mem": {"input_tokens": 11, "output_tokens": 2, "total_tokens": 13, "cache_read_tokens": 3, "calls": 1}},
            }
        finally:
            other.close()

    def test_reset_clears_the_durable_rows_too(self, aux_db):
        aux_usage.record_aux_usage("t-reset", "memory", model_name="mem", input_tokens=5, output_tokens=1)
        aux_usage.reset_aux_usage()
        assert aux_usage.get_thread_aux_usage("t-reset") == {}
        other = AuxUsageStore(aux_db)
        try:
            assert other.read_thread("t-reset") == {}
        finally:
            other.close()


class TestDurabilityDisabled:
    """``DEER_FLOW_AUX_USAGE_DB=0`` restores the previous process-local counter."""

    @pytest.fixture(autouse=True)
    def _no_store(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", "0")
        aux_usage.reset_aux_usage()
        yield
        aux_usage.reset_aux_usage()

    def test_recording_still_works_in_memory(self):
        aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=3, output_tokens=1)
        assert aux_usage.get_thread_aux_usage("t1")["memory"]["a"]["input_tokens"] == 3

    def test_totals_are_lost_on_a_cold_start(self):
        aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=3, output_tokens=1)
        aux_usage.reset_aux_usage_cache()
        assert aux_usage.get_thread_aux_usage("t1") == {}


class TestStoreFailureIsBestEffort:
    """A broken store degrades to the in-memory counter, never to an exception."""

    @pytest.fixture(autouse=True)
    def _unusable_store(self, tmp_path, monkeypatch):
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(blocker / "aux_usage.sqlite3"))
        aux_usage.reset_aux_usage_cache()
        yield
        aux_usage.reset_aux_usage_cache()

    def test_record_and_read_fall_back_to_the_cache_with_one_warning(self, caplog):
        with caplog.at_level("WARNING", logger="deerflow.runtime.aux_usage_store"):
            aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=3, output_tokens=1)
            aux_usage.record_aux_usage("t1", "memory", model_name="a", input_tokens=3, output_tokens=1)
        assert aux_usage.get_thread_aux_usage("t1")["memory"]["a"]["input_tokens"] == 6
        warnings = [r for r in caplog.records if r.levelname == "WARNING" and "auxiliary-usage store" in r.getMessage()]
        assert len(warnings) == 1


class TestStorePathResolution:
    def test_defaults_under_the_deerflow_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_AUX_USAGE_DB", raising=False)
        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
        assert resolve_aux_usage_db_path() == tmp_path / "aux_usage.sqlite3"

    @pytest.mark.parametrize("value", ["0", "off", "false", "no", "none", "disabled", "", "  OFF  "])
    def test_disabled_values(self, value, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", value)
        assert resolve_aux_usage_db_path() is None

    def test_explicit_path(self, tmp_path, monkeypatch):
        target = tmp_path / "nested" / "custom.sqlite3"
        monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(target))
        assert resolve_aux_usage_db_path() == target


class TestStore:
    """Direct unit coverage for the SQLite store itself."""

    def test_unknown_thread_reads_empty(self, tmp_path):
        store = AuxUsageStore(tmp_path / "db.sqlite3")
        try:
            assert store.read_thread("nope") == {}
        finally:
            store.close()

    def test_rows_are_summed_per_category_and_model(self, tmp_path):
        store = AuxUsageStore(tmp_path / "db.sqlite3")
        try:
            for _ in range(3):
                assert store.add("t", "memory", "m", input_tokens=10, output_tokens=2, total_tokens=12, cache_read_tokens=1, calls=1)
            store.add("t", "suggestions", "s", input_tokens=1, output_tokens=1, total_tokens=2, cache_read_tokens=0, calls=1)
            store.add("other", "memory", "m", input_tokens=99, output_tokens=99, total_tokens=198, cache_read_tokens=0, calls=1)
            assert store.read_thread("t") == {
                "memory": {"m": {"input_tokens": 30, "output_tokens": 6, "total_tokens": 36, "cache_read_tokens": 3, "calls": 3}},
                "suggestions": {"s": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2, "cache_read_tokens": 0, "calls": 1}},
            }
        finally:
            store.close()

    def test_the_file_is_created_with_its_parent_directory(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "db.sqlite3"
        store = AuxUsageStore(path)
        try:
            store.add("t", "memory", "m", input_tokens=1, output_tokens=1, total_tokens=2, cache_read_tokens=0, calls=1)
            assert path.exists()
        finally:
            store.close()

    def test_close_is_idempotent(self, tmp_path):
        store = AuxUsageStore(tmp_path / "db.sqlite3")
        store.add("t", "memory", "m", input_tokens=1, output_tokens=1, total_tokens=2, cache_read_tokens=0, calls=1)
        store.close()
        store.close()
        # Reopens transparently.
        assert store.read_thread("t")["memory"]["m"]["calls"] == 1
        store.close()


class TestAsyncWrappers:
    """Async callers must never touch the store from the event loop."""

    def test_arecord_and_aget_round_trip(self):
        async def scenario():
            await aux_usage.arecord_aux_usage("t-async", "suggestions", model_name="s", input_tokens=9, output_tokens=1)
            return await aux_usage.aget_thread_aux_usage("t-async")

        usage = asyncio.run(scenario())
        assert usage["suggestions"]["s"] == {"input_tokens": 9, "output_tokens": 1, "total_tokens": 10, "cache_read_tokens": 0, "calls": 1}
