"""Add ``runs.pricing_snapshot`` column.

Revision ID: 0019_runs_pricing_snapshot
Revises: 0018_oauth_identity_pg_partial
Create Date: 2026-09-05

Cost was recomputed from the live ``config.yaml`` on every read, so a run's
reported spend was a statement about today's roster rather than about what the
run actually cost. Two ways that goes wrong, both silent: re-pricing a model
rewrote every historical total, and a model the roster rolled forward past
stopped resolving in ``lookup_pricing`` and took its spend to zero. This column
stores the prices that were in effect when the run finished.

Schema parity with ``Base.metadata``
------------------------------------

Declared on the ORM as ``Mapped[dict] = mapped_column(JSON, default=dict,
server_default=text("'{}'"))`` -- non-Optional, so SQLAlchemy infers
``nullable=False`` and ``create_all`` produces ``pricing_snapshot JSON NOT NULL
DEFAULT '{}'`` on a fresh database. This migration matches that exactly, so a
legacy-upgraded database stays schema-identical to a fresh one. The server
default is also what lets ``ADD COLUMN ... NOT NULL`` succeed on a populated
``runs`` table: existing rows take ``'{}'`` at ALTER time rather than violating
the constraint.

Existing rows are deliberately **not** backfilled. An empty snapshot means "no
price was recorded for this run", which the read path answers by falling back to
the live config -- exactly the old behaviour. Writing today's prices onto runs
that predate the column would be the opposite: it would assert, with false
confidence, that those runs were billed at rates nobody has checked.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

# revision identifiers, used by Alembic.
revision: str = "0019_runs_pricing_snapshot"
down_revision: str | Sequence[str] | None = "0018_oauth_identity_pg_partial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column(
        "runs",
        sa.Column(
            "pricing_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    safe_drop_column("runs", "pricing_snapshot")
