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
        # Versions are the run's folders: a new file has no table for them.
        assert [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")] == ["designs"]


def test_a_relative_path_is_refused():
    with pytest.raises(ValueError):
        Store("designs.sqlite")


def test_designs_are_owner_scoped(store):
    store.create_design("alice", "a" * 32, "Bracket", "thread-1")
    assert [d["title"] for d in store.list_designs("alice")] == ["Bracket"]
    assert store.list_designs("bob") == []
    for call in (lambda: store.get_design("bob", "a" * 32), lambda: store.rename("bob", "a" * 32, "Mine"), lambda: store.set_run("bob", "a" * 32, "run-1"), lambda: store.delete("bob", "a" * 32)):
        with pytest.raises(NotFound):
            call()


def test_a_design_records_its_run(store):
    design = store.create_design("alice", "a" * 32, "One", "thread-1")
    assert set(design) == {"id", "title", "thread_id", "run_id", "created_at", "updated_at", "deleted_at"}
    store.set_run("alice", "a" * 32, "run-1")
    assert store.get_design("alice", "a" * 32)["run_id"] == "run-1"
    store.set_run("alice", "a" * 32, None)
    assert store.get_design("alice", "a" * 32)["run_id"] is None


def test_trash_restore_and_purge(store):
    store.create_design("alice", "a" * 32, "One", "thread-1")
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


def test_the_thread_binds_a_design_for_the_middleware(store):
    store.create_design("alice", "a" * 32, "One", "thread-1")
    assert store.design_for_thread("a" * 32, "thread-1")["id"] == "a" * 32
    assert store.design_for_thread("a" * 32, "thread-2") is None
    assert store.design_for_thread("b" * 32, "thread-1") is None


def test_limits(store, monkeypatch):
    import deerflow_extension_cad_design.store as module

    monkeypatch.setattr(module, "MAX_DESIGNS_PER_OWNER", 1)
    store.create_design("alice", "a" * 32, "One", "thread-1")
    with pytest.raises(Conflict):
        store.create_design("alice", "b" * 32, "Two", "thread-2")
    store.create_design("bob", "b" * 32, "Two", "thread-2")


#: The schema the first release (#176) wrote: designs with a head pointer, and stored versions.
FIRST_RELEASE = (
    "CREATE TABLE designs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, thread_id TEXT NOT NULL, head_version_id TEXT, run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)",
    "CREATE INDEX designs_owner ON designs(owner)",
    "CREATE TABLE versions (id TEXT PRIMARY KEY, design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE, "
    "parent_id TEXT, seq INTEGER NOT NULL, source TEXT NOT NULL, scad TEXT NOT NULL, params TEXT NOT NULL, render TEXT, final TEXT, "
    "run_id TEXT, repair_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, UNIQUE(design_id, seq))",
)


def test_a_file_from_the_first_release_keeps_working_unchanged(tmp_path):
    path = tmp_path / "designs.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        for statement in FIRST_RELEASE:
            db.execute(statement)
        db.execute("INSERT INTO designs VALUES (?,?,?,?,?,?,?,?,?)", ("a" * 32, "alice", "Old", "thread-1", "v" * 32, None, "2026-11-23T10:00:00Z", "2026-11-23T10:00:00Z", None))
        db.execute("INSERT INTO versions (id, design_id, parent_id, seq, source, scad, params, created_at) VALUES (?,?,?,?,?,?,?,?)", ("v" * 32, "a" * 32, None, 1, "model", "cube(1);", "{}", "2026-11-23T10:00:00Z"))
    with sqlite3.connect(path) as db:
        before = sorted(db.execute("SELECT type, name, sql FROM sqlite_master").fetchall())

    store = Store(path)
    (old,) = store.list_designs("alice")
    assert (old["id"], old["title"], old["thread_id"]) == ("a" * 32, "Old", "thread-1")
    assert "head_version_id" not in old
    assert store.design_for_thread("a" * 32, "thread-1")["id"] == "a" * 32
    new = store.create_design("alice", "b" * 32, "New", "thread-2")
    assert [d["id"] for d in store.list_designs("alice")] == [new["id"], "a" * 32]
    store.rename("alice", "a" * 32, "Renamed")
    store.set_run("alice", "a" * 32, "run-1")
    # Purging an old design takes its stored versions with it (the cascade).
    store.delete("alice", "a" * 32)
    store.purge("alice", "a" * 32)

    with sqlite3.connect(path) as db:
        assert sorted(db.execute("SELECT type, name, sql FROM sqlite_master").fetchall()) == before, "the schema was altered"
        assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 0
        assert db.execute("SELECT head_version_id FROM designs WHERE id=?", ("b" * 32,)).fetchone()[0] is None
