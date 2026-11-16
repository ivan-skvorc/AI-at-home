"""``/api/folder-ledger`` over a real SQLite ledger and real temporary mount directories.

Covers owner scoping, the orphan offer after a real ``DELETE /api/threads/{id}``,
pseudonymous detail rows for other users, and every refusal of the confined
delete (link, bad names, read-only or unconfigured mount, invisible host,
protected paths, a live conversation reappearing).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.routers import folder_ledger, threads
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import VolumeMountConfig
from deerflow.persistence.base import Base
from deerflow.persistence.folder_ledger import FolderLedgerEventRow, FolderLedgerFolderRow, FolderLedgerRepository, FolderLedgerTouchRow, TouchRecord
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow

ALICE = User(id=UUID(int=1), email="alice@example.com", password_hash="x", system_role="user")
BOB = User(id=UUID(int=2), email="bob@example.com", password_hash="x", system_role="user")
ADMIN = User(id=UUID(int=3), email="admin@example.com", password_hash="x", system_role="admin")
A, B = str(ALICE.id), str(BOB.id)
LOCAL = "deerflow.sandbox.local:LocalSandboxProvider"
_TABLES = [ThreadMetaRow, FolderLedgerFolderRow, FolderLedgerTouchRow, FolderLedgerEventRow]
posix_only = pytest.mark.skipif(os.name != "posix", reason="descriptor-relative deletes are POSIX-only")


class _RunManager:
    @asynccontextmanager
    async def reserve_thread_operation(self, _thread_id, **_kwargs):
        yield

    async def discard_thread_runs(self, _thread_id):
        return None


@pytest.fixture
def env(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    db = tmp_path / "ledger.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[model.__table__ for model in _TABLES]))

    asyncio.run(_create())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    state = SimpleNamespace(
        projects=projects,
        factory=factory,
        repo=FolderLedgerRepository(factory),
        mounts=[VolumeMountConfig(host_path=str(projects), container_path="/mnt/projects")],
        home=tmp_path / "home",
    )

    def config():
        return SimpleNamespace(sandbox=SimpleNamespace(use=LOCAL, mounts=state.mounts), skills=SimpleNamespace(container_path="/mnt/skills"))

    monkeypatch.setattr(folder_ledger, "get_session_factory", lambda: factory)
    monkeypatch.setattr(folder_ledger, "_load_app_config", config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(state.home))
    try:
        yield state
    finally:
        asyncio.run(engine.dispose())


def _client(user, *, owner_check_passes=True):
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True, owner_check_passes=owner_check_passes)
    app.include_router(folder_ledger.router)
    return TestClient(app)


def _record(env, thread_id, user_id, *, name="acme", created=True, op="write"):
    (folder_id,) = asyncio.run(env.repo.record([TouchRecord(mount_path="/mnt/projects", name=name, kind="dir", rel_path=f"{name}/a.txt", op=op, created=created, user_id=user_id, thread_id=thread_id, run_id="run-1")]))
    return folder_id


def _put_thread(env, thread_id, user_id, title=None):
    async def _run():
        now = datetime.now(UTC)
        async with env.factory() as session:
            await session.execute(ThreadMetaRow.__table__.insert().values(thread_id=thread_id, user_id=user_id, display_name=title, status="idle", metadata_json={}, created_at=now, updated_at=now))
            await session.commit()

    asyncio.run(_run())


def _drop_thread(env, thread_id):
    async def _run():
        await env.repo.tombstone_thread(thread_id)
        async with env.factory() as session:
            await session.execute(ThreadMetaRow.__table__.delete().where(ThreadMetaRow.thread_id == thread_id))
            await session.commit()

    asyncio.run(_run())


def _orphan_folder(env, name="acme"):
    """A folder Alice's (now deleted) conversation created, present on the host."""
    (env.projects / name).mkdir(exist_ok=True)
    (env.projects / name / "a.txt").write_text("x", encoding="utf-8")
    folder_id = _record(env, "alice-1", A, name=name)
    return folder_id


def _live_folder_rows(env):
    async def _run():
        async with env.factory() as session:
            return (await session.execute(select(FolderLedgerFolderRow).where(FolderLedgerFolderRow.deleted_at.is_(None)))).scalars().all()

    return asyncio.run(_run())


