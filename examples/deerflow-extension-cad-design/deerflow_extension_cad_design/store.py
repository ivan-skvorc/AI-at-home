"""Owner-scoped designs and their versions in one SQLite file.

A design is its own entity: a title, the hidden conversation its runs use, and
a head pointer into an append-only list of versions. Every render, hand edit,
slider release and model draft adds a version; nothing rewrites one except its
render result, its finalize record and its one-repair flag. Deleting a design
moves it to the trash; only purging removes rows.

The file is created on first use, not at install, so a Gateway that never opens
the page never touches DEER_FLOW_HOME. Every query that a caller reaches names
the owner, except the two the middleware uses, which bind a design to the
conversation a run executes in instead (the host already checked who owns it).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCES = frozenset({"model", "hand", "slider", "finalize", "repair"})
#: Bounds that keep one owner's page loadable and the file small.
MAX_DESIGNS_PER_OWNER = 200
MAX_VERSIONS_PER_DESIGN = 500
MAX_TITLE_CHARS = 120
DEFAULT_TITLE = "Untitled design"


class NotFound(LookupError):
    """The design or version does not exist for this owner."""


class Conflict(RuntimeError):
    """The request is valid but the record's state refuses it."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id() -> str:
    return uuid.uuid4().hex


def clean_title(value: Any) -> str:
    if value is None:
        return DEFAULT_TITLE
    if not isinstance(value, str):
        raise ValueError("title must be text")
    title = " ".join(value.split())[:MAX_TITLE_CHARS]
    return title or DEFAULT_TITLE


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("storage_path must be absolute")
        self._ready = False
        self._lock = threading.Lock()

    def exists(self) -> bool:
        return self.path.exists()

    def connect(self) -> sqlite3.Connection:
        if not self._ready:
            with self._lock:
                if not self._ready:
                    self._create()
                    self._ready = True
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _create(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS designs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, thread_id TEXT NOT NULL, "
                "head_version_id TEXT, run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS designs_owner ON designs(owner)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS versions (id TEXT PRIMARY KEY, design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE, "
                "parent_id TEXT, seq INTEGER NOT NULL, source TEXT NOT NULL, scad TEXT NOT NULL, params TEXT NOT NULL, render TEXT, final TEXT, "
                "run_id TEXT, repair_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, UNIQUE(design_id, seq))"
            )

    # -- reading ---------------------------------------------------------------

    @staticmethod
    def _design(row: sqlite3.Row, versions: int | None = None) -> dict[str, Any]:
        design = {key: row[key] for key in ("id", "title", "thread_id", "head_version_id", "run_id", "created_at", "updated_at", "deleted_at")}
        if versions is not None:
            design["versions"] = versions
        return design

    @staticmethod
    def _version(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "design_id": row["design_id"],
            "parent_id": row["parent_id"],
            "seq": row["seq"],
            "source": row["source"],
            "scad": row["scad"],
            "params": json.loads(row["params"]),
            "render": json.loads(row["render"]) if row["render"] else None,
            "final": json.loads(row["final"]) if row["final"] else None,
            "run_id": row["run_id"],
            "repair_requested": bool(row["repair_requested"]),
            "created_at": row["created_at"],
        }

    def _owned(self, db: sqlite3.Connection, owner: str, design_id: str, *, deleted: bool | None = False) -> sqlite3.Row:
        row = db.execute("SELECT * FROM designs WHERE id=? AND owner=?", (design_id, owner)).fetchone()
        if row is None or (deleted is False and row["deleted_at"] is not None) or (deleted is True and row["deleted_at"] is None):
            raise NotFound("design unavailable")
        return row

    def list_designs(self, owner: str, *, trash: bool = False) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT d.*, (SELECT count(*) FROM versions v WHERE v.design_id=d.id) AS n FROM designs d WHERE owner=? AND (deleted_at IS NOT NULL)=? ORDER BY updated_at DESC, rowid DESC",
                (owner, 1 if trash else 0),
            ).fetchall()
        return [self._design(row, row["n"]) for row in rows]

    def get_design(self, owner: str, design_id: str, *, deleted: bool | None = False) -> dict[str, Any]:
        with closing(self.connect()) as db:
            row = self._owned(db, owner, design_id, deleted=deleted)
            count = db.execute("SELECT count(*) FROM versions WHERE design_id=?", (design_id,)).fetchone()[0]
        return self._design(row, count)

    def versions(self, owner: str, design_id: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            self._owned(db, owner, design_id)
            rows = db.execute("SELECT * FROM versions WHERE design_id=? ORDER BY seq", (design_id,)).fetchall()
        return [self._version(row) for row in rows]

    def get_version(self, owner: str, design_id: str, version_id: str) -> dict[str, Any]:
        with closing(self.connect()) as db:
            self._owned(db, owner, design_id)
            row = db.execute("SELECT * FROM versions WHERE id=? AND design_id=?", (version_id, design_id)).fetchone()
        if row is None:
            raise NotFound("version unavailable")
        return self._version(row)

    # -- for the middleware: bound to the run's conversation, not an owner -------

    def design_for_thread(self, design_id: str, thread_id: str) -> dict[str, Any] | None:
        """The live design whose conversation this is, or None. Never creates the file."""
        if not self.exists():
            return None
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM designs WHERE id=? AND thread_id=? AND deleted_at IS NULL", (design_id, thread_id)).fetchone()
        return self._design(row) if row is not None else None

    def thread_versions(self, design_id: str, thread_id: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT v.* FROM versions v JOIN designs d ON d.id=v.design_id WHERE d.id=? AND d.thread_id=? ORDER BY v.seq",
                (design_id, thread_id),
            ).fetchall()
        return [self._version(row) for row in rows]

    def record_final_for_thread(self, design_id: str, thread_id: str, version_id: str, final: dict[str, Any]) -> bool:
        with closing(self.connect()) as db, db:
            changed = db.execute(
                "UPDATE versions SET final=? WHERE id=? AND design_id=(SELECT id FROM designs WHERE id=? AND thread_id=?)",
                (json.dumps(final), version_id, design_id, thread_id),
            ).rowcount
            if changed:
                db.execute("UPDATE designs SET updated_at=? WHERE id=?", (now(), design_id))
        return bool(changed)

    # -- writing ---------------------------------------------------------------

    def create_design(self, owner: str, design_id: str, title: str, thread_id: str) -> dict[str, Any]:
        stamp = now()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT count(*) FROM designs WHERE owner=?", (owner,)).fetchone()[0] >= MAX_DESIGNS_PER_OWNER:
                raise Conflict(f"You have {MAX_DESIGNS_PER_OWNER} designs; purge some from the trash first")
            db.execute(
                "INSERT INTO designs (id, owner, title, thread_id, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (design_id, owner, title, thread_id, stamp, stamp),
            )
        return self.get_design(owner, design_id)

    def rename(self, owner: str, design_id: str, title: str) -> dict[str, Any]:
        with closing(self.connect()) as db, db:
            self._owned(db, owner, design_id)
            db.execute("UPDATE designs SET title=?, updated_at=? WHERE id=?", (title, now(), design_id))
        return self.get_design(owner, design_id)

    def delete(self, owner: str, design_id: str) -> dict[str, Any]:
        with closing(self.connect()) as db, db:
            self._owned(db, owner, design_id)
            db.execute("UPDATE designs SET deleted_at=? WHERE id=?", (now(), design_id))
        return self.get_design(owner, design_id, deleted=True)

    def restore(self, owner: str, design_id: str) -> dict[str, Any]:
        with closing(self.connect()) as db, db:
            self._owned(db, owner, design_id, deleted=True)
            db.execute("UPDATE designs SET deleted_at=NULL, updated_at=? WHERE id=?", (now(), design_id))
        return self.get_design(owner, design_id)

    def purge(self, owner: str, design_id: str) -> None:
        with closing(self.connect()) as db, db:
            self._owned(db, owner, design_id, deleted=True)
            db.execute("DELETE FROM versions WHERE design_id=?", (design_id,))
            db.execute("DELETE FROM designs WHERE id=?", (design_id,))

    def set_run(self, owner: str, design_id: str, run_id: str | None) -> None:
        with closing(self.connect()) as db, db:
            self._owned(db, owner, design_id)
            db.execute("UPDATE designs SET run_id=?, updated_at=? WHERE id=?", (run_id, now(), design_id))

    def add_version(
        self,
        owner: str,
        design_id: str,
        *,
        parent_id: str | None,
        source: str,
        scad: str,
        params: dict[str, Any],
        run_id: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a version and make it the head. ``thread_id``, when given, must be the design's."""
        if source not in SOURCES:
            raise ValueError("unknown version source")
        version_id = new_id()
        stamp = now()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            design = self._owned(db, owner, design_id)
            if thread_id is not None and design["thread_id"] != thread_id:
                raise NotFound("design unavailable")
            if parent_id is not None and db.execute("SELECT 1 FROM versions WHERE id=? AND design_id=?", (parent_id, design_id)).fetchone() is None:
                raise NotFound("parent version unavailable")
            seq = db.execute("SELECT coalesce(max(seq), 0) FROM versions WHERE design_id=?", (design_id,)).fetchone()[0] + 1
            if seq > MAX_VERSIONS_PER_DESIGN:
                raise Conflict(f"A design keeps at most {MAX_VERSIONS_PER_DESIGN} versions; start a new design")
            db.execute(
                "INSERT INTO versions (id, design_id, parent_id, seq, source, scad, params, run_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (version_id, design_id, parent_id, seq, source, scad, json.dumps(params), run_id, stamp),
            )
            db.execute("UPDATE designs SET head_version_id=?, updated_at=? WHERE id=?", (version_id, stamp, design_id))
        return self.get_version(owner, design_id, version_id)

    def _update_version(self, owner: str, design_id: str, version_id: str, column: str, value: Any) -> dict[str, Any]:
        assert column in ("render", "final", "repair_requested")
        with closing(self.connect()) as db, db:
            self._owned(db, owner, design_id)
            changed = db.execute(f"UPDATE versions SET {column}=? WHERE id=? AND design_id=?", (value, version_id, design_id)).rowcount  # noqa: S608 - column is one of three literals
            if not changed:
                raise NotFound("version unavailable")
            db.execute("UPDATE designs SET updated_at=? WHERE id=?", (now(), design_id))
        return self.get_version(owner, design_id, version_id)

    def set_render(self, owner: str, design_id: str, version_id: str, render: dict[str, Any]) -> dict[str, Any]:
        return self._update_version(owner, design_id, version_id, "render", json.dumps(render))

    def set_final(self, owner: str, design_id: str, version_id: str, final: dict[str, Any]) -> dict[str, Any]:
        return self._update_version(owner, design_id, version_id, "final", json.dumps(final))

    def mark_repair(self, owner: str, design_id: str, version_id: str) -> dict[str, Any]:
        return self._update_version(owner, design_id, version_id, "repair_requested", 1)

    def set_head(self, owner: str, design_id: str, version_id: str) -> dict[str, Any]:
        with closing(self.connect()) as db, db:
            self._owned(db, owner, design_id)
            if db.execute("SELECT 1 FROM versions WHERE id=? AND design_id=?", (version_id, design_id)).fetchone() is None:
                raise NotFound("version unavailable")
            db.execute("UPDATE designs SET head_version_id=?, updated_at=? WHERE id=?", (version_id, now(), design_id))
        return self.get_design(owner, design_id)
