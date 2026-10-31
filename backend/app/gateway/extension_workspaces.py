"""Copy a conversation's workspace into an extension's child thread, and merge it back.

Extension API 0.2.10 (``AgentRuns.copy_workspace`` / ``merge_workspace``). Both
directions are plain host file copies between two thread user-data roots of one
user, so they need thread data that the sandbox sees through a host mount; a
synced sandbox (remote AIO without mounts, cloud sandboxes) fails closed.

Every walk opens directories and files relative to an already-open directory
descriptor with ``O_NOFOLLOW``: a sandbox process that swaps a path component
for a symlink mid-copy cannot redirect a read or a write outside the two roots.
Symlinks and special files are skipped, never followed.

A merge applies a child's file only while the parent still holds the version
the child started from (or, for a new path, still lacks it). Anything else is a
conflict and stays untouched; deletions are reported, never applied; uploads are
never written back. Merges into one parent are serialized in-process.
"""

from __future__ import annotations

import hashlib
import os
import stat
import threading
from collections.abc import Mapping

from deerflow_extension_api.agent_runs import AgentRunError

from deerflow.config.paths import get_paths

MAX_FILES = 1000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PATH_CHARS = 1024

#: User-data areas a snapshot copies, and the subset a merge may write back.
COPIED_AREAS = ("workspace", "uploads")
MERGED_AREAS = ("workspace", "outputs")

_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)

_merge_guard = threading.Lock()
_merge_locks: dict[tuple[str, str], threading.Lock] = {}


def require_mounted_thread_data() -> None:
    """Fail closed unless the sandbox reads thread data straight from the host."""
    from deerflow.sandbox.sandbox_provider import get_sandbox_provider

    if os.name != "posix" or not bool(getattr(get_sandbox_provider(), "uses_thread_data_mounts", False)):
        raise AgentRunError(409, "Shared workspaces need host-mounted thread data")


def _user_data_root(user_id: str, thread_id: str) -> str:
    return str(get_paths().sandbox_user_data_dir(thread_id, user_id=user_id))


def _open_root(path: str, *, create: bool) -> int | None:
    if create:
        os.makedirs(path, exist_ok=True)
    try:
        return os.open(path, _DIR_FLAGS)
    except FileNotFoundError:
        return None


class _Budget:
    def __init__(self) -> None:
        self.files = 0
        self.bytes = 0

    def charge(self, size: int) -> None:
        self.files += 1
        self.bytes += size
        if self.files > MAX_FILES or size > MAX_FILE_BYTES or self.bytes > MAX_TOTAL_BYTES:
            raise AgentRunError(422, f"Workspace exceeds {MAX_FILES} files, {MAX_FILE_BYTES // 2**20} MiB per file or {MAX_TOTAL_BYTES // 2**20} MiB in total")


def _read_tree(root_fd: int, area: str, budget: _Budget) -> dict[str, tuple[str, bytes, int]]:
    """Map ``area/relative/path`` to (sha256, bytes, mode) for every regular file."""
    files: dict[str, tuple[str, bytes, int]] = {}
    try:
        top = os.open(area, _DIR_FLAGS, dir_fd=root_fd)
    except (FileNotFoundError, NotADirectoryError):
        return files
    except OSError:
        # A symlinked or unreadable area root is skipped like any other link.
        return files

    def walk(directory: int, prefix: str) -> None:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                name = entry.name
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    try:
                        child = os.open(name, _DIR_FLAGS, dir_fd=directory)
                    except OSError:
                        continue
                    try:
                        walk(child, f"{prefix}{name}/")
                    finally:
                        os.close(child)
                elif entry.is_file(follow_symlinks=False):
                    path = f"{prefix}{name}"
                    if len(path) > MAX_PATH_CHARS:
                        continue
                    try:
                        fd = os.open(name, _FILE_FLAGS, dir_fd=directory)
                    except OSError:
                        continue
                    with os.fdopen(fd, "rb") as source:
                        info = os.fstat(source.fileno())
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        budget.charge(info.st_size)
                        content = source.read(MAX_FILE_BYTES + 1)
                        if len(content) != info.st_size:
                            raise AgentRunError(409, "Workspace changed while it was being copied")
                    files[path] = (hashlib.sha256(content).hexdigest(), content, stat.S_IMODE(info.st_mode))

    try:
        walk(top, f"{area}/")
    finally:
        os.close(top)
    return files


def _valid_relative(path: object, areas: tuple[str, ...]) -> bool:
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS or "\x00" in path:
        return False
    parts = path.split("/")
    return parts[0] in areas and len(parts) >= 2 and all(part not in ("", ".", "..") for part in parts)


