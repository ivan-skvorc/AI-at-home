"""SQL repositories for the folder ledger (see :mod:`.model`).

Two front ends share one set of statement builders:

- :class:`FolderLedgerRecorderStore` is **synchronous**. The recorder
  middleware runs on the lead agent's loop *and* on the persistent subagent
  loop, and the async engine's pool is bound to the Gateway's loop, so the
  recorder writes through the process-wide synchronous engine
  (``get_sync_sessionmaker``) from a worker thread, the same way project memory
  does. It never touches the async pool.
- :class:`FolderLedgerRepository` is the Gateway's async facade: thread
  tombstones, branch inheritance, the listings and the orphan query.

Every create-or-update by a unique key is a dialect ``ON CONFLICT`` upsert, so
two first writers (two conversations creating the same folder at once) both
land: the first commit wins ``created_by_*``, the second adds its touch.

**Binding.** A folder row records the mount's host directory and the entry's
``st_dev:st_ino`` (:mod:`.model`). A recorded call that saw the bound entry
before it ran moves the binding to what it left behind (a rewritten bare file
gets a new inode); anything else leaves it alone, so an entry replaced outside
the ledger stops matching and the confined delete refuses it.

**Liveness.** A touch keeps its folder in use while its thread is alive: the
touch is not tombstoned, the thread's ``threads_meta`` row still exists, and
the thread is not a hidden dependent (an edit version or a sidecar) whose
anchor thread is gone. The last two rules are evaluated at query time, so a
thread deleted without the tombstone step (an older Gateway, a failed
best-effort write) still counts as deleted.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, case, delete, exists, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from deerflow.persistence.dialect_insert import dialect_insert
from deerflow.persistence.folder_ledger.model import FolderLedgerDismissalRow, FolderLedgerEventRow, FolderLedgerFolderRow, FolderLedgerTouchRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

ATTRIBUTION_OBSERVED = "observed_create"
ATTRIBUTION_PREEXISTING = "preexisting"
ATTRIBUTION_SHELL = "inferred_shell"

ROLE_CREATED = "created"
ROLE_EDITED = "edited"
ROLE_INHERITED = "inherited"

OP_WRITE = "write"
OP_APPEND = "append"
OP_EDIT = "edit"
OP_SHELL = "shell"
OPS = frozenset({OP_WRITE, OP_APPEND, OP_EDIT, OP_SHELL})

KIND_DIR = "dir"
KIND_FILE = "file"

#: Edit-log rows kept per folder; older rows are pruned in the same transaction.
MAX_EVENTS_PER_FOLDER = 200
#: Folders one listing or orphan answer returns.
MAX_FOLDERS_PER_QUERY = 200
#: Bound on the ids one ``IN (...)`` carries.
_IN_CHUNK = 500

# Thread metadata keys that make a thread a hidden dependent of another one.
# They mirror app/gateway/edit_version_family.py and the sidecar keys of
# routers/threads.py; the harness cannot import the Gateway.
_EDIT_VERSION_FLAG_KEY = "deerflow_edit_version"
_EDIT_ROOT_THREAD_ID_KEY = "edit_root_thread_id"
_SIDECAR_FLAG_KEY = "deerflow_sidecar"
_SIDECAR_PARENT_THREAD_ID_KEY = "parent_thread_id"

_FIELD_LIMITS = {"user_id": 64, "thread_id": 64, "run_id": 64, "tool_call_id": 128, "rel_path": 1024, "mount_path": 512, "name": 255, "host_root": 1024, "entry_before": 64, "entry_after": 64}


@dataclass(frozen=True)
class TouchRecord:
    """One successful write (or shell reference) inside a tracked folder."""

    mount_path: str
    name: str
    kind: str
    rel_path: str
    op: str
    #: This call observed the folder come into existence.
    created: bool
    user_id: str
    thread_id: str
    run_id: str | None = None
    tool_call_id: str | None = None
    #: Normalized host directory of the mount (``mounts.host_root_key``).
    host_root: str | None = None
    #: ``st_dev:st_ino`` of the entry before and after the call; None when
    #: missing, not a directory or regular file, or not visible.
    entry_before: str | None = None
    entry_after: str | None = None

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise ValueError(f"unknown folder ledger op: {self.op!r}")
        if self.kind not in (KIND_DIR, KIND_FILE):
            raise ValueError(f"unknown folder ledger kind: {self.kind!r}")
        for field, limit in _FIELD_LIMITS.items():
            value = getattr(self, field)
            if value is not None and len(value) > limit:
                raise ValueError(f"folder ledger {field} exceeds {limit} characters")
        if not self.name or not self.thread_id or not self.user_id:
            raise ValueError("folder ledger records need a name, a thread and a user")

    @property
    def attribution(self) -> str:
        if not self.created:
            return ATTRIBUTION_PREEXISTING
        return ATTRIBUTION_SHELL if self.op == OP_SHELL else ATTRIBUTION_OBSERVED


def _now() -> datetime:
    return datetime.now(UTC)


def _chunks(values: Sequence[str]) -> Iterable[list[str]]:
    for start in range(0, len(values), _IN_CHUNK):
        yield list(values[start : start + _IN_CHUNK])


# ---------------------------------------------------------------------------
# Statement builders (shared by the sync recorder and the async repository)
# ---------------------------------------------------------------------------


def _folder_upsert_stmt(dialect_name: str, record: TouchRecord, now: datetime):
    """Insert the live folder row or refresh it; RETURNING the live row's id.

    The first commit wins ``created_by_*``. A later write upgrades the
    attribution only when it observed a stronger fact (a pre-existing folder
    that vanished and was recreated, or a shell inference confirmed by a tool
    write), never between two observed creations. An upgrade takes the new
    entry's binding; a call that saw the bound entry before it ran moves the
    binding to the entry it left (see the module docstring).
    """
    insert = dialect_insert(dialect_name, component="folder ledger")
    created = record.created
    stmt = insert(FolderLedgerFolderRow).values(
        id=uuid.uuid4().hex,
        mount_path=record.mount_path,
        name=record.name,
        kind=record.kind,
        created_by_user_id=record.user_id if created else None,
        created_by_thread_id=record.thread_id if created else None,
        created_attribution=record.attribution,
        first_seen_at=now,
        last_touched_at=now,
        host_root=record.host_root,
        host_entry=record.entry_after,
    )
    folder = FolderLedgerFolderRow
    excluded = stmt.excluded
    upgrade = or_(
        and_(folder.created_attribution == ATTRIBUTION_PREEXISTING, excluded.created_attribution != ATTRIBUTION_PREEXISTING),
        and_(folder.created_attribution == ATTRIBUTION_SHELL, excluded.created_attribution == ATTRIBUTION_OBSERVED),
    )
    if record.entry_before and record.entry_after and record.host_root:
        continued = and_(folder.host_entry == record.entry_before, folder.host_root == record.host_root)
    else:
        continued = false()
    stmt = stmt.on_conflict_do_update(
        index_elements=[folder.mount_path, folder.name],
        index_where=folder.deleted_at.is_(None),
        set_={
            "last_touched_at": excluded.last_touched_at,
            "created_attribution": case((upgrade, excluded.created_attribution), else_=folder.created_attribution),
            "created_by_user_id": case((upgrade, excluded.created_by_user_id), else_=folder.created_by_user_id),
            "created_by_thread_id": case((upgrade, excluded.created_by_thread_id), else_=folder.created_by_thread_id),
            "host_root": case((upgrade, excluded.host_root), else_=folder.host_root),
            "host_entry": case((upgrade, excluded.host_entry), (continued, excluded.host_entry), else_=folder.host_entry),
        },
    )
    return stmt.returning(folder.id)


def _touch_upsert_stmt(dialect_name: str, folder_id: str, record: TouchRecord, now: datetime):
    """Insert or advance one (folder, user, thread) touch.

    Counters add up, the strongest role wins (created > edited > inherited),
    and a write clears the thread's tombstone. Thread ids are reusable (a
    deleted conversation's id comes back when a client or an IM binding starts
    it again), and the recreated thread's writes must keep the folder in use.
    A straggling write of a deleted thread still does not: liveness also
    requires the ``threads_meta`` row, which the thread delete removes first.
    """
    insert = dialect_insert(dialect_name, component="folder ledger")
    role = ROLE_CREATED if record.created else ROLE_EDITED
    stmt = insert(FolderLedgerTouchRow).values(
        folder_id=folder_id,
        user_id=record.user_id,
        thread_id=record.thread_id,
        role=role,
        first_at=now,
        last_at=now,
        last_run_id=record.run_id,
        writes=1 if record.op in (OP_WRITE, OP_APPEND) else 0,
        edits=1 if record.op == OP_EDIT else 0,
        shell_ops=1 if record.op == OP_SHELL else 0,
    )
    touch = FolderLedgerTouchRow
    excluded = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=[touch.folder_id, touch.user_id, touch.thread_id],
        set_={
            "role": case(
                (or_(touch.role == ROLE_CREATED, excluded.role == ROLE_CREATED), ROLE_CREATED),
                (or_(touch.role == ROLE_EDITED, excluded.role == ROLE_EDITED), ROLE_EDITED),
                else_=ROLE_INHERITED,
            ),
            "last_at": excluded.last_at,
            "thread_deleted_at": None,
            "last_run_id": func.coalesce(excluded.last_run_id, touch.last_run_id),
            "writes": touch.writes + excluded.writes,
            "edits": touch.edits + excluded.edits,
            "shell_ops": touch.shell_ops + excluded.shell_ops,
        },
    )
    return stmt


def _event_insert_stmt(folder_id: str, record: TouchRecord, now: datetime):
    return FolderLedgerEventRow.__table__.insert().values(
        folder_id=folder_id,
        user_id=record.user_id,
        thread_id=record.thread_id,
        run_id=record.run_id,
        tool_call_id=record.tool_call_id,
        op=record.op,
        rel_path=record.rel_path,
        ts=now,
    )


def _event_prune_stmt(folder_id: str):
    """Keep the newest :data:`MAX_EVENTS_PER_FOLDER` events of one folder."""
    event = FolderLedgerEventRow
    cutoff = select(event.id).where(event.folder_id == folder_id).order_by(event.id.desc()).offset(MAX_EVENTS_PER_FOLDER - 1).limit(1).scalar_subquery()
    return delete(event).where(event.folder_id == folder_id, event.id < cutoff)


def _dismissal_clear_stmt(folder_id: str):
    """New activity on a folder lets it be offered again, to everyone."""
    return delete(FolderLedgerDismissalRow).where(FolderLedgerDismissalRow.folder_id == folder_id)


def _removed_stmt(mount_path: str, name: str, now: datetime):
    """Retire the live row of an entry a recorded command removed.

    A later creation of the same name then starts a new row credited to the
    conversation that made it, instead of inheriting the old row's creator.
    """
    folder = FolderLedgerFolderRow
    return update(folder).where(folder.mount_path == mount_path, folder.name == name, folder.deleted_at.is_(None)).values(deleted_at=now)


def _record_statements(dialect_name: str, record: TouchRecord, now: datetime, execute: Callable[[Any], Any]) -> str:
    folder_id = execute(_folder_upsert_stmt(dialect_name, record, now)).scalar_one()
    execute(_touch_upsert_stmt(dialect_name, folder_id, record, now))
    execute(_event_insert_stmt(folder_id, record, now))
    execute(_event_prune_stmt(folder_id))
    execute(_dismissal_clear_stmt(folder_id))
    return folder_id


# ---------------------------------------------------------------------------
# Synchronous recorder store
# ---------------------------------------------------------------------------


class FolderLedgerRecorderStore:
    """Synchronous write path of the recorder middleware (worker threads only)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._Session = session_factory

    def record(self, records: Sequence[TouchRecord], removed: Sequence[tuple[str, str]] = ()) -> list[str]:
        """Record every touch, and retire every removed ``(mount_path, name)``, in one transaction.

        Returns the folder ids of the touches.
        """
        if not records and not removed:
            return []
        with self._Session() as session:
            dialect_name = session.get_bind().dialect.name
            now = _now()
            for mount_path, name in removed:
                session.execute(_removed_stmt(mount_path, name, now))
            folder_ids = [_record_statements(dialect_name, record, now, session.execute) for record in records]
            session.commit()
        return folder_ids


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


