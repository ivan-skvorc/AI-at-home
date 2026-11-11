"""Rejoin the fork's merge head with upstream's batch-continuation revision.

Revision ID: 0053_merge_prefs_batch_cont
Revises: 0052_merge_prefs_run_inputs, 0052_batch_continuation
Create Date: 2026-11-10

The tenth instance of the shape ``0023_merge_pricing_scheduler`` first named.
``0052_merge_prefs_run_inputs`` joined the fork's merge head to upstream's
``0051_merge_run_inputs_fencing``. Upstream then extended that *same* parent
with ``0052_batch_continuation``, so the tree has two heads once more.
``alembic upgrade head`` refuses to run against more than one, and the
Gateway's schema bootstrap fails before a single request is served.

The fix is another no-op merge point, not a re-parenting: see
``0031_merge_prefs_notifications`` for why. The id stays within Postgres's
``VARCHAR(32)`` version column.

There is no schema change here: a merge revision exists to join the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0053_merge_prefs_batch_cont"
down_revision: str | Sequence[str] | None = ("0052_merge_prefs_run_inputs", "0052_batch_continuation")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