# -- availability -------------------------------------------------------


def test_memory_backend_reports_unavailable(env, monkeypatch):
    monkeypatch.setattr(folder_ledger, "get_session_factory", lambda: None)
    with _client(ALICE) as client:
        assert client.get("/api/folder-ledger/threads/alice-1/folders").json() == {"available": False, "folders": []}
        assert client.post("/api/folder-ledger/orphans", json={"thread_ids": ["alice-1"]}).json() == {"available": False, "orphans": []}
        assert client.get(f"/api/folder-ledger/folders/{'a' * 32}").status_code == 503
        assert client.delete(f"/api/folder-ledger/folders/{'a' * 32}", params={"confirm_name": "x"}).status_code == 503
        assert client.post(f"/api/folder-ledger/folders/{'a' * 32}/dismiss").status_code == 503


# -- listing and detail -------------------------------------------------


def test_thread_folders_lists_this_threads_folders_with_counts(env):
    _put_thread(env, "alice-1", A)
    _put_thread(env, "bob-1", B)
    (env.projects / "acme").mkdir()
    folder_id = _record(env, "alice-1", A)
    _record(env, "bob-1", B, created=False)

    with _client(ALICE) as client:
        body = client.get("/api/folder-ledger/threads/alice-1/folders").json()

    assert body["available"] is True
    (folder,) = body["folders"]
    assert folder["id"] == folder_id
    assert (folder["path"], folder["name"], folder["mount_path"], folder["kind"]) == ("/mnt/projects/acme", "acme", "/mnt/projects", "dir")
    assert (folder["role"], folder["created_here"], folder["created_attribution"]) == ("created", True, "observed_create")
    assert (folder["writes"], folder["edits"], folder["shell_ops"], folder["other_live_threads"], folder["host_visible"]) == (1, 0, 0, 1, True)
    assert folder["first_at"].endswith("+00:00")


def test_thread_folders_are_scoped_to_the_callers_touches(env):
    _record(env, "alice-1", A)
    with _client(BOB) as client:
        assert client.get("/api/folder-ledger/threads/alice-1/folders").json()["folders"] == []
    with _client(BOB, owner_check_passes=False) as client:
        assert client.get("/api/folder-ledger/threads/alice-1/folders").status_code == 404


def test_folder_detail_pseudonymizes_other_users_conversations(env):
    _put_thread(env, "alice-1", A, title="Build the site")
    _put_thread(env, "bob-1", B, title="Bob's private chat")
    folder_id = _record(env, "alice-1", A)
    _record(env, "bob-1", B, created=False, op="edit")

    with _client(ALICE) as client:
        body = client.get(f"/api/folder-ledger/folders/{folder_id}").json()
    with _client(ADMIN) as client:
        assert client.get(f"/api/folder-ledger/folders/{folder_id}").status_code == 404

    threads_by_own = {row["own"]: row for row in body["threads"]}
    assert threads_by_own[True] | {"first_at": None, "last_at": None} == {"thread_id": "alice-1", "own": True, "title": "Build the site", "role": "created", "first_at": None, "last_at": None, "deleted": False}
    other = threads_by_own[False]
    assert other["thread_id"].startswith("other-") and "bob-1" not in other["thread_id"]
    assert other["title"] is None
    assert [event["op"] for event in body["events"]] == ["edit", "write"]  # newest first
    assert body["events"][0]["thread_id"] == other["thread_id"] and body["events"][0]["run_id"] is None
    assert (body["folder"]["writes"], body["folder"]["edits"], body["folder"]["other_live_threads"], body["folder"]["created_here"]) == (1, 1, 2, True)
    assert "role" not in body["folder"] or body["folder"]["role"] is None


# -- orphans --------------------------------------------------------------


