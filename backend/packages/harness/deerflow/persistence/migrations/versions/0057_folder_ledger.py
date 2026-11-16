"""Add the folder ledger: which conversations created or edited shared mount folders.

Revision ID: 0057_folder_ledger
Revises: 0056_merge_prefs_thread_shares
Create Date: 2026-11-16

A fork revision (FORK_NOTES.md). It chains onto the fork's merge head, so the
next upstream sync that adds a revision joins this tip with another no-op merge
point instead of re-parenting either branch. Three new tables, no change to an
existing one; an older binary sharing the database never reads them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057_folder_ledger"
down_revision: str | Sequence[str] | None = "0056_merge_prefs_thread_shares"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = sa.text("deleted_at IS NULL")


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("folder_ledger_folders"):
        op.create_table(
            "folder_ledger_folders",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("mount_path", sa.String(512), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(8), nullable=False),
            sa.Column("created_by_user_id", sa.String(64), nullable=True),
            sa.Column("created_by_thread_id", sa.String(64), nullable=True),
            sa.Column("created_attribution", sa.String(16), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_touched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        )
        # Both predicates: one alone builds a full unique index on the other
        # dialect, which would forbid recreating a name after a ledger delete.
        op.create_index("uq_folder_ledger_folders_live", "folder_ledger_folders", ["mount_path", "name"], unique=True, sqlite_where=_LIVE, postgresql_where=_LIVE)
        op.create_index("ix_folder_ledger_folders_creator", "folder_ledger_folders", ["created_by_user_id"])
    if not _has_table("folder_ledger_touches"):
        op.create_table(
            "folder_ledger_touches",
            sa.Column("folder_id", sa.String(32), sa.ForeignKey("folder_ledger_folders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("inherited_from_thread_id", sa.String(64), nullable=True),
            sa.Column("first_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_run_id", sa.String(64), nullable=True),
            sa.Column("writes", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("edits", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("shell_ops", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("thread_deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("folder_id", "user_id", "thread_id", name="pk_folder_ledger_touches"),
        )
        op.create_index("ix_folder_ledger_touches_thread", "folder_ledger_touches", ["thread_id"])
        op.create_index("ix_folder_ledger_touches_user_thread", "folder_ledger_touches", ["user_id", "thread_id"])
    if not _has_table("folder_ledger_events"):
        op.create_table(
            "folder_ledger_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("folder_id", sa.String(32), sa.ForeignKey("folder_ledger_folders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=True),
            sa.Column("tool_call_id", sa.String(128), nullable=True),
            sa.Column("op", sa.String(8), nullable=False),
            sa.Column("rel_path", sa.String(1024), nullable=False),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_folder_ledger_events_folder", "folder_ledger_events", ["folder_id", "id"])


def downgrade() -> None:
    for table in ("folder_ledger_events", "folder_ledger_touches", "folder_ledger_folders"):
        if _has_table(table):
            op.drop_table(table)
