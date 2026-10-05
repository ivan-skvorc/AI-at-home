"""Migration tests for 0026_mcp_task_lease_tokens.

Adds the nullable per-claim token columns ``McpTaskRepository`` uses to fence
poll, cancel, and notification mutations to the exact claim generation. The
chain-head pin moved on to ``test_migration_0027_0028_notification_outbox``.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap

pytestmark = pytest.mark.asyncio

REVISION = "0026_mcp_task_lease_tokens"
PREVIOUS = "0025_repair_run_change_seq"
TOKEN_COLUMNS = {"lease_token", "notification_lease_token"}


<<<<<<< HEAD
async def test_0026_is_reachable_from_the_chain_head():
    """Upstream ships this as the head; in the fork a merge point sits above it.

    This fork carries its own migration branch (`0019_runs_pricing_snapshot`,
    FORK.md §17), so every sync that extends a revision the fork already merged
    needs another no-op merge revision to rejoin the two. Asserting an exact
    head here would therefore fail on every future sync and say nothing about
    this revision. What must stay true is that the head still reaches it — a
    merge point that stopped naming a branch would skip this DDL silently.
    """
    head = bootstrap._get_head_revision()
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    reachable = {revision.revision for revision in script.iterate_revisions(head, "base")}
    assert REVISION in reachable, f"{REVISION} is not an ancestor of head {head!r}"
=======
async def test_0026_chains_into_the_single_head():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    # Later migrations may advance the head without removing this revision.
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
>>>>>>> upstream/main


async def test_0026_adds_nullable_claim_tokens_and_downgrades(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lease-tokens.db'}")
    cfg = bootstrap._get_alembic_config(engine)

    async def token_columns() -> dict[str, bool]:
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: sa.inspect(sync).get_columns("mcp_tasks"))
        return {column["name"]: column["nullable"] for column in columns if column["name"] in TOKEN_COLUMNS}

    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, PREVIOUS)
        assert await token_columns() == {}

        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        # Nullable so rows written before this revision stay valid.
        assert await token_columns() == dict.fromkeys(TOKEN_COLUMNS, True)

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert await token_columns() == {}
    finally:
        await engine.dispose()
