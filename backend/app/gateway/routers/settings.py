"""Runtime-toggleable server settings (fork feature).

These are settings a user may flip from the Web UI at runtime — as opposed to
the operator's ``config.yaml``, which the UI never rewrites. Two things live
here:

* **multi-user mode** — per-user thread isolation, default on. Server-wide, so
  the write is admin-gated (in passwordless mode the built-in ``default`` user
  is admin).
* **chat tabs** — the per-user keep-alive tab strip. Per-user UI state, so it is
  scoped to the caller and needs no admin gate.
* **chat folders** — the sidebar's folder registry (id, name, display order).
  Also per-user UI state, and ungated for the same reason.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.gateway.deps import require_admin_user
from deerflow.config.runtime_settings import is_multi_user_mode_enabled, set_multi_user_mode
from deerflow.config.user_ui_state import (
    MAX_CHAT_FOLDERS,
    MAX_CHAT_TABS,
    get_chat_folders,
    get_chat_tabs,
    set_chat_folders,
    set_chat_tabs,
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


class ChatTab(BaseModel):
    """One pinned keep-alive chat tab.

    ``key`` is the stable slot identity assigned when the chat was pinned (it
    survives a new→real thread-id promotion); ``title`` is a cached display hint
    so a reloaded strip renders before the live thread title resolves.
    """

    key: str
    threadId: str  # noqa: N815 - wire shape matches the frontend tab model
    title: str | None = None


class ChatTabsResponse(BaseModel):
    """The caller's persisted keep-alive tab strip."""

    chat_tabs: list[ChatTab]


class ChatTabsUpdate(BaseModel):
    """Replacement tab set. Over-long lists are truncated, not rejected."""

    chat_tabs: list[ChatTab] = Field(default_factory=list)


@router.get("/chat-tabs", response_model=ChatTabsResponse)
async def get_chat_tabs_setting() -> ChatTabsResponse:
    """Return the caller's pinned chat tabs (durable across browsers/devices).

    ``localStorage`` alone lost this set whenever the browser cleared site data,
    evicted storage for an insecure origin, or the app was reopened on a
    different origin than the one that pinned them — all of which read to a user
    as "my tabs were forgotten after a restart".
    """
    tabs = await asyncio.to_thread(get_chat_tabs, get_effective_user_id())
    return ChatTabsResponse(chat_tabs=[ChatTab(**tab) for tab in tabs])


@router.put("/chat-tabs", response_model=ChatTabsResponse)
async def update_chat_tabs_setting(body: ChatTabsUpdate) -> ChatTabsResponse:
    """Replace the caller's pinned chat tabs; returns the persisted value.

    An empty list is a real value (the user closed their last tab), so it is
    stored rather than ignored. The store caps the list at
    ``MAX_CHAT_TABS`` and drops malformed entries, so the response is the
    authoritative post-write state the client should adopt.
    """
    payload = [tab.model_dump(exclude_none=True) for tab in body.chat_tabs[: MAX_CHAT_TABS * 4]]
    tabs = await asyncio.to_thread(set_chat_tabs, get_effective_user_id(), payload)
    return ChatTabsResponse(chat_tabs=[ChatTab(**tab) for tab in tabs])


class ChatFolder(BaseModel):
    """One sidebar folder: a stable id and the name the user typed.

    Membership is deliberately *not* here — a conversation records its folder in
    its own ``deerflow_folder`` thread metadata. That split is what makes a
    rename one write instead of one per conversation in the folder.
    """

    id: str
    name: str


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
    stored rather than ignored. The store caps the list at ``MAX_CHAT_FOLDERS``
    and drops malformed entries, so the response is the authoritative post-write
    state the client should adopt.

    Deleting a folder here never deletes a conversation: a thread still pointing
    at a folder that no longer exists falls back to the sidebar's root list.
    """
    payload = [folder.model_dump() for folder in body.chat_folders[: MAX_CHAT_FOLDERS * 4]]
    folders = await asyncio.to_thread(set_chat_folders, get_effective_user_id(), payload)
    return ChatFoldersResponse(chat_folders=[ChatFolder(**folder) for folder in folders])
