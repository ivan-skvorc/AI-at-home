"""Regression anchor: the thread file explorer listing must not block the event loop.

``list_thread_files`` resolves the requested virtual path (``Path.resolve``
stats every component), ``lstat``s the directory, scans it with
``os.scandir`` and ``lstat``s each listed entry. All of it is blocking
filesystem IO that has to run in the file-IO worker; if any of it moves back
onto the event loop, the strict Blockbuster gate raises ``BlockingError`` and
these tests fail. The error statuses are raised from the same worker, so
they are anchored too.

The ``@require_permission`` decorator is bypassed via ``__wrapped__`` so the
anchor exercises the handler's own filesystem IO, not the authz layer. Imports
sit at module top so any import-time IO runs at collection, outside the gate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.gateway.path_utils import resolve_thread_virtual_path
from app.gateway.routers.thread_files import list_thread_files

pytestmark = pytest.mark.asyncio

# The undecorated coroutine (``require_permission`` uses ``functools.wraps``).
_list_thread_files = list_thread_files.__wrapped__


async def _user_data_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # Rebuild cached Paths against the tmp home so the thread resolves under it.
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)
    # Test-side resolution touches the filesystem too; keep it off the loop.
    return await asyncio.to_thread(resolve_thread_virtual_path, "t1", "/mnt/user-data")


async def test_listing_a_directory_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    user_data = await _user_data_root(tmp_path, monkeypatch)

    def build_tree() -> None:
        workspace = user_data / "workspace"
        (workspace / "src").mkdir(parents=True)
        (workspace / "app.py").write_text("print('hi')\n", encoding="utf-8")
        try:
            (workspace / "link").symlink_to("src", target_is_directory=True)
        except OSError:
            (workspace / "link").write_text("symlinks unavailable", encoding="utf-8")

    await asyncio.to_thread(build_tree)

    listing = await _list_thread_files("t1", request=None, path="/mnt/user-data/workspace")

    assert listing.exists is True
    assert [entry.name for entry in listing.entries] == ["src", "app.py", "link"]
    assert listing.entries[1].size == len("print('hi')\n")


async def test_missing_root_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    await _user_data_root(tmp_path, monkeypatch)

    listing = await _list_thread_files("t1", request=None, path="/mnt/user-data")

    assert listing.exists is False
    assert listing.entries == []


@pytest.mark.parametrize(("requested", "status_code"), [("/mnt/user-data/workspace/missing", 404), ("/mnt/user-data/workspace/app.py", 400)])
async def test_error_statuses_do_not_block_event_loop(tmp_path: Path, monkeypatch, requested: str, status_code: int) -> None:
    user_data = await _user_data_root(tmp_path, monkeypatch)

    def build_tree() -> None:
        (user_data / "workspace").mkdir(parents=True)
        (user_data / "workspace" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    await asyncio.to_thread(build_tree)

    with pytest.raises(HTTPException) as exc_info:
        await _list_thread_files("t1", request=None, path=requested)

    assert exc_info.value.status_code == status_code