def _open_parent_dirs(root_fd: int, path: str) -> tuple[int, str]:
    """Open (creating) every directory above ``path`` without following links."""
    parts = path.split("/")
    directory = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o755, dir_fd=directory)
            except FileExistsError:
                pass
            following = os.open(part, _DIR_FLAGS, dir_fd=directory)
            os.close(directory)
            directory = following
    except BaseException:
        os.close(directory)
        raise
    return directory, parts[-1]


def _write_file(root_fd: int, path: str, content: bytes, mode: int) -> None:
    directory, name = _open_parent_dirs(root_fd, path)
    temporary = f".deerflow-merge-{os.getpid()}-{threading.get_ident()}-{name}"[:255]
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode or 0o644, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            # rename(2) replaces the directory entry itself, never a link's target.
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            raise
    finally:
        os.close(directory)


def _current_digest(root_fd: int, path: str) -> str | None:
    parts = path.split("/")
    directory = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            following = os.open(part, _DIR_FLAGS, dir_fd=directory)
            os.close(directory)
            directory = following
        fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        os.close(directory)
        return None
    except OSError:
        # A link or special file where a regular file was expected: never ours to overwrite.
        os.close(directory)
        return "unreadable"
    os.close(directory)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            return "unreadable"
        return hashlib.sha256(source.read(MAX_FILE_BYTES + 1)).hexdigest()


def copy_workspace(user_id: str, source_thread_id: str, thread_id: str) -> dict[str, str]:
    """Copy the source's workspace and uploads into ``thread_id``; return path -> sha256."""
    require_mounted_thread_data()
    if source_thread_id == thread_id:
        raise AgentRunError(422, "A workspace cannot be copied onto itself")
    source_fd = _open_root(_user_data_root(user_id, source_thread_id), create=False)
    budget = _Budget()
    files: dict[str, tuple[str, bytes, int]] = {}
    if source_fd is not None:
        try:
            for area in COPIED_AREAS:
                files.update(_read_tree(source_fd, area, budget))
        finally:
            os.close(source_fd)
    target_fd = _open_root(_user_data_root(user_id, thread_id), create=True)
    assert target_fd is not None
    try:
        for path, (_, content, mode) in files.items():
            _write_file(target_fd, path, content, mode)
    finally:
        os.close(target_fd)
    return {path: digest for path, (digest, _, _) in files.items()}


def _merge_lock(user_id: str, thread_id: str) -> threading.Lock:
    with _merge_guard:
        lock = _merge_locks.get((user_id, thread_id))
        if lock is None:
            if len(_merge_locks) >= 1024:
                for key in [key for key, value in _merge_locks.items() if not value.locked()][:512]:
                    _merge_locks.pop(key, None)
            lock = _merge_locks[(user_id, thread_id)] = threading.Lock()
        return lock


def merge_workspace(user_id: str, thread_id: str, into_thread_id: str, base: Mapping[str, str]) -> tuple[list[str], list[str], list[str]]:
    """Apply the child's workspace/output edits onto the parent; (applied, conflicts, skipped)."""
    require_mounted_thread_data()
    if thread_id == into_thread_id:
        raise AgentRunError(422, "A workspace cannot be merged into itself")
    if not isinstance(base, Mapping) or len(base) > MAX_FILES:
        raise AgentRunError(422, "Invalid workspace snapshot")
    for path, digest in base.items():
        if not _valid_relative(path, COPIED_AREAS) or not isinstance(digest, str) or len(digest) != 64:
            raise AgentRunError(422, "Invalid workspace snapshot")
    child_fd = _open_root(_user_data_root(user_id, thread_id), create=False)
    if child_fd is None:
        return [], [], sorted(path for path in base if path.split("/", 1)[0] in MERGED_AREAS)
    budget = _Budget()
    try:
        child: dict[str, tuple[str, bytes, int]] = {}
        for area in MERGED_AREAS:
            child.update(_read_tree(child_fd, area, budget))
    finally:
        os.close(child_fd)
    applied: list[str] = []
    conflicts: list[str] = []
    skipped = sorted(path for path in base if path.split("/", 1)[0] in MERGED_AREAS and path not in child)
    with _merge_lock(user_id, into_thread_id):
        parent_fd = _open_root(_user_data_root(user_id, into_thread_id), create=True)
        assert parent_fd is not None
        try:
            for path in sorted(child):
                digest, content, mode = child[path]
                original = base.get(path)
                if digest == original:
                    continue
                current = _current_digest(parent_fd, path)
                if current == digest:
                    continue
                if current != original:
                    conflicts.append(path)
                    continue
                _write_file(parent_fd, path, content, mode)
                applied.append(path)
        finally:
            os.close(parent_fd)
    return applied, conflicts, skipped
