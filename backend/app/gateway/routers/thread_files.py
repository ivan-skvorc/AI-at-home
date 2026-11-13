"""Read-only directory listing of a thread's sandbox user-data tree.

``GET /api/threads/{thread_id}/files?path=/mnt/user-data/...`` backs the file
explorer: it lists one directory at or below the virtual root
``/mnt/user-data`` (on the host ``users/{user_id}/threads/{thread_id}/user-data``).
Files are opened through the existing artifacts route, so this module never
reads file contents.

Confinement mirrors ``get_artifact``. The requested path is normalized
lexically before the prefix check, because an encoded ``..`` reaches the
route already decoded; ``resolve_thread_virtual_path`` then resolves symlinks
and confines the result to the thread's ``user-data`` directory (403 on an
escape). The sandbox can still write below ``user-data`` after that check, so
the checked directory is opened one component at a time from the user-data
root, each relative to its parent's descriptor without following a link, and
is scanned through that descriptor: a component swapped for a link fails the
request (404) instead of leading the scan out of the thread. Windows has no
descriptor-relative opens and lists by path. Entries are classified without
following links, so a symlink is reported as ``"symlink"`` and is only
entered by a new request that is confined again.

Fork-owned module with no upstream counterpart, so upstream syncs stay
conflict-free.
"""

import errno
import os
import posixpath
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.path_utils import resolve_thread_virtual_path
from app.gateway.routers.artifacts import _ARTIFACT_EDIT_TEMP_PREFIX
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, make_safe_user_id
from deerflow.uploads.manager import is_upload_staging_file
from deerflow.utils.file_io import run_file_io
from deerflow.utils.thread_id import ThreadId

router = APIRouter(prefix="/api", tags=["thread-files"])

# Entries one response carries; a larger directory reports ``truncated``.
MAX_LISTED_ENTRIES = 500
# Visible entries one request scans before it stops, so a directory with
# millions of files cannot pin a file-IO worker. ``total`` is then this lower
# bound rather than an exact count.
MAX_SCANNED_ENTRIES = 10_000

_USER_DATA_PREFIX = VIRTUAL_PATH_PREFIX.lstrip("/")
# Failures meaning no directory can be reached at the path: a missing
# component, a file used as a directory, a link where the walk follows none
# (ENOTDIR on Linux, ELOOP elsewhere), or a name too long for the filesystem.
_MISSING_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.ENAMETOOLONG})
# Descriptor-relative opens and a descriptor scan keep the listing on the
# directory that was checked. Windows has neither and lists by path.
_LISTS_BY_DESCRIPTOR = hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and {os.open, os.stat} <= os.supports_dir_fd and os.scandir in os.supports_fd
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_NO_FOLLOW_DIRECTORY_FLAGS = _DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0)

EntryKind = Literal["directory", "file", "symlink", "other"]


class ThreadDirectoryEntry(BaseModel):
    """One child of the listed directory."""

    name: str
    path: str = Field(description="Virtual path of the entry (/mnt/user-data/...), not URL-encoded.")
    kind: EntryKind = Field(description="Classified without following links: a link to a directory is a symlink.")
    size: int | None = Field(description="Size in bytes for regular files; null for every other kind.")
    modified_at: str | None = Field(description="ISO-8601 UTC time of the entry's own (lstat) mtime, to the second.")


class ThreadDirectoryListing(BaseModel):
    """A sorted, capped listing of one user-data directory."""

    path: str = Field(description="Normalized virtual path of the listed directory, without a trailing slash.")
    exists: bool = Field(description="False only for the root before the thread's user-data exists.")
    entries: list[ThreadDirectoryEntry] = Field(description="Directories first, then every other kind, each by case-insensitive name.")
    truncated: bool = Field(description="True when entries holds fewer entries than the directory has.")
    total: int = Field(description="Visible entries in the directory; a lower bound once the scan bound is reached.")


