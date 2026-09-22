"""Rejoin the fork's merge head with upstream's MCP task-lease branch.

Revision ID: 0027_merge_preferences_mcp_tasks
Revises: 0024_merge_preferences, 0026_mcp_task_lease_tokens
Create Date: 2026-09-22

The third instance of the shape ``0023_merge_pricing_scheduler`` first named.
``0024_merge_preferences`` joined the fork's pricing branch to upstream's
``0023_user_preferences``. Upstream then extended that *same* parent again --
``0024_project_documents`` -> ``0025_repair_run_change_seq`` ->
``0026_mcp_task_lease_tokens`` -- so ``0023_user_preferences`` has two children
and the tree has two heads once more. ``alembic upgrade head`` refuses to run
against more than one, and the Gateway's schema bootstrap fails before a single
request is served (``_get_head_revision`` calls
``ScriptDirectory.get_current_head``, which raises on multiple heads).

The fix is another no-op merge point, not a re-parenting. Rewriting
``0024_project_documents``'s ``down_revision`` onto the fork's merge head would
leave every database already stamped at one branch's tip reading as though it
were *at head* with the other branch's DDL never applied -- a wrong schema that
stays silent until a query hits the missing table. Here both branches keep their
applied history and arrive at the same place from either order.

There is no schema change here: a merge revision exists to join the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0027_merge_preferences_mcp_tasks"
down_revision: str | Sequence[str] | None = ("0024_merge_preferences", "0026_mcp_task_lease_tokens")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