def test_real_thread_delete_tombstones_and_the_folder_is_offered(env, tmp_path):
    _put_thread(env, "alice-1", A)
    folder_id = _orphan_folder(env)
    app = make_authed_test_app(user_factory=lambda: ALICE, bind_current_user=True)
    app.state.run_manager = _RunManager()
    app.state.thread_store = ThreadMetaRepository(env.factory)
    app.include_router(threads.router)
    app.include_router(folder_ledger.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=Paths(tmp_path / "home")), TestClient(app) as client:
        assert client.delete("/api/threads/alice-1").status_code == 200
        body = client.post("/api/folder-ledger/orphans", json={"thread_ids": ["alice-1"]}).json()

    (orphan,) = body["orphans"]
    assert orphan == {
        "id": folder_id,
        "path": "/mnt/projects/acme",
        "name": "acme",
        "mount_path": "/mnt/projects",
        "created_by_thread_id": "alice-1",
        "created_attribution": "observed_create",
        "last_at": orphan["last_at"],
        "writes": 1,
        "edits": 0,
        "deletable": os.name == "posix",
        "reason": None if os.name == "posix" else "unsupported_platform",
    }
    (touch,) = asyncio.run(_touches(env))
    assert touch.thread_deleted_at is not None


async def _touches(env):
    async with env.factory() as session:
        return (await session.execute(select(FolderLedgerTouchRow))).scalars().all()


def test_orphans_ignore_other_users_thread_ids(env):
    _orphan_folder(env)
    with _client(BOB) as client:
        assert client.post("/api/folder-ledger/orphans", json={"thread_ids": ["alice-1"]}).json() == {"available": True, "orphans": []}


def test_orphans_are_not_offered_while_another_users_conversation_is_live(env):
    _orphan_folder(env)
    _put_thread(env, "bob-1", B)
    _record(env, "bob-1", B, created=False)
    with _client(ALICE) as client:
        assert client.post("/api/folder-ledger/orphans", json={"thread_ids": ["alice-1"]}).json()["orphans"] == []


@posix_only
def test_orphan_reasons(env):
    _record(env, "alice-1", A, name="existing", created=False)
    _orphan_folder(env, "made-by-alice")
    _record(env, "bob-x", B, name="made-by-alice", created=False)
    with _client(BOB) as client:
        reasons = {row["name"]: (row["deletable"], row["reason"], row["created_by_thread_id"]) for row in client.post("/api/folder-ledger/orphans", json={"thread_ids": ["bob-x"]}).json()["orphans"]}
    assert reasons == {"made-by-alice": (False, "not_creator", None)}
    with _client(ALICE) as client:
        reasons = {row["name"]: (row["deletable"], row["reason"]) for row in client.post("/api/folder-ledger/orphans", json={"thread_ids": ["alice-1"]}).json()["orphans"]}
    assert reasons == {"existing": (False, "preexisting"), "made-by-alice": (True, None)}

    env.mounts = [VolumeMountConfig(host_path=str(env.projects), container_path="/mnt/projects", read_only=True)]
    with _client(ALICE) as client:
        rows = client.post("/api/folder-ledger/orphans", json={"thread_ids": ["alice-1"]}).json()["orphans"]
    assert {row["name"]: row["reason"] for row in rows}["made-by-alice"] == "mount_unavailable"

    env.mounts = [VolumeMountConfig(host_path=str(env.projects / "gone"), container_path="/mnt/projects")]
    with _client(ALICE) as client:
        rows = client.post("/api/folder-ledger/orphans", json={"thread_ids": ["alice-1"]}).json()["orphans"]
    assert {row["name"]: row["reason"] for row in rows}["made-by-alice"] == "host_not_visible"


def test_orphans_reject_an_oversized_id_list(env):
    with _client(ALICE) as client:
        assert client.post("/api/folder-ledger/orphans", json={"thread_ids": [f"t{n}" for n in range(501)]}).status_code == 422


# -- delete ---------------------------------------------------------------


@posix_only
def test_delete_removes_the_folder_and_marks_it(env):
    folder_id = _orphan_folder(env)
    with _client(ALICE) as client:
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"})
        assert response.status_code == 200, response.text
        assert response.json() == {"deleted": True}
        assert client.get(f"/api/folder-ledger/folders/{folder_id}").status_code == 404
    assert not (env.projects / "acme").exists()
    assert env.projects.exists()
    assert _live_folder_rows(env) == []


@posix_only
def test_admin_can_delete_and_an_already_missing_folder_is_marked(env):
    folder_id = _record(env, "alice-1", A)  # never materialized on the host
    with _client(ADMIN) as client:
        assert client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"}).json() == {"deleted": True}
    assert _live_folder_rows(env) == []


