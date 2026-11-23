"""GET one finalized file of a design, for the page's viewer.

The page loads the finalized GLB through this route instead of the host's
artifact route because it only knows the design: the route maps the design to
its conversation for the signed-in owner, allows only a basename the version's
``final.files`` lists, and reads the bytes through the host's AgentRuns handle,
which checks thread ownership again and bounds the read (2 MiB).
"""

from __future__ import annotations

import asyncio
import re

from deerflow_extension_api import AgentRunError, require_agent_runs
from deerflow_extension_api.auth import resolve_principal
from fastapi import APIRouter, HTTPException, Request, Response

from .constants import ID, NAMESPACE
from .store import NotFound, Store

FILE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,254}")
MEDIA_TYPES = {
    ".glb": "model/gltf-binary",
    ".stl": "model/stl",
    ".3mf": "model/3mf",
    ".step": "model/step",
    ".png": "image/png",
    ".json": "application/json",
    ".py": "text/plain; charset=utf-8",
}


def valid_name(name: str) -> bool:
    return bool(FILE_NAME.fullmatch(name)) and ".." not in name


def build_router(store: Store) -> APIRouter:
    router = APIRouter(prefix=f"/api/extensions/{NAMESPACE}", tags=[NAMESPACE])

    @router.get("/designs/{design_id}/files/{name}")
    async def design_file(design_id: str, name: str, request: Request) -> Response:
        if not ID.fullmatch(design_id) or not valid_name(name):
            raise HTTPException(404, "File unavailable")
        principal = resolve_principal(request)
        if principal is None:
            raise HTTPException(401, "Authentication required")
        try:
            design = await asyncio.to_thread(store.get_design, principal.user_id, design_id)
            versions = await asyncio.to_thread(store.versions, principal.user_id, design_id)
        except NotFound:
            raise HTTPException(404, "File unavailable") from None
        if not any(name in ((version.get("final") or {}).get("files") or []) for version in versions):
            raise HTTPException(404, "File unavailable")
        try:
            runs = require_agent_runs(request).for_plugin(NAMESPACE)
        except NotImplementedError:
            raise HTTPException(503, "File reads need a signed-in browser session") from None
        try:
            content = await runs.read_artifact(thread_id=design["thread_id"], path=f"/mnt/user-data/outputs/{name}")
        except AgentRunError as exc:
            raise HTTPException(exc.status_code, "File unavailable") from None
        suffix = name[name.rfind(".") :].lower() if "." in name else ""
        return Response(
            content,
            media_type=MEDIA_TYPES.get(suffix, "application/octet-stream"),
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    return router
