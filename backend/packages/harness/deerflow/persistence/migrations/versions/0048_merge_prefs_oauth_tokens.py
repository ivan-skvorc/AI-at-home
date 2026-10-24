"""Rejoin the fork's merge head with upstream's 0044..0047 branch.

Revision ID: 0048_merge_prefs_oauth_tokens
Revises: 0044_merge_prefs_im_notices, 0047_mcp_oauth_tokens
Create Date: 2026-10-22

The seventh instance of the shape ``0023_merge_pricing_scheduler`` first named.
``0044_merge_prefs_im_notices`` joined the fork's merge head to upstream's
``0043_runtime_im_notices``. Upstream then extended that *same* parent again --
``0044_channel_runtime_configs`` -> ... -> ``0047_mcp_oauth_tokens`` -- so
``0043_runtime_im_notices`` has two children and the tree has two heads once
more. ``alembic upgrade head`` refuses to run against more than one, and the
Gateway's schema bootstrap fails before a single request is served.

The fix is another no-op merge point, not a re-parenting: see
``0031_merge_prefs_notifications`` for why. The id stays within Postgres's
``VARCHAR(32)`` version column.

There is no schema change here: a merge revision exists to join the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0048_merge_prefs_oauth_tokens"
down_revision: str | Sequence[str] | None = ("0044_merge_prefs_im_notices", "0047_mcp_oauth_tokens")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: this revision only joins two independent branches."""


def downgrade() -> None:
    """No-op: splitting the branches again needs no schema change."""
