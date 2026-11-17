"""Folder ledger repository: upserts, tombstones, inheritance and the orphan query.

Runs on SQLite, and on PostgreSQL with ``TEST_POSTGRES_URI`` (the upserts are
dialect ``ON CONFLICT`` statements against a partial unique index).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from support.postgres import asyncpg_test_url

from deerflow.persistence.base import Base
from deerflow.persistence.folder_ledger import FolderLedgerDismissalRow, FolderLedgerEventRow, FolderLedgerFolderRow, FolderLedgerRecorderStore, FolderLedgerRepository, FolderLedgerTouchRow, TouchRecord
from deerflow.persistence.folder_ledger.sql import MAX_EVENTS_PER_FOLDER, MAX_FOLDERS_PER_QUERY
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.thread_meta.model import ThreadMetaRow

ALICE = "alice"
BOB = "bob"
_TABLES = [ThreadMetaRow, FolderLedgerFolderRow, FolderLedgerTouchRow, FolderLedgerEventRow, FolderLedgerDismissalRow]
pytestmark = pytest.mark.asyncio


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request):
    return request.param


@asynccontextmanager
async def database(tmp_path, backend):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres upsert path)")
        schema = f"folder_ledger_{uuid.uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    try:
        async with engine.begin() as conn:
            if schema:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[model.__table__ for model in _TABLES]))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        yield sf, FolderLedgerRepository(sf)
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def put_thread(sf, thread_id, user_id=ALICE, metadata=None):
    now = datetime.now(UTC)
    async with sf() as session:
        await session.execute(ThreadMetaRow.__table__.insert().values(thread_id=thread_id, user_id=user_id, status="idle", metadata_json=metadata or {}, created_at=now, updated_at=now))
        await session.commit()


async def drop_thread(sf, thread_id):
    async with sf() as session:
        await session.execute(delete(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id))
        await session.commit()


def touch(thread_id, *, user_id=ALICE, name="acme", created=False, op="write", mount="/mnt/projects", rel=None, **binding):
    return TouchRecord(mount_path=mount, name=name, kind="dir", rel_path=rel or f"{name}/file.txt", op=op, created=created, user_id=user_id, thread_id=thread_id, run_id="run-1", **binding)


async def rows(sf, model, *where):
    async with sf() as session:
        return (await session.execute(select(model).where(*where))).scalars().all()


async def test_two_first_writers_share_one_folder_and_the_first_commit_is_the_creator(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        first = await repo.record([touch("thread-a", created=True)])
        second = await repo.record([touch("thread-b", user_id=BOB, created=True)])

        assert first == second
        (folder,) = await rows(sf, FolderLedgerFolderRow)
        assert (folder.created_by_thread_id, folder.created_by_user_id, folder.created_attribution) == ("thread-a", ALICE, "observed_create")
        touches = {row.thread_id: row.role for row in await rows(sf, FolderLedgerTouchRow)}
        assert touches == {"thread-a": "created", "thread-b": "created"}


async def test_concurrent_first_writers_land_without_an_integrity_error(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        ids = await asyncio.gather(*(repo.record([touch(f"thread-{n}", created=True)]) for n in range(5)))

        assert len({tuple(folder_ids) for folder_ids in ids}) == 1
        assert len(await rows(sf, FolderLedgerFolderRow)) == 1
        assert len(await rows(sf, FolderLedgerTouchRow)) == 5


async def test_counters_add_up_and_the_strongest_role_wins(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        await repo.record([touch("thread-a"), touch("thread-a", op="edit"), touch("thread-a", op="append"), touch("thread-a", op="shell")])
        await repo.record([touch("thread-a", created=True)])

        (row,) = await rows(sf, FolderLedgerTouchRow)
        assert (row.writes, row.edits, row.shell_ops, row.role) == (3, 1, 1, "created")


async def test_a_preexisting_folder_seen_recreated_gains_its_creator(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        await repo.record([touch("thread-a")])
        await repo.record([touch("thread-b", user_id=BOB, created=True)])

        (folder,) = await rows(sf, FolderLedgerFolderRow)
        assert (folder.created_attribution, folder.created_by_thread_id) == ("observed_create", "thread-b")


async def test_a_ledger_deleted_name_starts_a_new_row(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        (old_id,) = await repo.record([touch("thread-a", created=True)])
        assert await repo.mark_deleted(old_id) is True

        (new_id,) = await repo.record([touch("thread-b", created=True)])

        assert new_id != old_id
        assert len(await rows(sf, FolderLedgerFolderRow, FolderLedgerFolderRow.deleted_at.is_(None))) == 1


async def test_events_are_capped_per_folder_newest_kept(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        await repo.record([touch("thread-a", rel=f"acme/{n}.txt") for n in range(MAX_EVENTS_PER_FOLDER + 5)])

        async with sf() as session:
            count = await session.scalar(select(func.count()).select_from(FolderLedgerEventRow))
        assert count == MAX_EVENTS_PER_FOLDER
        (folder_id,) = [row.id for row in await rows(sf, FolderLedgerFolderRow)]
        detail = await repo.folder_detail(folder_id=folder_id)
        assert detail["events"][0]["rel_path"] == f"acme/{MAX_EVENTS_PER_FOLDER + 4}.txt"
        assert detail["events"][-1]["rel_path"] == "acme/5.txt"


async def test_a_straggling_write_of_a_deleted_thread_does_not_keep_the_folder(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        await put_thread(sf, "thread-a")
        (folder_id,) = await repo.record([touch("thread-a", created=True)])

        await drop_thread(sf, "thread-a")  # the thread delete removes thread_meta first
        assert await repo.tombstone_thread("thread-a") == 1
        await repo.record([touch("thread-a")])

        (row,) = await rows(sf, FolderLedgerTouchRow)
        assert row.writes == 2
        assert await repo.live_thread_ids(folder_id) == set()
        assert [orphan["id"] for orphan in await repo.find_orphans(thread_ids=["thread-a"], user_id=ALICE)] == [folder_id]


async def test_a_recreated_thread_id_keeps_using_its_folder(tmp_path, backend):
    """Thread ids come back (a stale tab, an IM binding); the new thread's writes count."""
    async with database(tmp_path, backend) as (sf, repo):
        await put_thread(sf, "x")
        await put_thread(sf, "y")
        folder_id, _same = await repo.record([touch("x", created=True), touch("y")])
        await drop_thread(sf, "x")
        await repo.tombstone_thread("x")

        await put_thread(sf, "x")  # start_run recreates the thread_meta row under the same id
        await repo.record([touch("x")])
        assert await repo.live_thread_ids(folder_id) == {"x", "y"}

        await drop_thread(sf, "y")
        await repo.tombstone_thread("y")
        assert await repo.live_thread_ids(folder_id) == {"x"}
        assert await repo.find_orphans(thread_ids=["y"], user_id=ALICE) == []


