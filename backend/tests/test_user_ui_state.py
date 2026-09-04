"""Unit tests for the per-user UI-state store (fork feature: durable chat tabs).

The keep-alive chat tab strip used to live only in ``localStorage``, which is
per-browser *and* per-origin — so a pinned set was silently "forgotten" whenever
site data was cleared, the browser evicted storage for an insecure-origin site,
or the app was reopened on a different origin (``localhost`` vs. a LAN/Tailscale
address, both documented ways to reach this fork). This store is the durable
source of truth the browser reconciles against.
"""

from __future__ import annotations

import json

import pytest

from deerflow.config import paths as paths_module
from deerflow.config import user_ui_state
from deerflow.config.paths import get_paths


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_module, "_paths", None)
    user_ui_state.reset_cache_for_tests()
    yield
    monkeypatch.setattr(paths_module, "_paths", None)
    user_ui_state.reset_cache_for_tests()


def _tab(key: str, thread_id: str, title: str | None = None) -> dict:
    tab = {"key": key, "threadId": thread_id}
    if title is not None:
        tab["title"] = title
    return tab


def test_unset_user_returns_empty_list():
    assert user_ui_state.get_chat_tabs("default") == []


def test_round_trip_survives_a_cache_reset():
    tabs = [_tab("k1", "t1", "Alpha"), _tab("k2", "t2")]
    assert user_ui_state.set_chat_tabs("default", tabs) == tabs

    # A fresh process (cold cache) must read the same set back off disk — this
    # is the "survives a restart" property the feature exists for.
    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_tabs("default") == tabs


def test_tabs_are_isolated_per_user():
    user_ui_state.set_chat_tabs("alice", [_tab("k1", "t1")])
    user_ui_state.set_chat_tabs("bob", [_tab("k2", "t2")])
    assert user_ui_state.get_chat_tabs("alice") == [_tab("k1", "t1")]
    assert user_ui_state.get_chat_tabs("bob") == [_tab("k2", "t2")]


def test_explicit_empty_set_is_persisted():
    """Closing the last tab is a real user action, not a wipe to be ignored."""
    user_ui_state.set_chat_tabs("default", [_tab("k1", "t1")])
    assert user_ui_state.set_chat_tabs("default", []) == []
    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_tabs("default") == []


def test_malformed_entries_are_dropped_not_raised():
    stored = user_ui_state.set_chat_tabs(
        "default",
        [
            _tab("k1", "t1", "keep"),
            {"key": "", "threadId": "t2"},  # empty key
            {"key": "k3"},  # missing threadId
            {"threadId": "t4"},  # missing key
            "not-a-dict",
            {"key": "k5", "threadId": "t5", "title": 42},  # bad title type
        ],
    )
    assert stored == [_tab("k1", "t1", "keep"), _tab("k5", "t5")]


def test_duplicate_keys_and_threads_collapse_first_wins():
    stored = user_ui_state.set_chat_tabs(
        "default",
        [_tab("k1", "t1", "first"), _tab("k1", "t9"), _tab("k9", "t1"), _tab("k2", "t2")],
    )
    assert stored == [_tab("k1", "t1", "first"), _tab("k2", "t2")]


def test_tab_count_is_capped():
    stored = user_ui_state.set_chat_tabs(
        "default",
        [_tab(f"k{i}", f"t{i}") for i in range(user_ui_state.MAX_CHAT_TABS + 5)],
    )
    assert len(stored) == user_ui_state.MAX_CHAT_TABS


def test_title_is_length_capped():
    stored = user_ui_state.set_chat_tabs("default", [_tab("k1", "t1", "x" * 1000)])
    assert len(stored[0]["title"]) == user_ui_state.MAX_TITLE_CHARS


def test_corrupt_state_file_degrades_to_empty(caplog):
    path = get_paths().user_dir("default") / user_ui_state.UI_STATE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_tabs("default") == []


def test_non_list_chat_tabs_value_degrades_to_empty():
    path = get_paths().user_dir("default") / user_ui_state.UI_STATE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"chat_tabs": "nope"}), encoding="utf-8")
    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_tabs("default") == []


