"""Migration 0057: the folder-ledger tables match the ORM and round-trip cleanly.

Upgrading an existing install keeps its conversations, the three new tables
match ``Base.metadata`` (including the live-only partial unique index on both
dialects), and downgrade/upgrade round-trips.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.folder_ledger.model import FolderLedgerFolderRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.thread_meta.model import ThreadMetaRow

REVISION = "0057_folder_ledger"
PREVIOUS = "0056_merge_prefs_thread_shares"
TABLES = {"folder_ledger_folders", "folder_ledger_touches", "folder_ledger_events"}


def _folder_insert(letter: str, now: datetime, *, deleted_at: datetime | None):
    return FolderLedgerFolderRow.__table__.insert().values(
        id=letter * 32,
        mount_path="/mnt/p",
        name="acme",
        kind="dir",
        created_attribution="observed_create",
        first_seen_at=now,
        last_touched_at=now,
        deleted_at=deleted_at,
    )


def test_0057_chains_onto_the_fork_merge_head():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(REVISION) <= 32


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_folder_ledger_upgrade_downgrade_and_schema(tmp_path, backend):
    schema = None
    if backend == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "folder_ledger_migration_" + uuid.uuid4().hex
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    config = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, config, PREVIOUS)
        async with engine.begin() as conn:
            now = datetime.now(UTC)
            await conn.execute(ThreadMetaRow.__table__.insert().values(thread_id="existing", user_id="alice", display_name="Existing conversation", status="idle", metadata_json={}, created_at=now, updated_at=now))
        await asyncio.to_thread(command.upgrade, config, REVISION)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT display_name FROM threads_meta WHERE thread_id='existing'"))).scalar_one() == "Existing conversation"

            def schema_diff(sync):
                context = MigrationContext.configure(sync, opts={"compare_type": True, "include_object": lambda obj, name, type_, reflected, compare_to: type_ != "table" or name in TABLES})
                return compare_metadata(context, Base.metadata)

            assert await conn.run_sync(schema_diff) == []

        # The live-only unique index lets a ledger-deleted name be recreated,
        # and still refuses two live rows for one (mount, name).
        async with engine.begin() as conn:
            await conn.execute(_folder_insert("a", now, deleted_at=now))
            await conn.execute(_folder_insert("b", now, deleted_at=None))
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(_folder_insert("c", now, deleted_at=None))

        await asyncio.to_thread(command.downgrade, config, PREVIOUS)
        async with engine.connect() as conn:

            def tables(sync):
                from sqlalchemy import inspect

                return set(inspect(sync).get_table_names())

            assert not (await conn.run_sync(tables)) & TABLES
        await asyncio.to_thread(command.upgrade, config, REVISION)
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