def _dependent_anchor(metadata: Any) -> str | None:
    """The thread a hidden dependent thread lives under, or None.

    Metadata is client-writable, so anything malformed reads as "this thread
    stands alone" (live as long as its own row exists).
    """
    if not isinstance(metadata, dict):
        return None
    if metadata.get(_EDIT_VERSION_FLAG_KEY) is True:
        anchor = metadata.get(_EDIT_ROOT_THREAD_ID_KEY)
    elif metadata.get(_SIDECAR_FLAG_KEY) is True:
        anchor = metadata.get(_SIDECAR_PARENT_THREAD_ID_KEY)
    else:
        return None
    return anchor if isinstance(anchor, str) and anchor and len(anchor) <= 64 else None


async def _live_threads_by_folder(session: AsyncSession, folder_ids: Sequence[str]) -> dict[str, set[str]]:
    """Map each folder id to the ids of the live threads that touch it."""
    touch = FolderLedgerTouchRow
    meta = ThreadMetaRow
    rows: list[tuple[str, str, Any]] = []
    for chunk in _chunks(list(dict.fromkeys(folder_ids))):
        result = await session.execute(select(touch.folder_id, touch.thread_id, meta.metadata_json).join(meta, meta.thread_id == touch.thread_id).where(touch.folder_id.in_(chunk), touch.thread_deleted_at.is_(None)))
        rows.extend((str(folder_id), str(thread_id), metadata) for folder_id, thread_id, metadata in result.all())
    anchors = {thread_id: _dependent_anchor(metadata) for _folder_id, thread_id, metadata in rows}
    wanted = sorted({anchor for anchor in anchors.values() if anchor is not None})
    existing: set[str] = set()
    for chunk in _chunks(wanted):
        existing.update(str(thread_id) for thread_id in (await session.execute(select(meta.thread_id).where(meta.thread_id.in_(chunk)))).scalars())
    live: dict[str, set[str]] = {}
    for folder_id, thread_id, _metadata in rows:
        anchor = anchors.get(thread_id)
        if anchor is not None and anchor not in existing:
            continue
        live.setdefault(folder_id, set()).add(thread_id)
    return live


