"""Runtime-toggleable server settings (fork feature).

These are settings a user may flip from the Web UI at runtime — as opposed to
the operator's ``config.yaml``, which the UI never rewrites. Currently exposes
**multi-user mode** (per-user thread isolation, default on). Turning it off makes
the server show every conversation to every login/device; the write is
admin-gated (in passwordless mode the built-in ``default`` user is admin).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.gateway.deps import require_admin_user
from deerflow.config.runtime_settings import is_multi_user_mode_enabled, set_multi_user_mode

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
