"""ORM models for the folder ledger: which conversations created or edited a shared folder.

A *folder* is one top-level entry (directory or bare file) of a writable custom
``sandbox.mounts`` entry, for example ``/mnt/projects/acme``. Those mounts are
shared by every conversation and every user, and survive a thread's deletion,
so a deployment-wide ledger records who wrote there:

- ``folder_ledger_folders`` holds one row per live folder. Deleting the folder
  through the ledger sets ``deleted_at``; recreating the same name later starts
  a new row (the partial unique index only covers live rows).
- ``folder_ledger_touches`` holds one row per (folder, user, thread). A thread's
  deletion sets ``thread_deleted_at`` instead of dropping the row, so the
  record of who worked on the folder outlives the conversation.
- ``folder_ledger_events`` is the capped edit log, newest kept.
- ``folder_ledger_dismissals`` holds one row per (folder, user) who chose to
  keep the folder and stop being offered its deletion. Dismissal is per user:
  one user's "don't ask again" never hides the offer from the folder's creator.
  New activity on the folder clears every dismissal of it.

A folder row is bound to the host entry it describes: ``host_root`` is the
mount's host directory and ``host_entry`` the entry's ``st_dev:st_ino`` as the
recorder saw them. The confined delete refuses an entry that no longer matches,
so a repointed mount or a folder recreated outside the ledger is never removed
on the strength of an older row.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: Live-row predicate of the partial unique index on (mount_path, name). The
#: repository's upsert names the same predicate as its conflict target.
LIVE_FOLDER_PREDICATE = "deleted_at IS NULL"


def _now() -> datetime:
    return datetime.now(UTC)


class FolderLedgerFolderRow(Base):
    __tablename__ = "folder_ledger_folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Normalized container_path of the mount, e.g. "/mnt/projects".
    mount_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # One path segment below the mount root.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # "dir" or "file" (a bare file at the mount root).
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # "observed_create" | "preexisting" | "inferred_shell"
    created_attribution: Mapped[str] = mapped_column(String(16), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    last_touched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Normalized host directory of the mount when the entry was recorded.
    host_root: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # "st_dev:st_ino" of the entry the ledger last saw a conversation create or
    # change; None when the Gateway could not see it.
    host_entry: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        # One live row per (mount, name). Both dialect predicates are set: a
        # single one builds a FULL unique index on the other dialect (see
        # persistence/user/model.py), which would forbid recreating a name
        # after a ledger delete.
        Index(
            "uq_folder_ledger_folders_live",
            "mount_path",
            "name",
            unique=True,
            sqlite_where=text(LIVE_FOLDER_PREDICATE),
            postgresql_where=text(LIVE_FOLDER_PREDICATE),
        ),
        Index("ix_folder_ledger_folders_creator", "created_by_user_id"),
    )


class FolderLedgerTouchRow(Base):
    __tablename__ = "folder_ledger_touches"

    folder_id: Mapped[str] = mapped_column(String(32), ForeignKey("folder_ledger_folders.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # "created" | "edited" | "inherited"
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    inherited_from_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    writes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    edits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    shell_ops: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    # Set when the thread is deleted: the row stays as the record of who
    # worked on the folder, but no longer keeps the folder in use.
    thread_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("folder_id", "user_id", "thread_id", name="pk_folder_ledger_touches"),
        Index("ix_folder_ledger_touches_thread", "thread_id"),
        Index("ix_folder_ledger_touches_user_thread", "user_id", "thread_id"),
    )


class FolderLedgerEventRow(Base):
    __tablename__ = "folder_ledger_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_id: Mapped[str] = mapped_column(String(32), ForeignKey("folder_ledger_folders.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # "write" | "append" | "edit" | "shell"
    op: Mapped[str] = mapped_column(String(8), nullable=False)
    # Path relative to the mount root, starting with the folder name.
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (Index("ix_folder_ledger_events_folder", "folder_id", "id"),)


class FolderLedgerDismissalRow(Base):
    __tablename__ = "folder_ledger_dismissals"

    folder_id: Mapped[str] = mapped_column(String(32), ForeignKey("folder_ledger_folders.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (PrimaryKeyConstraint("folder_id", "user_id", name="pk_folder_ledger_dismissals"),)
