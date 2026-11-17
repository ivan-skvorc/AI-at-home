"""Folder ledger routes: which conversations created or edited shared mount folders.

``/api/folder-ledger`` serves the deployment-wide ledger the recorder
middleware fills (``agents/middlewares/folder_ledger_middleware.py``). A folder
is one top-level entry of a writable custom ``sandbox.mounts`` entry; those
mounts are shared by every conversation and user and outlive any thread, so
when the last conversation that used a folder is deleted, deleting the folder
is *offered* here, never done automatically.

- ``GET /threads/{thread_id}/folders``: the folders one conversation created,
  edited or inherited (threads:read, owner check). With multi-user mode off
  (one shared workspace) every login's touches of the conversation count, as
  every login can open it.
- ``GET /folders/{folder_id}``: one folder, the conversations that touched it
  and its capped edit log. Visible to its creator and to anyone with a touch on
  it; other users' conversations appear under a pseudonymous id, untitled.
- ``POST /orphans``: after a delete, the folders the caller's given threads
  touched that no live conversation of any user still uses. Ids of other
  users' threads select nothing, so they are ignored (in a shared workspace
  every login's touches select).
- ``DELETE /folders/{folder_id}?confirm_name=``: the confined delete
  (``deerflow.folder_ledger.fs``). Only folders a ``write_file`` or
  ``str_replace`` call was seen creating (``observed_create``), by their
  creator or an admin, on a mount that is still configured writable, still
  points at the host directory it pointed at then and whose host directory the
  Gateway sees, and only while the entry on disk is still the one recorded;
  409 when a live conversation uses the folder again. A folder that appeared
  during a shell command (``inferred_shell``) is never deleted from here: a
  ``mv`` or ``cp`` of existing data makes a name appear just like ``mkdir``.
- ``POST /folders/{folder_id}/dismiss``: keep the folder and stop offering it
  to the caller (until new activity on it). Dismissal is per user, so it never
  hides the offer from the folder's creator.

Without a SQL session factory (``database.backend: memory``) every read answers
``available: false`` with empty lists and the writes answer 503.

Fork-owned module with no upstream counterpart.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, StringConstraints

from app.gateway.authz import require_permission
from app.gateway.deps import is_admin_user
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from deerflow.config.runtime_settings import resolve_owner_scope
from deerflow.folder_ledger.fs import FolderDeleteRefused, delete_folder_entry, delete_supported, is_single_segment
from deerflow.folder_ledger.mounts import LedgerMount, configured_mounts, find_mount, host_root_key, host_root_visible
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.folder_ledger import ATTRIBUTION_OBSERVED, ATTRIBUTION_SHELL, FolderLedgerRepository
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.file_io import await_drained, run_file_io
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/folder-ledger", tags=["folder-ledger"])

#: Thread ids one orphan query accepts.
MAX_ORPHAN_THREAD_IDS = 500

FolderId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
ThreadIdItem = Annotated[str, StringConstraints(min_length=1, max_length=64)]

#: Only a tool write that saw the entry missing proves a conversation created
#: it. ``inferred_shell`` is listed but kept: a rename or move of existing data
#: makes a name appear during a command exactly as ``mkdir`` does.
_DELETABLE_ATTRIBUTIONS = frozenset({ATTRIBUTION_OBSERVED})


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class LedgerFolder(BaseModel):
    """A tracked folder as one conversation sees it."""

    id: str
    path: str = Field(description="Container path, e.g. /mnt/projects/acme.")
    name: str
    mount_path: str
    kind: str = Field(description='"dir", or "file" for a bare file at the mount root.')
    role: str | None = Field(default=None, description='"created" | "edited" | "inherited"; absent in the folder detail.')
    created_here: bool = Field(description="This conversation (in the detail: one of the caller's conversations) created the folder.")
    created_attribution: str = Field(description='"observed_create" | "preexisting" | "inferred_shell".')
    first_at: str | None
    last_at: str | None
    writes: int
    edits: int
    shell_ops: int
    other_live_threads: int = Field(description="Live conversations of any user, other than this one, that also touch the folder.")
    host_visible: bool = Field(description="The Gateway can see the mount's host directory (listing and deletion need it).")


class ThreadFoldersResponse(BaseModel):
    available: bool
    folders: list[LedgerFolder]


class FolderThread(BaseModel):
    thread_id: str = Field(description="The real id for the caller's own conversations, a stable pseudonym for others'.")
    own: bool
    title: str | None = Field(description="Only for the caller's own conversations.")
    role: str
    first_at: str | None
    last_at: str | None
    deleted: bool


class FolderEvent(BaseModel):
    thread_id: str
    run_id: str | None
    op: str
    rel_path: str = Field(description="Path relative to the mount root, starting with the folder name.")
    ts: str | None


class FolderDetailResponse(BaseModel):
    folder: LedgerFolder
    threads: list[FolderThread]
    events: list[FolderEvent] = Field(description="Newest first, capped.")


class OrphansRequest(BaseModel):
    thread_ids: list[ThreadIdItem] = Field(default_factory=list, max_length=MAX_ORPHAN_THREAD_IDS)


class OrphanFolder(BaseModel):
    id: str
    path: str
    name: str
    mount_path: str
    created_by_thread_id: str | None = Field(description="Only when one of the caller's conversations created it.")
    created_attribution: str
    last_at: str | None
    writes: int
    edits: int
    deletable: bool
    reason: str | None = Field(description="Why it cannot be deleted: preexisting, shell_inferred, not_creator, unsupported_platform, mount_unavailable, changed, host_not_visible.")


class OrphansResponse(BaseModel):
    available: bool
    orphans: list[OrphanFolder]


class DeletedResponse(BaseModel):
    deleted: bool


class DismissedResponse(BaseModel):
    dismissed: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repository() -> FolderLedgerRepository | None:
    factory = get_session_factory()
    return FolderLedgerRepository(factory) if factory is not None else None


def _require_repository() -> FolderLedgerRepository:
    repo = _repository()
    if repo is None:
        raise HTTPException(status_code=503, detail="The folder ledger requires SQL persistence.")
    return repo


def _caller_user_id(request: Request) -> str:
    """The caller, or the owner a trusted internal caller acts for."""
    return get_trusted_internal_owner_user_id(request) or get_effective_user_id()


async def _touch_scope(user_id: str) -> str | None:
    """Whose touches a read selects: the caller's, or everyone's (None) in a shared workspace.

    Mirrors the thread routes' owner scope: with multi-user mode off every
    login opens and deletes every conversation, so the ledger of a
    conversation must not depend on which login wrote it. Creator checks keep
    the real caller id. Off-loop: it stats ``runtime_settings.json``.
    """
    return await asyncio.to_thread(resolve_owner_scope, user_id, method_name="folder ledger read")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _pseudonym(thread_id: str) -> str:
    """A stable id for another user's conversation that reveals nothing about it."""
    return "other-" + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]


