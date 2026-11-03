"""Rejoin the fork's merge head with upstream's run-input branch.

Revision ID: 0052_merge_prefs_run_inputs
Revises: 0049_merge_prefs_ext_leases, 0051_merge_run_inputs_fencing
Create Date: 2026-11-03

The ninth instance of the shape ``0023_merge_pricing_scheduler`` first named.
``0049_merge_prefs_ext_leases`` joined the fork's merge head to upstream's
``0048_extension_execution_leases``. Upstream then extended that *same* parent
again — ``0049_run_inputs`` and ``0049_run_producer_fencing``, later joined by
``0051_merge_run_inputs_fencing`` — so the tree has two heads once more.
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
revision: str = "0052_merge_prefs_run_inputs"
down_revision: str | Sequence[str] | None = ("0049_merge_prefs_ext_leases", "0051_merge_run_inputs_fencing")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