def _normalize_directory_path(raw_path: str) -> str:
    """Return *raw_path* as a canonical ``/mnt/user-data[/...]`` virtual path.

    ``.``/``..`` segments and duplicate slashes collapse before the prefix
    check, so ``user-data/../x`` is rejected as outside instead of passing a
    raw string-prefix test and leaving the resolver to catch it.

    Raises:
        HTTPException: 400 when the path is not ``/mnt/user-data`` or below it.
    """
    stripped = posixpath.normpath(raw_path.lstrip("/")).lstrip("/")
    if stripped != _USER_DATA_PREFIX and not stripped.startswith(f"{_USER_DATA_PREFIX}/"):
        raise HTTPException(status_code=400, detail=f"Only directories under {VIRTUAL_PATH_PREFIX} can be listed")
    return f"/{stripped}"


def _is_transient_internal_file(name: str) -> bool:
    """Whether *name* is an in-flight Gateway file rather than thread content.

    Upload staging files and artifact-edit temporaries exist only until the
    write they belong to publishes or fails. Ordinary dotfiles are content.
    """
    return is_upload_staging_file(name) or name.startswith(_ARTIFACT_EDIT_TEMP_PREFIX)


def _entry_kind(entry: os.DirEntry[str]) -> EntryKind:
    try:
        # A Windows junction redirects like a symlink and is reported as one.
        if entry.is_symlink() or entry.is_junction():
            return "symlink"
        if entry.is_dir(follow_symlinks=False):
            return "directory"
        if entry.is_file(follow_symlinks=False):
            return "file"
    except OSError:
        pass
    return "other"


def _display_name(name: str) -> str:
    """Return *name* in a form JSON can carry.

    Bytes that are not UTF-8 decode to lone surrogates, which make JSON
    serialization fail for the whole listing. They are shown as U+FFFD
    instead; such an entry is visible but cannot be opened by its name.
    """
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        try:
            return os.fsencode(name).decode("utf-8", "replace")
        except UnicodeError:
            return name.encode("utf-8", "replace").decode("utf-8")
    return name


def _modified_at(entry_stat: os.stat_result) -> str | None:
    try:
        return datetime.fromtimestamp(entry_stat.st_mtime, tz=UTC).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _build_entry(parent: str, kind: EntryKind, entry: os.DirEntry[str], name: str) -> ThreadDirectoryEntry:
    try:
        entry_stat = entry.stat(follow_symlinks=False)
    except OSError:
        entry_stat = None
    size = None
    modified_at = None
    if entry_stat is not None:
        if kind == "file" and stat.S_ISREG(entry_stat.st_mode):
            size = entry_stat.st_size
        modified_at = _modified_at(entry_stat)
    return ThreadDirectoryEntry(name=name, path=f"{parent}/{name}", kind=kind, size=size, modified_at=modified_at)


