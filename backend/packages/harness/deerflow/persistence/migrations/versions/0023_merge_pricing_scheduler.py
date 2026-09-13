"""Rejoin the fork's merge head with upstream's post-acceptance chain.

Revision ID: 0023_merge_pricing_scheduler
Revises: 0022_merge_pricing_projects, 0022_scheduled_occurrence_seq
Create Date: 2026-09-12

``0022_merge_pricing_projects`` joined the fork's ``0019_runs_pricing_snapshot``
to upstream's ``0021_batch_acceptance``. Upstream then extended that same parent
with ``0019_thread_incarnations`` → ``0022_scheduled_occurrence_seq``, so
``0021_batch_acceptance`` now has two children and the tree has two heads again.
``upgrade head`` refuses to run against more than one, and the Gateway's schema
bootstrap fails outright before any request is served (``_get_head_revision``
calls ``ScriptDirectory.get_current_head``, which raises on multiple heads).

The fix is another no-op merge point, not a re-parenting — the same reasoning as
``0022_merge_pricing_projects`` documents, and the rule the migrations guide
states: rewriting ``0019_thread_incarnations``'s ``down_revision`` onto the
fork's merge head would leave every database already stamped at one branch's tip
reading as though it were at head with the other branch's DDL never applied.
Here both branches keep their applied history: a fork database stamped at
``0022_merge_pricing_projects`` walks ``0019_thread_incarnations`` →
``0022_scheduled_occurrence_seq`` and arrives here, and a fresh database reaches
the same place by the other order.

Expect this shape on every sync where upstream extends a revision the fork has
already merged: the answer is a new merge revision, never a re-parent.

There is no schema change here: a merge revision exists to join the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0023_merge_pricing_scheduler"
down_revision: str | Sequence[str] | None = ("0022_merge_pricing_projects", "0022_scheduled_occurrence_seq")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
