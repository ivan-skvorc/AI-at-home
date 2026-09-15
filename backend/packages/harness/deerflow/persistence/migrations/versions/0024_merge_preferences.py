"""Rejoin the fork's merge head with upstream's account-preferences revision.

Revision ID: 0024_merge_preferences
Revises: 0023_merge_pricing_scheduler, 0023_user_preferences
Create Date: 2026-09-14

``0023_merge_pricing_scheduler`` joined the fork's pricing branch to upstream's
``0022_scheduled_occurrence_seq``. Upstream then extended that same parent with
``0023_user_preferences``, so ``0022_scheduled_occurrence_seq`` has two children
and the tree has two heads again — exactly the shape
``0023_merge_pricing_scheduler`` predicted for "every sync where upstream extends
a revision the fork has already merged". ``upgrade head`` refuses to run against
more than one head, and the Gateway's schema bootstrap fails outright before any
request is served (``_get_head_revision`` calls
``ScriptDirectory.get_current_head``, which raises on multiple heads).

The fix is another no-op merge point, not a re-parenting: rewriting
``0023_user_preferences``'s ``down_revision`` onto the fork's merge head would
leave every database already stamped at one branch's tip reading as though it
were at head with the other branch's DDL never applied — a wrong schema that
stays silent until a query hits the missing table. Here both branches keep their
applied history and arrive at the same place from either order.

There is no schema change here: a merge revision exists to join the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0024_merge_preferences"
down_revision: str | Sequence[str] | None = ("0023_merge_pricing_scheduler", "0023_user_preferences")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
