import sqlite3

import pytest

from deerflow_extension_cad_design.store import Conflict, NotFound, Store


def test_the_file_is_created_on_first_use_only(tmp_path):
    store = Store(tmp_path / "sub" / "designs.sqlite")
    assert not store.exists()
    assert store.design_for_thread("a" * 32, "thread-1") is None
    assert not store.exists(), "the middleware's lookup must not create the file"
    assert store.list_designs("alice") == []
    assert store.exists()
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_a_relative_path_is_refused():
    with pytest.raises(ValueError):
        Store("designs.sqlite")


def test_designs_are_owner_scoped(store):
    store.create_design("alice", "a" * 32, "Bracket", "thread-1")
    assert [d["title"] for d in store.list_designs("alice")] == ["Bracket"]
    assert store.list_designs("bob") == []
    with pytest.raises(NotFound):
        store.get_design("bob", "a" * 32)
    with pytest.raises(NotFound):
        store.rename("bob", "a" * 32, "Mine")
    with pytest.raises(NotFound):
        store.add_version("bob", "a" * 32, parent_id=None, source="hand", scad="cube(1);", params={})


def test_versions_number_per_design_and_move_the_head(store):
    store.create_design("alice", "a" * 32, "One", "thread-1")
    store.create_design("alice", "b" * 32, "Two", "thread-2")
    first = store.add_version("alice", "a" * 32, parent_id=None, source="model", scad="cube(1);", params={"w": 1})
    second = store.add_version("alice", "a" * 32, parent_id=first["id"], source="hand", scad="cube(2);", params={})
    other = store.add_version("alice", "b" * 32, parent_id=None, source="model", scad="sphere(1);", params={})
    assert (first["seq"], second["seq"], other["seq"]) == (1, 2, 1)
    assert second["parent_id"] == first["id"]
    assert store.get_design("alice", "a" * 32)["head_version_id"] == second["id"]
    assert store.get_design("alice", "a" * 32)["versions"] == 2
    store.set_head("alice", "a" * 32, first["id"])
    assert store.get_design("alice", "a" * 32)["head_version_id"] == first["id"]
    with pytest.raises(NotFound):
        store.set_head("alice", "a" * 32, other["id"])
    with pytest.raises(NotFound):
        store.add_version("alice", "a" * 32, parent_id=other["id"], source="hand", scad="", params={})
    with pytest.raises(ValueError):
        store.add_version("alice", "a" * 32, parent_id=None, source="eval", scad="", params={})


def test_render_final_and_repair_flag_are_stored(store):
    store.create_design("alice", "a" * 32, "One", "thread-1")
    version = store.add_version("alice", "a" * 32, parent_id=None, source="model", scad="cube(1);", params={})
    store.set_render("alice", "a" * 32, version["id"], {"ok": True, "partial": False, "bbox_mm": [1, 1, 1]})
    store.set_final("alice", "a" * 32, version["id"], {"status": "running", "files": []})
    store.mark_repair("alice", "a" * 32, version["id"])
    saved = store.get_version("alice", "a" * 32, version["id"])
    assert saved["render"]["bbox_mm"] == [1, 1, 1]
    assert saved["final"]["status"] == "running"
    assert saved["repair_requested"] is True


def test_trash_restore_and_purge(store):
    store.create_design("alice", "a" * 32, "One", "thread-1")
    store.add_version("alice", "a" * 32, parent_id=None, source="model", scad="cube(1);", params={})
    with pytest.raises(NotFound):
        store.purge("alice", "a" * 32)  # only from the trash
    store.delete("alice", "a" * 32)
    assert store.list_designs("alice") == []
    assert [d["id"] for d in store.list_designs("alice", trash=True)] == ["a" * 32]
    with pytest.raises(NotFound):
        store.get_design("alice", "a" * 32)
    assert store.design_for_thread("a" * 32, "thread-1") is None
    store.restore("alice", "a" * 32)
    assert store.design_for_thread("a" * 32, "thread-1") is not None
    store.delete("alice", "a" * 32)
    store.purge("alice", "a" * 32)
    assert store.list_designs("alice", trash=True) == []
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 0


def test_the_thread_binds_a_design_for_the_middleware(store):
    store.create_design("alice", "a" * 32, "One", "thread-1")
    assert store.design_for_thread("a" * 32, "thread-1")["id"] == "a" * 32
    assert store.design_for_thread("a" * 32, "thread-2") is None
    version = store.add_version("alice", "a" * 32, parent_id=None, source="model", scad="cube(1);", params={})
    assert store.record_final_for_thread("a" * 32, "thread-1", version["id"], {"status": "built"})
    assert not store.record_final_for_thread("a" * 32, "thread-2", version["id"], {"status": "failed"})
    assert store.get_version("alice", "a" * 32, version["id"])["final"] == {"status": "built"}


def test_limits(store, monkeypatch):
    import deerflow_extension_cad_design.store as module

    monkeypatch.setattr(module, "MAX_DESIGNS_PER_OWNER", 1)
    monkeypatch.setattr(module, "MAX_VERSIONS_PER_DESIGN", 1)
    store.create_design("alice", "a" * 32, "One", "thread-1")
    with pytest.raises(Conflict):
        store.create_design("alice", "b" * 32, "Two", "thread-2")
    store.add_version("alice", "a" * 32, parent_id=None, source="model", scad="cube(1);", params={})
    with pytest.raises(Conflict):
        store.add_version("alice", "a" * 32, parent_id=None, source="hand", scad="cube(1);", params={})