@posix_only
def test_delete_refuses_a_symlink_without_following_it(env, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    (env.projects / "link").symlink_to(outside, target_is_directory=True)
    folder_id = _record(env, "alice-1", A, name="link")

    with _client(ALICE) as client:
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "link"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "link"
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (env.projects / "link").is_symlink()


@pytest.mark.parametrize("name", ["..", ".", "a/b", "a\\b"])
@posix_only
def test_delete_refuses_names_that_are_not_one_segment(env, name):
    folder_id = _record(env, "alice-1", A, name=name)
    with _client(ALICE) as client:
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": name})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_name"
    assert env.projects.exists()


@posix_only
def test_delete_refusals(env, tmp_path):
    folder_id = _orphan_folder(env)
    preexisting = _record(env, "alice-1", A, name="legacy", created=False)

    with _client(BOB) as client:
        assert client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"}).status_code == 404  # invisible
    _record(env, "bob-1", B, created=False)
    _drop_thread(env, "bob-1")
    with _client(BOB) as client:
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"})
        assert (response.status_code, response.json()["detail"]["code"]) == (403, "not_creator")
    with _client(ALICE) as client:
        response = client.delete(f"/api/folder-ledger/folders/{preexisting}", params={"confirm_name": "legacy"})
        assert (response.status_code, response.json()["detail"]["code"]) == (403, "preexisting")
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "ACME"})
        assert (response.status_code, response.json()["detail"]["code"]) == (422, "confirm_name")

        env.mounts = [VolumeMountConfig(host_path=str(env.projects), container_path="/mnt/projects", read_only=True)]
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"})
        assert (response.status_code, response.json()["detail"]["code"]) == (422, "mount_unavailable")

        env.mounts = []
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"})
        assert (response.status_code, response.json()["detail"]["code"]) == (422, "mount_unavailable")

        env.mounts = [VolumeMountConfig(host_path=str(tmp_path / "not-here"), container_path="/mnt/projects")]
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"})
        assert (response.status_code, response.json()["detail"]["code"]) == (422, "host_not_visible")

        # Another mount's host root lives inside the folder: never removed.
        env.mounts = [
            VolumeMountConfig(host_path=str(env.projects), container_path="/mnt/projects"),
            VolumeMountConfig(host_path=str(env.projects / "acme"), container_path="/mnt/acme-ro", read_only=True),
        ]
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"})
        assert (response.status_code, response.json()["detail"]["code"]) == (422, "protected")
    assert (env.projects / "acme" / "a.txt").exists()


@posix_only
def test_delete_refuses_deerflows_own_data_root(env):
    folder_id = _orphan_folder(env, "deer-home")
    env.home = env.projects / "deer-home" / ".deer-flow"
    env.home.mkdir()
    with _client(ALICE) as client:
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "deer-home"})
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "protected")
    assert env.home.exists()


@posix_only
def test_delete_answers_409_when_a_live_conversation_uses_the_folder_again(env):
    folder_id = _orphan_folder(env)
    _put_thread(env, "alice-2", A)
    _record(env, "alice-2", A, created=False)
    with _client(ALICE) as client:
        response = client.delete(f"/api/folder-ledger/folders/{folder_id}", params={"confirm_name": "acme"})
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "in_use")
    assert (env.projects / "acme").exists()


def test_dismiss_stops_the_offer(env):
    folder_id = _orphan_folder(env)
    with _client(ALICE) as client:
        assert client.post(f"/api/folder-ledger/folders/{folder_id}/dismiss").json() == {"dismissed": True}
        assert client.post("/api/folder-ledger/orphans", json={"thread_ids": ["alice-1"]}).json()["orphans"] == []
    with _client(BOB) as client:
        assert client.post(f"/api/folder-ledger/folders/{folder_id}/dismiss").status_code == 404
    assert (env.projects / "acme").exists()


def test_malformed_folder_ids_are_rejected(env):
    with _client(ALICE) as client:
        assert client.get("/api/folder-ledger/folders/..%2F..").status_code in (404, 422)
        assert client.delete("/api/folder-ledger/folders/NOT-HEX", params={"confirm_name": "x"}).status_code == 422