def test_write_preserves_unrelated_keys():
    """The file is a per-user UI-state bag; a future key must not be clobbered."""
    path = get_paths().user_dir("default") / user_ui_state.UI_STATE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"something_else": {"a": 1}}), encoding="utf-8")
    user_ui_state.reset_cache_for_tests()

    user_ui_state.set_chat_tabs("default", [_tab("k1", "t1")])

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["something_else"] == {"a": 1}
    assert data["chat_tabs"] == [_tab("k1", "t1")]


def test_write_is_atomic_and_leaves_no_temp_file():
    user_ui_state.set_chat_tabs("default", [_tab("k1", "t1")])
    user_dir = get_paths().user_dir("default")
    assert not list(user_dir.glob("*.tmp"))


def test_out_of_band_edit_is_picked_up():
    """A sibling worker's write must be visible without a restart."""
    user_ui_state.set_chat_tabs("default", [_tab("k1", "t1")])
    path = get_paths().user_dir("default") / user_ui_state.UI_STATE_FILENAME
    # Rewrite with a different mtime so the signature check invalidates.
    path.write_text(json.dumps({"chat_tabs": [_tab("k2", "t2")]}), encoding="utf-8")
    import os

    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))
    assert user_ui_state.get_chat_tabs("default") == [_tab("k2", "t2")]


# ---------------------------------------------------------------------------
# Sidebar chat folders (fork feature)
# ---------------------------------------------------------------------------


def _folder(folder_id: str, name: str) -> dict:
    return {"id": folder_id, "name": name}


def test_unset_user_has_no_folders():
    assert user_ui_state.get_chat_folders("default") == []


def test_folders_round_trip_in_display_order_across_a_cache_reset():
    """List order *is* the sidebar order, so it must survive a restart intact."""
    user_ui_state.set_chat_folders("default", [_folder("f1", "Work"), _folder("f2", "Personal")])
    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_folders("default") == [_folder("f1", "Work"), _folder("f2", "Personal")]


def test_folders_are_isolated_per_user():
    user_ui_state.set_chat_folders("alice", [_folder("fa", "Alice")])
    assert user_ui_state.get_chat_folders("bob") == []


def test_explicit_empty_folder_list_is_persisted():
    """Deleting the last folder is a real value, not a no-op."""
    user_ui_state.set_chat_folders("default", [_folder("f1", "Work")])
    user_ui_state.set_chat_folders("default", [])
    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_folders("default") == []


def test_malformed_folders_are_dropped_not_raised():
    stored = user_ui_state.set_chat_folders(
        "default",
        [
            "not-a-dict",
            {"id": "f1"},  # no name
            {"name": "Nameless id"},  # no id
            {"id": "  ", "name": "blank id"},
            {"id": "f2", "name": "   "},  # blank name
            _folder("  f3  ", "  Work  "),  # trimmed, kept
        ],
    )
    assert stored == [_folder("f3", "Work")]


def test_duplicate_folder_ids_collapse_first_wins():
    stored = user_ui_state.set_chat_folders("default", [_folder("f1", "First"), _folder("f1", "Second")])
    assert stored == [_folder("f1", "First")]


def test_folder_count_is_capped():
    stored = user_ui_state.set_chat_folders(
        "default",
        [_folder(f"f{i}", f"Folder {i}") for i in range(user_ui_state.MAX_CHAT_FOLDERS * 3)],
    )
    assert len(stored) == user_ui_state.MAX_CHAT_FOLDERS


def test_folder_name_is_length_capped():
    stored = user_ui_state.set_chat_folders("default", [_folder("f1", "n" * 500)])
    assert len(stored[0]["name"]) == user_ui_state.MAX_FOLDER_NAME_CHARS


def test_non_list_folder_value_degrades_to_empty():
    path = get_paths().user_dir("default") / user_ui_state.UI_STATE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"chat_folders": {"f1": "Work"}}), encoding="utf-8")
    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_folders("default") == []


def test_folders_and_tabs_do_not_clobber_each_other():
    """Both keys share one file; each writer must merge, never replace."""
    user_ui_state.set_chat_tabs("default", [_tab("k1", "t1")])
    user_ui_state.set_chat_folders("default", [_folder("f1", "Work")])
    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_tabs("default") == [_tab("k1", "t1")]
    assert user_ui_state.get_chat_folders("default") == [_folder("f1", "Work")]