def _refusal(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _load_app_config():
    from deerflow.config.app_config import get_app_config

    return get_app_config()


@dataclass(frozen=True)
class _MountState:
    mount: LedgerMount | None
    host_visible: bool

    @property
    def writable(self) -> bool:
        return self.mount is not None and not self.mount.read_only


def _mount_states_sync(app_config: Any, mount_paths: list[str]) -> dict[str, _MountState]:
    """Current mount config and host visibility per mount path (blocking)."""
    mounts = configured_mounts(app_config) if app_config is not None else ()
    states: dict[str, _MountState] = {}
    for mount_path in mount_paths:
        mount = find_mount(mounts, mount_path)
        states[mount_path] = _MountState(mount=mount, host_visible=mount is not None and host_root_visible(mount))
    return states


async def _mount_states(mount_paths: list[str]) -> tuple[Any, dict[str, _MountState]]:
    """Unreadable config is not default config: every mount then reads as unavailable."""
    try:
        app_config = await asyncio.to_thread(_load_app_config)
    except Exception:
        logger.warning("folder ledger: config unreadable; treating every mount as unavailable", exc_info=True)
        app_config = None
    unique = sorted(set(mount_paths))
    if not unique:
        return app_config, {}
    return app_config, await run_file_io(_mount_states_sync, app_config, unique)


def _folder_payload(folder: dict[str, Any], *, role: str | None, created_here: bool, first_at, last_at, writes: int, edits: int, shell_ops: int, other_live_threads: int, host_visible: bool) -> LedgerFolder:
    return LedgerFolder(
        id=folder["id"],
        path=f"{folder['mount_path']}/{folder['name']}",
        name=folder["name"],
        mount_path=folder["mount_path"],
        kind=folder["kind"],
        role=role,
        created_here=created_here,
        created_attribution=folder["created_attribution"],
        first_at=_iso(first_at),
        last_at=_iso(last_at),
        writes=writes,
        edits=edits,
        shell_ops=shell_ops,
        other_live_threads=other_live_threads,
        host_visible=host_visible,
    )


def _keep_reason(attribution: str) -> str:
    return "shell_inferred" if attribution == ATTRIBUTION_SHELL else "preexisting"


def _same_host_root(folder: dict[str, Any], mount: LedgerMount) -> bool:
    """The mount still points at the host directory the folder was recorded under."""
    recorded = folder.get("host_root")
    return recorded is not None and recorded == host_root_key(mount)


def _deletability(folder: dict[str, Any], *, user_id: str, is_admin: bool, state: _MountState | None) -> tuple[bool, str | None]:
    if folder["created_attribution"] not in _DELETABLE_ATTRIBUTIONS:
        return False, _keep_reason(folder["created_attribution"])
    if folder.get("created_by_user_id") != user_id and not is_admin:
        return False, "not_creator"
    if not delete_supported():
        return False, "unsupported_platform"
    if state is None or not state.writable or state.mount is None:
        return False, "mount_unavailable"
    if not _same_host_root(folder, state.mount):
        return False, "changed"
    if not state.host_visible:
        return False, "host_not_visible"
    return True, None


async def _visible_folder(repo: FolderLedgerRepository, folder_id: str, *, user_id: str, is_admin: bool) -> dict[str, Any]:
    """The live folder, or 404 for a missing, deleted or invisible one (no existence oracle)."""
    folder = await repo.get_folder(folder_id)
    if folder is None or folder["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not is_admin and not await repo.user_can_view(folder_id=folder_id, user_id=await _touch_scope(user_id)):
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


# ---------------------------------------------------------------------------
# Thread lifecycle hooks (called best-effort by routers/threads.py)
# ---------------------------------------------------------------------------


async def tombstone_thread_touches(thread_id: str) -> int:
    """Mark a deleted thread's touches; its folders stop counting it as a user."""
    repo = _repository()
    if repo is None:
        return 0
    return await repo.tombstone_thread(thread_id)


async def inherit_thread_touches(*, parent_thread_id: str, child_thread_id: str, user_id: str) -> int:
    """Let a new branch keep using the folders its parent used."""
    repo = _repository()
    if repo is None:
        return 0
    return await repo.inherit_thread(parent_thread_id=parent_thread_id, child_thread_id=child_thread_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/folders", response_model=ThreadFoldersResponse)
@require_permission("threads", "read", owner_check=True)
async def list_thread_folders(thread_id: ThreadId, request: Request) -> ThreadFoldersResponse:
    """Folders in shared writable mounts this conversation created, edited or inherited."""
    repo = _repository()
    if repo is None:
        return ThreadFoldersResponse(available=False, folders=[])
    user_id = _caller_user_id(request)
    entries = await repo.list_thread_folders(thread_id=thread_id, user_id=await _touch_scope(user_id))
    _config, states = await _mount_states([entry["folder"]["mount_path"] for entry in entries])
    folders = []
    for entry in entries:
        folder, touch = entry["folder"], entry["touch"]
        state = states.get(folder["mount_path"])
        folders.append(
            _folder_payload(
                folder,
                role=touch["role"],
                created_here=folder["created_by_thread_id"] == thread_id,
                first_at=touch["first_at"],
                last_at=touch["last_at"],
                writes=touch["writes"],
                edits=touch["edits"],
                shell_ops=touch["shell_ops"],
                other_live_threads=entry["other_live_threads"],
                host_visible=bool(state and state.host_visible),
            )
        )
    return ThreadFoldersResponse(available=True, folders=folders)


@router.get("/folders/{folder_id}", response_model=FolderDetailResponse)
@require_permission("threads", "read")
async def get_folder(folder_id: FolderId, request: Request) -> FolderDetailResponse:
    """One folder, the conversations that worked on it and its edit log."""
    repo = _require_repository()
    user_id = _caller_user_id(request)
    await _visible_folder(repo, folder_id, user_id=user_id, is_admin=False)
    detail = await repo.folder_detail(folder_id=folder_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    folder = detail["folder"]
    _config, states = await _mount_states([folder["mount_path"]])
    state = states.get(folder["mount_path"])
    touches = detail["touches"]
    live_ids = detail["live_thread_ids"]
    threads = []
    for touch in touches:
        own = touch["user_id"] == user_id
        threads.append(
            FolderThread(
                thread_id=touch["thread_id"] if own else _pseudonym(touch["thread_id"]),
                own=own,
                title=touch["display_name"] if own and touch["thread_owner_id"] in (None, user_id) else None,
                role=touch["role"],
                first_at=_iso(touch["first_at"]),
                last_at=_iso(touch["last_at"]),
                deleted=not touch["live"],
            )
        )
    events = []
    for event in detail["events"]:
        own = event["user_id"] == user_id
        events.append(
            FolderEvent(
                thread_id=event["thread_id"] if own else _pseudonym(event["thread_id"]),
                run_id=event["run_id"] if own else None,
                op=event["op"],
                rel_path=event["rel_path"],
                ts=_iso(event["ts"]),
            )
        )
    payload = _folder_payload(
        folder,
        role=None,
        created_here=folder["created_by_user_id"] == user_id,
        first_at=folder["first_seen_at"],
        last_at=folder["last_touched_at"],
        writes=sum(touch["writes"] for touch in touches),
        edits=sum(touch["edits"] for touch in touches),
        shell_ops=sum(touch["shell_ops"] for touch in touches),
        other_live_threads=len(live_ids),
        host_visible=bool(state and state.host_visible),
    )
    return FolderDetailResponse(folder=payload, threads=threads, events=events)


@router.post("/orphans", response_model=OrphansResponse)
@require_permission("threads", "read")
async def find_orphans(body: OrphansRequest, request: Request) -> OrphansResponse:
    """Folders the given (deleted) conversations leave behind with no live user."""
    repo = _repository()
    if repo is None:
        return OrphansResponse(available=False, orphans=[])
    user_id = _caller_user_id(request)
    rows = await repo.find_orphans(thread_ids=body.thread_ids, user_id=await _touch_scope(user_id), viewer_id=user_id)
    if not rows:
        return OrphansResponse(available=True, orphans=[])
    is_admin = await is_admin_user(request)
    _config, states = await _mount_states([row["mount_path"] for row in rows])
    orphans = []
    for row in rows:
        deletable, reason = _deletability(row, user_id=user_id, is_admin=is_admin, state=states.get(row["mount_path"]))
        orphans.append(
            OrphanFolder(
                id=row["id"],
                path=f"{row['mount_path']}/{row['name']}",
                name=row["name"],
                mount_path=row["mount_path"],
                created_by_thread_id=row["created_by_thread_id"] if row["created_by_user_id"] == user_id else None,
                created_attribution=row["created_attribution"],
                last_at=_iso(row["last_at"]),
                writes=row["writes"],
                edits=row["edits"],
                deletable=deletable,
                reason=reason,
            )
        )
    return OrphansResponse(available=True, orphans=orphans)


def _protected_paths(app_config: Any, mount: LedgerMount) -> list[str]:
    """Host paths a folder delete must never contain (blocking: resolves the data root)."""
    protected = [other.host_path for other in configured_mounts(app_config) if other.container_path != mount.container_path]
    try:
        from deerflow.config.paths import get_paths

        protected.append(str(get_paths().base_dir))
    except Exception:
        logger.debug("folder ledger: DeerFlow data root unresolved; mount roots stay protected", exc_info=True)
    return protected


def _delete_entry_sync(app_config: Any, mount: LedgerMount, name: str, expected_entry: str | None) -> str:
    return delete_folder_entry(mount.host_path, name, expected_entry=expected_entry, protected_paths=_protected_paths(app_config, mount))


@router.delete("/folders/{folder_id}", response_model=DeletedResponse)
@require_permission("threads", "delete")
async def delete_folder(folder_id: FolderId, request: Request, confirm_name: Annotated[str, Query(max_length=255)] = "") -> DeletedResponse:
    """Delete a folder no live conversation uses, confined to its mount.

    Never follows a link, never removes the mount root, never retries.
    """
    repo = _require_repository()
    user_id = _caller_user_id(request)
    is_admin = await is_admin_user(request)
    folder = await _visible_folder(repo, folder_id, user_id=user_id, is_admin=is_admin)
    if folder["created_attribution"] == ATTRIBUTION_SHELL:
        raise _refusal(403, "shell_inferred", "This folder appeared during a shell command, which may have renamed or moved existing data, so it is never deleted from here.")
    if folder["created_attribution"] not in _DELETABLE_ATTRIBUTIONS:
        raise _refusal(403, "preexisting", "This folder existed before a conversation used it, so it is never deleted from here.")
    if folder["created_by_user_id"] != user_id and not is_admin:
        raise _refusal(403, "not_creator", "Only the conversation owner who created this folder, or an admin, can delete it.")
    name = folder["name"]
    if confirm_name != name:
        raise _refusal(422, "confirm_name", "confirm_name must equal the folder name.")
    if not is_single_segment(name):
        raise _refusal(422, "invalid_name", "The folder name is not a single path segment.")
    app_config, states = await _mount_states([folder["mount_path"]])
    state = states.get(folder["mount_path"])
    if state is None or not state.writable or state.mount is None:
        raise _refusal(422, "mount_unavailable", "The folder's mount is no longer configured as writable.")
    if not _same_host_root(folder, state.mount):
        raise _refusal(422, "changed", "The folder's mount now points at a different host directory than when the folder was created.")
    if not state.host_visible:
        raise _refusal(422, "host_not_visible", "The mount's host directory is not visible from the Gateway.")
    if await repo.live_thread_ids(folder_id):
        raise _refusal(409, "in_use", "A conversation uses this folder again; it was not deleted.")

    mount = state.mount

    async def remove_and_mark() -> str:
        outcome = await run_file_io(_delete_entry_sync, app_config, mount, name, folder["host_entry"])
        await repo.mark_deleted(folder_id)
        return outcome

    try:
        # Drained: a client disconnect must not leave the folder removed but
        # still listed as live, or abandon a removal halfway through.
        outcome = await await_drained(remove_and_mark())
    except FolderDeleteRefused as refused:
        raise _refusal(422, refused.code, refused.message) from None
    except OSError:
        logger.exception("folder ledger: deleting folder %s failed", folder_id)
        raise HTTPException(status_code=500, detail="Could not delete the folder.") from None
    logger.info("folder ledger: folder %s %s by user %s", folder_id, outcome, user_id)
    return DeletedResponse(deleted=True)


@router.post("/folders/{folder_id}/dismiss", response_model=DismissedResponse)
@require_permission("threads", "delete")
async def dismiss_folder(folder_id: FolderId, request: Request) -> DismissedResponse:
    """Keep the folder and stop offering it to the caller (until it is used again)."""
    repo = _require_repository()
    user_id = _caller_user_id(request)
    await _visible_folder(repo, folder_id, user_id=user_id, is_admin=await is_admin_user(request))
    await await_drained(repo.mark_dismissed(folder_id, user_id=user_id))
    return DismissedResponse(dismissed=True)
