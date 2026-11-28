"""Owner-scoped designs in one SQLite file.

A design is a title and the hidden conversation its runs use. Its versions are
not stored here: they are the folders cadkit writes in that conversation,
``/mnt/user-data/outputs/design/v<N>/``, which the page lists through the host.
Deleting a design moves it to the trash; only purging removes the row.

Files written by an earlier release also hold a ``versions`` table and a
``designs.head_version_id`` column. They keep working as they are: nothing here
reads them, inserts leave the extra column NULL, and the foreign key's cascade
removes a purged design's old version rows. The schema is never altered or
dropped, so a downgrade still opens the file.

The file is created on first use, not at install, so a Gateway that never opens
the page never touches DEER_FLOW_HOME. Every query that a caller reaches names
the owner, except the one the middleware uses, which binds a design to the
conversation a run executes in instead (the host already checked who owns it).
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Bounds that keep one owner's page loadable and the file small.
MAX_DESIGNS_PER_OWNER = 200
MAX_TITLE_CHARS = 120
DEFAULT_TITLE = "Untitled design"
FIELDS = ("id", "title", "thread_id", "run_id", "created_at", "updated_at", "deleted_at")


class NotFound(LookupError):
    """The design does not exist for this owner."""


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
        # An earlier release's versions rows go with their design on purge.
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _create(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS designs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, thread_id TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS designs_owner ON designs(owner)")

    # -- reading ---------------------------------------------------------------

    @staticmethod
    def _design(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in FIELDS}

    def _owned(self, db: sqlite3.Connection, owner: str, design_id: str, *, deleted: bool | None = False) -> sqlite3.Row:
        row = db.execute("SELECT * FROM designs WHERE id=? AND owner=?", (design_id, owner)).fetchone()
        if row is None or (deleted is False and row["deleted_at"] is not None) or (deleted is True and row["deleted_at"] is None):
            raise NotFound("design unavailable")
        return row

    def list_designs(self, owner: str, *, trash: bool = False) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT * FROM designs WHERE owner=? AND (deleted_at IS NOT NULL)=? ORDER BY updated_at DESC, rowid DESC",
                (owner, 1 if trash else 0),
            ).fetchall()
        return [self._design(row) for row in rows]

    def get_design(self, owner: str, design_id: str, *, deleted: bool | None = False) -> dict[str, Any]:
        with closing(self.connect()) as db:
            return self._design(self._owned(db, owner, design_id, deleted=deleted))

    # -- for the middleware: bound to the run's conversation, not an owner -------

    def design_for_thread(self, design_id: str, thread_id: str) -> dict[str, Any] | None:
        """The live design whose conversation this is, or None. Never creates the file."""
        if not self.exists():
            return None
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM designs WHERE id=? AND thread_id=? AND deleted_at IS NULL", (design_id, thread_id)).fetchone()
        return self._design(row) if row is not None else None

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
            db.execute("DELETE FROM designs WHERE id=?", (design_id,))

    def set_run(self, owner: str, design_id: str, run_id: str | None) -> None:
        with closing(self.connect()) as db, db:
            self._owned(db, owner, design_id)
            db.execute("UPDATE designs SET run_id=?, updated_at=? WHERE id=?", (run_id, now(), design_id))
