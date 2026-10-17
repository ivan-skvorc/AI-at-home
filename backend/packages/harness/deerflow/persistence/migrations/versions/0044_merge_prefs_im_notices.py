"""Rejoin the fork's merge head with upstream's 0038..0043 branch.

Revision ID: 0044_merge_prefs_im_notices
Revises: 0038_merge_prefs_summaries, 0043_runtime_im_notices
Create Date: 2026-10-17

The sixth instance of the shape ``0023_merge_pricing_scheduler`` first named.
``0038_merge_prefs_summaries`` joined the fork's merge head to upstream's
``0037_project_document_summaries``. Upstream then extended that *same* parent
again -- ``0038_channel_thread_bindings`` -> ... -> ``0043_runtime_im_notices``
-- so ``0037_project_document_summaries`` has two children and the tree has two
heads once more. ``alembic upgrade head`` refuses to run against more than one,
and the Gateway's schema bootstrap fails before a single request is served.

The fix is another no-op merge point, not a re-parenting: see
``0031_merge_prefs_notifications`` for why. The id stays within Postgres's
``VARCHAR(32)`` version column.

There is no schema change here: a merge revision exists to join the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0044_merge_prefs_im_notices"
down_revision: str | Sequence[str] | None = ("0038_merge_prefs_summaries", "0043_runtime_im_notices")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
