"""Regression anchor: the folder ledger never blocks the event loop.

The recorder probes host folders and writes through the synchronous engine;
the routes read config, check host visibility and run a confined ``rmtree``.
Every one of those is blocking I/O that must run in a worker thread, so a
regression onto the loop raises ``BlockingError`` under the strict gate.

The ``@require_permission`` decorator is bypassed via ``__wrapped__`` so the
anchor exercises the handlers' own I/O, not the authz layer.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.gateway.routers import folder_ledger
from deerflow.agents.middlewares.folder_ledger_middleware import FolderLedgerMiddleware
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import VolumeMountConfig
from deerflow.persistence.base import Base
from deerflow.persistence.folder_ledger import FolderLedgerDismissalRow, FolderLedgerEventRow, FolderLedgerFolderRow, FolderLedgerRecorderStore, FolderLedgerRepository, FolderLedgerTouchRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import reset_current_user, set_current_user

pytestmark = pytest.mark.asyncio
_TABLES = [ThreadMetaRow, FolderLedgerFolderRow, FolderLedgerTouchRow, FolderLedgerEventRow, FolderLedgerDismissalRow]


def _config(projects):
    return SimpleNamespace(
        sandbox=SimpleNamespace(use="deerflow.sandbox.local:LocalSandboxProvider", mounts=[VolumeMountConfig(host_path=str(projects), container_path="/mnt/projects")]),
        skills=SimpleNamespace(container_path="/mnt/skills"),
        database=None,
    )


def _sync_store(db):
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine, tables=[model.__table__ for model in _TABLES])
    return engine, FolderLedgerRecorderStore(sessionmaker(engine, expire_on_commit=False))


async def test_recorder_probes_and_writes_off_the_loop(tmp_path):
    projects = tmp_path / "projects"
    await asyncio.to_thread(projects.mkdir)
    engine, store = await asyncio.to_thread(_sync_store, tmp_path / "ledger.db")
    middleware = FolderLedgerMiddleware(app_config=_config(projects), store_factory=lambda: store, ledger_available=lambda: True)
    request = ToolCallRequest(
        tool_call={"name": "bash", "args": {"command": "mkdir -p /mnt/projects/acme"}, "id": "call-1"},
        tool=None,
        state={"messages": []},
        runtime=SimpleNamespace(context={"thread_id": "t1", "user_id": "alice", "run_id": "r1"}),
    )

    async def handler(req):
        await asyncio.to_thread((projects / "acme").mkdir)
        return ToolMessage(content="", tool_call_id="call-1", name="bash")

    try:
        result = await middleware.awrap_tool_call(request, handler)
        rows = await asyncio.to_thread(lambda: store._Session().query(FolderLedgerFolderRow).all())
    finally:
        await asyncio.to_thread(engine.dispose)

    assert result.content == ""
    assert [(row.name, row.created_attribution) for row in rows] == [("acme", "inferred_shell")]


async def test_routes_list_offer_and_delete_off_the_loop(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    await asyncio.to_thread(lambda: (projects / "acme").mkdir(parents=True))
    await asyncio.to_thread((projects / "acme" / "a.txt").write_text, "x", encoding="utf-8")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[model.__table__ for model in _TABLES]))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = FolderLedgerRepository(factory)
    from deerflow.folder_ledger.mounts import LedgerMount, host_root_key, probe_entry
    from deerflow.persistence.folder_ledger import TouchRecord

    mount = LedgerMount(container_path="/mnt/projects", host_path=str(projects), read_only=False)
    probe = await asyncio.to_thread(probe_entry, mount, "acme")
    record = TouchRecord(mount_path="/mnt/projects", name="acme", kind="dir", rel_path="acme/a.txt", op="write", created=True, user_id="alice", thread_id="t1", host_root=host_root_key(mount), entry_after=probe.identity)
    (folder_id,) = await repo.record([record])
    monkeypatch.setattr(folder_ledger, "get_session_factory", lambda: factory)
    monkeypatch.setattr(folder_ledger, "_load_app_config", lambda: _config(projects))
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(tmp_path / "home"))
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})
    request.state.user = SimpleNamespace(id="alice", system_role="user")
    token = set_current_user(SimpleNamespace(id="alice"))
    try:
        listing = await folder_ledger.list_thread_folders.__wrapped__("t1", request)
        detail = await folder_ledger.get_folder.__wrapped__(folder_id, request)
        orphans = await folder_ledger.find_orphans.__wrapped__(folder_ledger.OrphansRequest(thread_ids=["t1"]), request)
        deleted = await folder_ledger.delete_folder.__wrapped__(folder_id, request, confirm_name="acme")
    finally:
        reset_current_user(token)
        await engine.dispose()

    assert listing.folders[0].host_visible is True
    assert detail.folder.name == "acme"
    assert orphans.orphans[0].deletable is True
    assert deleted.deleted is True
    assert not await asyncio.to_thread((projects / "acme").exists)