def _folder_dict(row: FolderLedgerFolderRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "mount_path": row.mount_path,
        "name": row.name,
        "kind": row.kind,
        "created_by_user_id": row.created_by_user_id,
        "created_by_thread_id": row.created_by_thread_id,
        "created_attribution": row.created_attribution,
        "first_seen_at": row.first_seen_at,
        "last_touched_at": row.last_touched_at,
        "deleted_at": row.deleted_at,
        "host_root": row.host_root,
        "host_entry": row.host_entry,
    }


def _touch_dict(row: FolderLedgerTouchRow) -> dict[str, Any]:
    return {
        "folder_id": row.folder_id,
        "user_id": row.user_id,
        "thread_id": row.thread_id,
        "role": row.role,
        "inherited_from_thread_id": row.inherited_from_thread_id,
        "first_at": row.first_at,
        "last_at": row.last_at,
        "last_run_id": row.last_run_id,
        "writes": int(row.writes or 0),
        "edits": int(row.edits or 0),
        "shell_ops": int(row.shell_ops or 0),
        "thread_deleted_at": row.thread_deleted_at,
    }


_ROLE_RANK = {ROLE_CREATED: 3, ROLE_EDITED: 2, ROLE_INHERITED: 1}


def _merge_touches(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Two users' touches of one thread on one folder, as one (shared workspace)."""
    merged = dict(a)
    merged["role"] = max(a["role"], b["role"], key=lambda role: _ROLE_RANK.get(role, 0))
    for key in ("writes", "edits", "shell_ops"):
        merged[key] = a[key] + b[key]
    merged["first_at"] = min(a["first_at"], b["first_at"])
    merged["last_at"] = max(a["last_at"], b["last_at"])
    return merged


# ---------------------------------------------------------------------------
# Async Gateway repository
# ---------------------------------------------------------------------------


class FolderLedgerRepository:
    """The Gateway's async facade over the folder ledger tables.

    Methods take explicit ``user_id`` strings; the router resolves the caller
    once. A read whose ``user_id`` scopes touches takes None to mean every
    user's touches, the shared-workspace scope (multi-user mode off), where the
    router's owner check already lets every login open every conversation.
    Nothing here touches the filesystem.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record(self, records: Sequence[TouchRecord], removed: Sequence[tuple[str, str]] = ()) -> list[str]:
        """Async twin of :meth:`FolderLedgerRecorderStore.record`."""
        if not records and not removed:
            return []
        async with self._sf() as session:
            dialect_name = session.get_bind().dialect.name
            now = _now()
            for mount_path, name in removed:
                await session.execute(_removed_stmt(mount_path, name, now))
            folder_ids: list[str] = []
            for record in records:
                folder_id = (await session.execute(_folder_upsert_stmt(dialect_name, record, now))).scalar_one()
                await session.execute(_touch_upsert_stmt(dialect_name, folder_id, record, now))
                await session.execute(_event_insert_stmt(folder_id, record, now))
                await session.execute(_event_prune_stmt(folder_id))
                await session.execute(_dismissal_clear_stmt(folder_id))
                folder_ids.append(folder_id)
            await session.commit()
        return folder_ids

    # -- thread lifecycle ------------------------------------------------

    async def tombstone_thread(self, thread_id: str) -> int:
        """Mark every live touch of a deleted thread; returns the rows changed.

        Thread ids are unique across users, so every user's touch rows of the
        thread are tombstoned: the thread is gone for all of them.
        """
        touch = FolderLedgerTouchRow
        async with self._sf() as session:
            result = await session.execute(update(touch).where(touch.thread_id == thread_id, touch.thread_deleted_at.is_(None)).values(thread_deleted_at=_now()))
            await session.commit()
        return int(result.rowcount or 0)

    async def inherit_thread(self, *, parent_thread_id: str, child_thread_id: str, user_id: str) -> int:
        """Copy the parent's live touches onto a new branch as ``inherited``.

        A branch whose history includes the parent's writes keeps the folder in
        use. Errs toward keeping folders longer, never shorter. Returns the
        number of touches copied.
        """
        touch = FolderLedgerTouchRow
        folder = FolderLedgerFolderRow
        async with self._sf() as session:
            parents = (
                (
                    await session.execute(
                        select(touch)
                        .join(folder, folder.id == touch.folder_id)
                        .where(touch.thread_id == parent_thread_id, touch.thread_deleted_at.is_(None), folder.deleted_at.is_(None))
                        .order_by(touch.last_at.desc())
                        .limit(MAX_FOLDERS_PER_QUERY)
                    )
                )
                .scalars()
                .all()
            )
            if not parents:
                return 0
            insert = dialect_insert(session.get_bind().dialect.name, component="folder ledger")
            copied: dict[str, FolderLedgerTouchRow] = {}
            for parent in parents:
                copied.setdefault(parent.folder_id, parent)
            stmt = insert(touch).values(
                [
                    {
                        "folder_id": parent.folder_id,
                        "user_id": user_id,
                        "thread_id": child_thread_id,
                        "role": ROLE_INHERITED,
                        "inherited_from_thread_id": parent_thread_id,
                        "first_at": parent.first_at,
                        "last_at": parent.last_at,
                        "last_run_id": None,
                        "writes": 0,
                        "edits": 0,
                        "shell_ops": 0,
                    }
                    for parent in copied.values()
                ]
            )
            await session.execute(stmt.on_conflict_do_nothing(index_elements=[touch.folder_id, touch.user_id, touch.thread_id]))
            await session.commit()
        return len(copied)

    # -- reads -----------------------------------------------------------

    async def get_folder(self, folder_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(FolderLedgerFolderRow, folder_id)
            return _folder_dict(row) if row is not None else None

    async def user_can_view(self, *, folder_id: str, user_id: str | None) -> bool:
        """A user sees a folder they created or have any touch on (tombstoned included).

        ``user_id=None`` (shared workspace) sees every folder.
        """
        if user_id is None:
            return True
        touch = FolderLedgerTouchRow
        folder = FolderLedgerFolderRow
        async with self._sf() as session:
            creator = await session.scalar(select(folder.id).where(folder.id == folder_id, folder.created_by_user_id == user_id))
            if creator is not None:
                return True
            touched = await session.scalar(select(touch.folder_id).where(touch.folder_id == folder_id, touch.user_id == user_id).limit(1))
            return touched is not None

    async def live_thread_ids(self, folder_id: str) -> set[str]:
        async with self._sf() as session:
            return (await _live_threads_by_folder(session, [folder_id])).get(folder_id, set())

    async def list_thread_folders(self, *, thread_id: str, user_id: str | None) -> list[dict[str, Any]]:
        """Folders one thread created, edited or inherited, newest touch first.

        Each entry carries the folder, this thread's touch, and
        ``other_live_threads``: how many other live conversations (of any
        user) also touch the folder. With ``user_id=None`` (shared workspace)
        every user's touches of the thread count, merged into one per folder.
        """
        touch = FolderLedgerTouchRow
        folder = FolderLedgerFolderRow
        conditions = [touch.thread_id == thread_id, folder.deleted_at.is_(None)]
        if user_id is not None:
            conditions.append(touch.user_id == user_id)
        query = select(touch, folder).join(folder, folder.id == touch.folder_id).where(*conditions).order_by(touch.last_at.desc(), folder.name)
        if user_id is not None:
            query = query.limit(MAX_FOLDERS_PER_QUERY)  # one touch per folder
        async with self._sf() as session:
            rows = (await session.execute(query)).all()
            merged: dict[str, tuple[dict[str, Any], FolderLedgerFolderRow]] = {}
            for touch_row, folder_row in rows:
                current = merged.get(folder_row.id)
                merged[folder_row.id] = (_touch_dict(touch_row) if current is None else _merge_touches(current[0], _touch_dict(touch_row)), folder_row)
            selected = list(merged.values())[:MAX_FOLDERS_PER_QUERY]
            live = await _live_threads_by_folder(session, [folder_row.id for _touch, folder_row in selected])
        entries = []
        for touch_entry, folder_row in selected:
            others = live.get(folder_row.id, set()) - {thread_id}
            entries.append({"folder": _folder_dict(folder_row), "touch": touch_entry, "other_live_threads": len(others)})
        return entries

    async def folder_detail(self, *, folder_id: str, event_limit: int = MAX_EVENTS_PER_FOLDER) -> dict[str, Any] | None:
        """Folder, every touch with its liveness and the caller-agnostic edit log.

        Visibility and redaction are the router's job; this returns raw ids.
        """
        touch = FolderLedgerTouchRow
        event = FolderLedgerEventRow
        meta = ThreadMetaRow
        async with self._sf() as session:
            folder_row = await session.get(FolderLedgerFolderRow, folder_id)
            if folder_row is None:
                return None
            touch_rows = (
                await session.execute(select(touch, meta.display_name, meta.user_id).outerjoin(meta, meta.thread_id == touch.thread_id).where(touch.folder_id == folder_id).order_by(touch.last_at.desc()).limit(MAX_FOLDERS_PER_QUERY))
            ).all()
            event_rows = (await session.execute(select(event).where(event.folder_id == folder_id).order_by(event.id.desc()).limit(max(1, min(event_limit, MAX_EVENTS_PER_FOLDER))))).scalars().all()
            live = (await _live_threads_by_folder(session, [folder_id])).get(folder_id, set())
        touches = []
        for touch_row, display_name, owner_id in touch_rows:
            entry = _touch_dict(touch_row)
            entry["display_name"] = display_name
            entry["thread_owner_id"] = owner_id
            entry["live"] = touch_row.thread_id in live
            touches.append(entry)
        events = [
            {
                "thread_id": row.thread_id,
                "user_id": row.user_id,
                "run_id": row.run_id,
                "op": row.op,
                "rel_path": row.rel_path,
                "ts": row.ts,
            }
            for row in event_rows
        ]
        return {"folder": _folder_dict(folder_row), "touches": touches, "events": events, "live_thread_ids": live}

    async def find_orphans(self, *, thread_ids: Sequence[str], user_id: str | None, viewer_id: str | None = None) -> list[dict[str, Any]]:
        """Folders the caller's given threads touched that no live conversation uses.

        Only the caller's own touches select candidates (``user_id``; None in a
        shared workspace selects every user's), so ids of other users' threads
        are ignored. Deleted folders, and folders ``viewer_id`` (default
        ``user_id``) dismissed, are skipped. The live-touch check then counts
        every user's conversations: mounts are shared, and a per-user "last
        conversation" would offer to delete another user's working folder.
        Liveness is checked on every candidate before the answer is capped, so
        live folders never crowd an orphan out of it.
        """
        ids = [thread_id for thread_id in dict.fromkeys(thread_ids) if isinstance(thread_id, str) and thread_id]
        if not ids:
            return []
        viewer = viewer_id if viewer_id is not None else user_id
        touch = FolderLedgerTouchRow
        folder = FolderLedgerFolderRow
        dismissal = FolderLedgerDismissalRow
        async with self._sf() as session:
            candidates: dict[str, FolderLedgerFolderRow] = {}
            for chunk in _chunks(ids):
                conditions = [touch.thread_id.in_(chunk), folder.deleted_at.is_(None)]
                if user_id is not None:
                    conditions.append(touch.user_id == user_id)
                if viewer is not None:
                    conditions.append(~exists().where(dismissal.folder_id == folder.id, dismissal.user_id == viewer))
                rows = (await session.execute(select(folder).join(touch, touch.folder_id == folder.id).where(*conditions))).scalars().unique().all()
                for row in rows:
                    candidates.setdefault(row.id, row)
            if not candidates:
                return []
            live = await _live_threads_by_folder(session, list(candidates))
            orphan_rows = sorted((row for row in candidates.values() if not live.get(row.id)), key=lambda row: (row.last_touched_at, row.id), reverse=True)[:MAX_FOLDERS_PER_QUERY]
            totals: dict[str, tuple[int, int, Any]] = {}
            for chunk in _chunks([row.id for row in orphan_rows]):
                result = await session.execute(select(touch.folder_id, func.coalesce(func.sum(touch.writes), 0), func.coalesce(func.sum(touch.edits), 0), func.max(touch.last_at)).where(touch.folder_id.in_(chunk)).group_by(touch.folder_id))
                for folder_id, writes, edits, last_at in result.all():
                    totals[str(folder_id)] = (int(writes or 0), int(edits or 0), last_at)
        orphans = []
        for row in orphan_rows:
            writes, edits, last_at = totals.get(row.id, (0, 0, None))
            entry = _folder_dict(row)
            entry.update({"writes": writes, "edits": edits, "last_at": last_at or row.last_touched_at})
            orphans.append(entry)
        return orphans

    # -- folder state ----------------------------------------------------

    async def mark_deleted(self, folder_id: str) -> bool:
        folder = FolderLedgerFolderRow
        async with self._sf() as session:
            result = await session.execute(update(folder).where(folder.id == folder_id, folder.deleted_at.is_(None)).values(deleted_at=_now()))
            await session.commit()
        return bool(result.rowcount)

    async def mark_dismissed(self, folder_id: str, *, user_id: str) -> bool:
        """Stop offering a live folder's deletion to one user, until new activity on it."""
        folder = FolderLedgerFolderRow
        dismissal = FolderLedgerDismissalRow
        async with self._sf() as session:
            live = await session.scalar(select(folder.id).where(folder.id == folder_id, folder.deleted_at.is_(None)))
            if live is None:
                return False
            insert = dialect_insert(session.get_bind().dialect.name, component="folder ledger")
            stmt = insert(dismissal).values(folder_id=folder_id, user_id=user_id, dismissed_at=_now())
            await session.execute(stmt.on_conflict_do_update(index_elements=[dismissal.folder_id, dismissal.user_id], set_={"dismissed_at": stmt.excluded.dismissed_at}))
            await session.commit()
        return True
