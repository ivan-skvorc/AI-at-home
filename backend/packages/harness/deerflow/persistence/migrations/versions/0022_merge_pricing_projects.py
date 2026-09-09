"""Merge the fork's pricing-snapshot branch with upstream's projects branch.

Revision ID: 0022_merge_pricing_projects
Revises: 0019_runs_pricing_snapshot, 0021_batch_acceptance
Create Date: 2026-09-09

Two revisions independently claimed ``0018_oauth_identity_pg_partial`` as their
parent: the fork's ``0019_runs_pricing_snapshot`` (FORK.md §17, added here) and
upstream's ``0019_projects`` (which ``0020_threads_meta_project_id`` and
``0021_batch_acceptance`` extend). Merging the two histories left Alembic with
two heads, and ``upgrade head`` refuses to run against more than one — the
Gateway's schema bootstrap fails outright, before any request is served.

This is a no-op merge point rather than a re-parenting of either branch, and
that distinction is the whole reason it exists. A fork database is already
stamped at ``0019_runs_pricing_snapshot``; rewriting that revision's
``down_revision`` to sit after upstream's chain would leave such a database
believing it is at head while ``projects``, ``threads_meta.project_id``, and the
batch-acceptance columns were never created — a schema that is wrong in silence,
and only fails later at query time. With the merge point, that same database
walks the upstream branch it skipped (``0019_projects`` → ``0020`` → ``0021``)
and arrives here, and a fresh database reaches the same place by the other
order. Neither branch's applied history is rewritten.

There is no schema change here: a merge revision exists to join the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0022_merge_pricing_projects"
down_revision: str | Sequence[str] | None = ("0019_runs_pricing_snapshot", "0021_batch_acceptance")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