def _not_found(virtual_path: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Directory not found: {virtual_path}")


def _permission_denied(virtual_path: str) -> HTTPException:
    return HTTPException(status_code=403, detail=f"Permission denied: {virtual_path}")


def _missing_directory(virtual_path: str) -> ThreadDirectoryListing:
    # Only the root may be absent: a thread has no user-data until its first
    # run or upload. Any other missing directory is an error.
    if virtual_path == VIRTUAL_PATH_PREFIX:
        return ThreadDirectoryListing(path=virtual_path, exists=False, entries=[], truncated=False, total=0)
    raise _not_found(virtual_path)


def _require_directory(mode: int, virtual_path: str) -> None:
    if stat.S_ISLNK(mode):
        # A link survives resolution only when it loops (newer Pythons no
        # longer raise for that) or when it was swapped in after the check.
        raise _not_found(virtual_path)
    if not stat.S_ISDIR(mode):
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {virtual_path}")


def _open_checked_directory(base: Path, directory: Path, virtual_path: str) -> int:
    """Open *directory*, already confined below *base*, without following a link.

    Each component opens relative to its parent's descriptor, so a component
    replaced by a link after the check raises instead of leading outside the
    thread's user-data. The caller closes the returned descriptor.
    """
    names = (base.name, *directory.relative_to(base).parts)
    parent = os.open(base.parent, _DIRECTORY_FLAGS)
    try:
        for name in names[:-1]:
            child = os.open(name, _NO_FOLLOW_DIRECTORY_FLAGS, dir_fd=parent)
            os.close(parent)
            parent = child
        _require_directory(os.stat(names[-1], dir_fd=parent, follow_symlinks=False).st_mode, virtual_path)
        return os.open(names[-1], _NO_FOLLOW_DIRECTORY_FLAGS, dir_fd=parent)
    finally:
        os.close(parent)


def _list_directory(thread_id: str, virtual_path: str, user_id: str | None) -> ThreadDirectoryListing:
    """Worker-thread body of ``list_thread_files``: resolve, check and scan.

    Like ``get_artifact``, confinement is decided when the path is resolved.
    The scan then reads the directory that was checked, through a descriptor
    walked down from the user-data root, and classifies its entries without
    following them.
    """
    try:
        base = resolve_thread_virtual_path(thread_id, VIRTUAL_PATH_PREFIX, user_id=user_id)
        directory = resolve_thread_virtual_path(thread_id, virtual_path, user_id=user_id)
    except (RuntimeError, OSError):
        # Python 3.12's Path.resolve() raises RuntimeError on a symlink loop,
        # and OSError when a link changes while it is being resolved; no
        # directory can be reached through either.
        raise _not_found(virtual_path) from None

    try:
        if not _LISTS_BY_DESCRIPTOR:
            _require_directory(os.lstat(directory).st_mode, virtual_path)
            return _scan(directory, virtual_path)
        directory_fd = _open_checked_directory(base, directory, virtual_path)
        try:
            # DirEntry.stat() reads through this descriptor, so it stays open
            # until every entry is built.
            return _scan(directory_fd, virtual_path)
        finally:
            os.close(directory_fd)
    except PermissionError:
        raise _permission_denied(virtual_path) from None
    except OSError as exc:
        # Missing, or removed or replaced while it was opened or scanned.
        if exc.errno in _MISSING_ERRNOS:
            return _missing_directory(virtual_path)
        raise


def _scan(directory: int | Path, virtual_path: str) -> ThreadDirectoryListing:
    visible: list[tuple[EntryKind, os.DirEntry[str], str]] = []
    scan_capped = False
    with os.scandir(directory) as scan:
        for entry in scan:
            if _is_transient_internal_file(entry.name):
                continue
            if len(visible) == MAX_SCANNED_ENTRIES:
                scan_capped = True
                break
            visible.append((_entry_kind(entry), entry, _display_name(entry.name)))

    visible.sort(key=lambda item: (item[0] != "directory", item[2].casefold(), item[2]))
    # Entries beyond the cap are never stat-ed.
    entries = [_build_entry(virtual_path, kind, entry, name) for kind, entry, name in visible[:MAX_LISTED_ENTRIES]]
    return ThreadDirectoryListing(
        path=virtual_path,
        exists=True,
        entries=entries,
        truncated=scan_capped or len(visible) > MAX_LISTED_ENTRIES,
        total=len(visible),
    )


@router.get(
    "/threads/{thread_id}/files",
    response_model=ThreadDirectoryListing,
    summary="List Thread Files",
    description="List one directory of the thread's sandbox user-data tree (`/mnt/user-data` and below). Directories sort first; links are reported, never followed. Open files with the artifacts route.",
)
@require_permission("threads", "read", owner_check=True)
async def list_thread_files(
    thread_id: ThreadId,
    request: Request,
    path: Annotated[str, Query(description="Virtual directory path at or below /mnt/user-data, with or without the leading slash.")] = VIRTUAL_PATH_PREFIX,
) -> ThreadDirectoryListing:
    """List a directory of the thread's user-data tree for the file explorer.

    Raises:
        HTTPException:
            - 400 if the path is outside ``/mnt/user-data`` or is not a directory
            - 403 if a symlink or traversal would escape the thread's user-data
            - 404 if a directory below the root does not exist
    """
    virtual_path = _normalize_directory_path(path)
    # Same owner override as get_artifact: a trusted internal caller acting for
    # a thread's owner resolves under that owner's make_safe_user_id bucket;
    # browser/API callers get None and fall back to the effective user.
    raw_owner_user_id = get_trusted_internal_owner_user_id(request)
    owner_user_id = make_safe_user_id(raw_owner_user_id) if raw_owner_user_id else None
    return await run_file_io(_list_directory, thread_id, virtual_path, owner_user_id)
