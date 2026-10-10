"""Rejoin the fork's merge head with upstream's 0031..0037 branch.

Revision ID: 0038_merge_prefs_summaries
Revises: 0031_merge_prefs_notifications, 0037_project_document_summaries
Create Date: 2026-10-10

The fifth instance of the shape ``0023_merge_pricing_scheduler`` first named.
``0031_merge_prefs_notifications`` joined the fork's merge head to upstream's
``0030_notification_claim_tokens``. Upstream then extended that *same* parent
again -- ``0031_scheduled_streak_boundary`` -> ... ->
``0037_project_document_summaries`` -- so ``0030_notification_claim_tokens``
has two children and the tree has two heads once more. ``alembic upgrade head``
refuses to run against more than one, and the Gateway's schema bootstrap fails
before a single request is served.

The fix is another no-op merge point, not a re-parenting: see
``0031_merge_prefs_notifications`` for why. The id stays within Postgres's
``VARCHAR(32)`` version column.

There is no schema change here: a merge revision exists to join the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0038_merge_prefs_summaries"
down_revision: str | Sequence[str] | None = ("0031_merge_prefs_notifications", "0037_project_document_summaries")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