async def test_branch_inherits_only_live_touches_of_live_folders(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        await repo.record([touch("parent", name="kept", created=True), touch("parent", name="gone", created=True)])
        (gone,) = [row.id for row in await rows(sf, FolderLedgerFolderRow, FolderLedgerFolderRow.name == "gone")]
        await repo.mark_deleted(gone)

        assert await repo.inherit_thread(parent_thread_id="parent", child_thread_id="child", user_id=ALICE) == 1
        assert await repo.inherit_thread(parent_thread_id="parent", child_thread_id="child", user_id=ALICE) == 1  # idempotent

        (child,) = await rows(sf, FolderLedgerTouchRow, FolderLedgerTouchRow.thread_id == "child")
        assert (child.role, child.inherited_from_thread_id, child.writes) == ("inherited", "parent", 0)
        await repo.tombstone_thread("parent")
        assert await repo.inherit_thread(parent_thread_id="parent", child_thread_id="grandchild", user_id=ALICE) == 0


async def test_orphans_count_every_users_live_touch(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        await put_thread(sf, "alice-1", ALICE)
        await put_thread(sf, "bob-1", BOB)
        await repo.record([touch("alice-1", created=True), touch("bob-1", user_id=BOB)])

        await repo.tombstone_thread("alice-1")
        await drop_thread(sf, "alice-1")
        assert await repo.find_orphans(thread_ids=["alice-1"], user_id=ALICE) == []

        await drop_thread(sf, "bob-1")  # reconciled: no tombstone, row gone
        (orphan,) = await repo.find_orphans(thread_ids=["alice-1"], user_id=ALICE)
        assert (orphan["name"], orphan["writes"], orphan["created_by_user_id"]) == ("acme", 2, ALICE)


async def test_orphans_ignore_other_users_thread_ids(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        await repo.record([touch("alice-1", created=True)])

        assert await repo.find_orphans(thread_ids=["alice-1"], user_id=BOB) == []
        assert len(await repo.find_orphans(thread_ids=["alice-1", "unknown"], user_id=ALICE)) == 1


async def test_orphans_skip_dismissed_until_new_activity(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        (folder_id,) = await repo.record([touch("alice-1", created=True)])
        assert await repo.mark_dismissed(folder_id, user_id=ALICE) is True
        assert await repo.find_orphans(thread_ids=["alice-1"], user_id=ALICE) == []

        await repo.record([touch("alice-2")])
        assert [row["id"] for row in await repo.find_orphans(thread_ids=["alice-1"], user_id=ALICE)] == [folder_id]


async def test_dismissal_is_per_user(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        folder_id, _same = await repo.record([touch("alice-1", created=True), touch("bob-1", user_id=BOB)])

        assert await repo.mark_dismissed(folder_id, user_id=BOB) is True
        assert await repo.mark_dismissed(folder_id, user_id=BOB) is True  # idempotent

        assert await repo.find_orphans(thread_ids=["bob-1"], user_id=BOB) == []
        assert [row["id"] for row in await repo.find_orphans(thread_ids=["alice-1"], user_id=ALICE)] == [folder_id]
        await repo.mark_deleted(folder_id)
        assert await repo.mark_dismissed(folder_id, user_id=ALICE) is False


async def test_live_folders_never_crowd_an_orphan_out_of_the_answer(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        (orphan_id,) = await repo.record([touch("gone", name="old-orphan", created=True)])
        await put_thread(sf, "keep")
        busy = [f"busy-{n:03d}" for n in range(MAX_FOLDERS_PER_QUERY + 1)]
        await repo.record([touch("gone", name=name, created=True) for name in busy] + [touch("keep", name=name) for name in busy])
        await repo.tombstone_thread("gone")

        assert [row["id"] for row in await repo.find_orphans(thread_ids=["gone"], user_id=ALICE)] == [orphan_id]


async def test_the_binding_follows_writes_that_started_from_the_bound_entry(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        root = "/srv/projects"
        (folder_id,) = await repo.record([touch("t", created=True, host_root=root, entry_after="1:10")])
        # A recorded rewrite of the bound entry (a bare file replaced atomically).
        await repo.record([touch("t", host_root=root, entry_before="1:10", entry_after="1:11")])
        assert (await repo.get_folder(folder_id))["host_entry"] == "1:11"
        # A write that started from some other entry, or under another root, moves nothing.
        await repo.record([touch("t", host_root=root, entry_before="1:99", entry_after="1:12")])
        await repo.record([touch("t", host_root="/srv/elsewhere", entry_before="1:11", entry_after="1:13")])
        assert (await repo.get_folder(folder_id))["host_entry"] == "1:11"
        assert (await repo.get_folder(folder_id))["host_root"] == root


async def test_an_upgraded_creation_takes_the_new_entrys_binding(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        (folder_id,) = await repo.record([touch("t", host_root="/srv/a", entry_after="1:10")])  # pre-existing
        await repo.record([touch("u", user_id=BOB, created=True, host_root="/srv/a", entry_after="1:20")])  # seen recreated

        folder = await repo.get_folder(folder_id)
        assert (folder["created_attribution"], folder["created_by_user_id"], folder["host_entry"]) == ("observed_create", BOB, "1:20")


async def test_a_removed_entry_retires_its_row_so_the_next_creator_is_credited(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        (old_id,) = await repo.record([touch("alice-1", created=True)])
        await repo.record([], removed=[("/mnt/projects", "acme")])
        (new_id,) = await repo.record([touch("bob-1", user_id=BOB, created=True)])

        assert new_id != old_id
        folder = await repo.get_folder(new_id)
        assert (folder["created_by_user_id"], folder["created_by_thread_id"]) == (BOB, "bob-1")
        assert (await repo.get_folder(old_id))["deleted_at"] is not None


@pytest.mark.parametrize(
    ("metadata", "anchor_alive", "orphan"),
    [
        ({"deerflow_edit_version": True, "edit_root_thread_id": "root"}, False, True),
        ({"deerflow_edit_version": True, "edit_root_thread_id": "root"}, True, False),
        ({"deerflow_sidecar": True, "parent_thread_id": "root"}, False, True),
        ({"deerflow_edit_version": "yes", "edit_root_thread_id": "root"}, False, False),  # malformed: stands alone
    ],
)
async def test_hidden_dependents_of_a_deleted_root_do_not_pin_a_folder(tmp_path, backend, metadata, anchor_alive, orphan):
    async with database(tmp_path, backend) as (sf, repo):
        if anchor_alive:
            await put_thread(sf, "root")
        await put_thread(sf, "version", metadata=metadata)
        await repo.record([touch("root", created=True), touch("version")])
        await repo.tombstone_thread("root")

        found = await repo.find_orphans(thread_ids=["root"], user_id=ALICE)

        assert bool(found) is orphan


async def test_thread_listing_counts_other_live_conversations(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        for thread_id, user_id in (("a", ALICE), ("b", ALICE), ("c", BOB)):
            await put_thread(sf, thread_id, user_id)
        await repo.record([touch("a", created=True), touch("b"), touch("c", user_id=BOB), touch("a", name="solo", created=True)])
        await repo.tombstone_thread("b")

        listing = {entry["folder"]["name"]: entry for entry in await repo.list_thread_folders(thread_id="a", user_id=ALICE)}

        assert listing["acme"]["other_live_threads"] == 1
        assert listing["solo"]["other_live_threads"] == 0
        assert listing["acme"]["touch"]["role"] == "created"
        assert await repo.list_thread_folders(thread_id="a", user_id=BOB) == []


async def test_shared_workspace_listing_merges_every_users_touch_of_the_thread(tmp_path, backend):
    async with database(tmp_path, backend) as (sf, repo):
        await repo.record([touch("a", op="edit"), touch("a", user_id=BOB, created=True), touch("a", user_id=BOB)])

        (entry,) = await repo.list_thread_folders(thread_id="a", user_id=None)

        assert (entry["touch"]["role"], entry["touch"]["writes"], entry["touch"]["edits"]) == ("created", 2, 1)


async def test_sync_recorder_store_and_async_repository_share_one_database(tmp_path):
    db = tmp_path / "shared.db"
    sync_engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(sync_engine, tables=[model.__table__ for model in _TABLES])
    store = FolderLedgerRecorderStore(sessionmaker(sync_engine, expire_on_commit=False))
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    try:
        (folder_id,) = await asyncio.to_thread(store.record, [touch("thread-a", created=True)])
        repo = FolderLedgerRepository(async_sessionmaker(async_engine, expire_on_commit=False))
        folder = await repo.get_folder(folder_id)
        assert (folder["name"], folder["created_attribution"]) == ("acme", "observed_create")
    finally:
        await async_engine.dispose()
        sync_engine.dispose()


async def test_touch_record_rejects_unknown_ops_and_oversized_fields():
    with pytest.raises(ValueError):
        touch("t", op="delete")
    with pytest.raises(ValueError):
        TouchRecord(mount_path="/mnt/p", name="x" * 256, kind="dir", rel_path="x", op="write", created=False, user_id="u", thread_id="t")
