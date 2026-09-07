"""Runtime-toggleable server settings (fork feature).

These are settings a user may flip from the Web UI at runtime — as opposed to
the operator's ``config.yaml``, which the UI never rewrites. Two things live
here:

* **multi-user mode** — per-user thread isolation, default on. Server-wide, so
  the write is admin-gated (in passwordless mode the built-in ``default`` user
  is admin).
* **chat folders** — the sidebar's folder registry (id, name, parent, display
  order). Per-user UI state, so it is scoped to the caller and needs no admin
  gate.
* **dependency updates** — an on-demand refresh of the Camoufox browser and the
  bundled SearXNG image. This runs commands on the host, so it is admin-gated
  like multi-user mode, and takes no input from the caller at all.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.gateway.dependency_update import get_dependency_updater
from app.gateway.deps import require_admin_user
from deerflow.config.runtime_settings import is_multi_user_mode_enabled, set_multi_user_mode
from deerflow.config.user_ui_state import (
    MAX_CHAT_FOLDERS,
    get_chat_folders,
    set_chat_folders,
)
from deerflow.runtime.user_context import get_effective_user_id

router = APIRouter(prefix="/api/settings", tags=["settings"])


class MultiUserModeResponse(BaseModel):
    """Current multi-user-mode setting."""

    multi_user_mode: bool


class MultiUserModeUpdate(BaseModel):
    """Request body to toggle multi-user mode."""

    enabled: bool


@router.get("/multi-user-mode", response_model=MultiUserModeResponse)
async def get_multi_user_mode_setting() -> MultiUserModeResponse:
    """Return whether per-user thread isolation is active (default true)."""
    return MultiUserModeResponse(multi_user_mode=is_multi_user_mode_enabled())


@router.put("/multi-user-mode", response_model=MultiUserModeResponse)
async def update_multi_user_mode_setting(body: MultiUserModeUpdate, request: Request) -> MultiUserModeResponse:
    """Toggle multi-user mode (admin only).

    Turning it OFF makes the server show all conversations to every login/device
    (one shared workspace). The file write is offloaded so it never blocks the
    event loop.
    """
    await require_admin_user(request, detail="Only an admin can change multi-user mode.")
    await asyncio.to_thread(set_multi_user_mode, body.enabled)
    return MultiUserModeResponse(multi_user_mode=is_multi_user_mode_enabled())


class ChatFolder(BaseModel):
    """One sidebar folder: a stable id, the name the user typed, and its parent.

    Membership is deliberately *not* here — a conversation records its folder in
    its own ``deerflow_folder`` thread metadata. That split is what makes a
    rename one write instead of one per conversation in the folder.

    ``parentId`` is what makes the list a tree; ``None`` is a top-level folder.
    The store repairs a dangling parent, a loop, or an over-deep chain by moving
    the offending folder to the top level rather than dropping it, so a bad
    parent link can never hide the conversations filed under it.
    """

    id: str
    name: str
    parentId: str | None = None


class ChatFoldersResponse(BaseModel):
    """The caller's sidebar folders, in display order."""

    chat_folders: list[ChatFolder]


class ChatFoldersUpdate(BaseModel):
    """Replacement folder list. Over-long lists are truncated, not rejected."""

    chat_folders: list[ChatFolder] = Field(default_factory=list)


@router.get("/chat-folders", response_model=ChatFoldersResponse)
async def get_chat_folders_setting() -> ChatFoldersResponse:
    """Return the caller's sidebar folders (durable across browsers/devices)."""
    folders = await asyncio.to_thread(get_chat_folders, get_effective_user_id())
    return ChatFoldersResponse(chat_folders=[ChatFolder(**folder) for folder in folders])


@router.put("/chat-folders", response_model=ChatFoldersResponse)
async def update_chat_folders_setting(body: ChatFoldersUpdate) -> ChatFoldersResponse:
    """Replace the caller's sidebar folders; returns the persisted value.

    An empty list is a real value (the user deleted their last folder), so it is
    stored rather than ignored. The store caps the list at ``MAX_CHAT_FOLDERS``,
    drops malformed entries and repairs the ``parentId`` links into a real
    forest, so the response is the authoritative post-write state the client
    should adopt.

    Deleting a folder here never deletes a conversation: a thread still pointing
    at a folder that no longer exists falls back to the sidebar's root list.
    """
    payload = [folder.model_dump() for folder in body.chat_folders[: MAX_CHAT_FOLDERS * 4]]
    folders = await asyncio.to_thread(set_chat_folders, get_effective_user_id(), payload)
    return ChatFoldersResponse(chat_folders=[ChatFolder(**folder) for folder in folders])


class DependencyUpdateResponse(BaseModel):
    """State of the on-demand Camoufox + SearXNG refresh.

    ``results`` maps each component to the updater's own outcome word — ``ok``
    (refreshed, or already current: the underlying commands are no-ops when
    nothing changed), ``skipped`` (the component is not in use, or the operator
    points at their own SearXNG), ``skipped-no-docker``, ``failed``, or
    ``timeout``. It is empty while a run is in flight and until the first run.
    """

    running: bool
    started_at: float | None = None
    finished_at: float | None = None
    results: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


@router.get("/update-dependencies", response_model=DependencyUpdateResponse)
async def get_dependency_update_status() -> DependencyUpdateResponse:
    """Report whether a refresh is running and how the last one went."""
    return DependencyUpdateResponse(**get_dependency_updater().status().to_dict())


@router.post("/update-dependencies", response_model=DependencyUpdateResponse)
async def start_dependency_update(request: Request) -> DependencyUpdateResponse:
    """Refresh the Camoufox browser and the bundled SearXNG image now (admin only).

    Both are pulled on a daily throttle already; this is the "I need the newer
    build now" path. The work takes minutes and blocks, so the request only
    *starts* it — poll ``GET`` for the outcome. A second request while one is in
    flight is refused rather than queued: two concurrent pulls fight over the
    same files.
    """
    await require_admin_user(request, detail="Only an admin can update dependencies.")
    updater = get_dependency_updater()
    if not updater.begin():
        return DependencyUpdateResponse(**updater.status().to_dict())
    # Fire and forget onto a worker thread: the caller polls, and awaiting here
    # would hold an HTTP request open past every reverse-proxy read timeout.
    asyncio.get_running_loop().run_in_executor(None, updater.run)
    return DependencyUpdateResponse(**updater.status().to_dict())
