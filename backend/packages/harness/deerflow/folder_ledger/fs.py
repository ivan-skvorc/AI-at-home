"""Confined deletion of one tracked folder below a mount's host root.

Blocking: call through ``run_file_io`` (and ``await_drained``, so a cancelled
request still waits for the removal it started).

The delete opens the mount root as a directory descriptor and works relative
to it: the entry is checked with ``lstat`` (never following a link) and removed
with ``shutil.rmtree(name, dir_fd=...)``, which re-checks the entry against the
``lstat`` result and refuses a symbolic link, so a component swapped for a link
after the check cannot redirect the removal out of the mount. Only POSIX
platforms whose ``rmtree`` resists symlink attacks are supported; elsewhere the
delete is refused rather than done by path.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Sequence
from typing import Literal

DeleteOutcome = Literal["deleted", "missing"]

# ``os.lstat(..., dir_fd=)`` is ``os.stat(..., follow_symlinks=False)``, so the
# capability sets name ``os.stat``.
_SUPPORTED = os.name == "posix" and bool(getattr(shutil.rmtree, "avoids_symlink_attacks", False)) and {os.open, os.stat, os.unlink} <= os.supports_dir_fd and os.stat in os.supports_follow_symlinks


class FolderDeleteRefused(Exception):
    """The delete was refused before anything was removed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def delete_supported() -> bool:
    return _SUPPORTED


def is_single_segment(name: object) -> bool:
    """A name that can only address one entry directly below the root."""
    return isinstance(name, str) and name not in ("", ".", "..") and "/" not in name and "\\" not in name and "\x00" not in name


def _real(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _protects(target: str, protected: str) -> bool:
    """Whether removing *target* would remove *protected* (equal or below it)."""
    return protected == target or protected.startswith(target.rstrip(os.sep) + os.sep)


def delete_folder_entry(host_root: str, name: str, *, protected_paths: Sequence[str] = ()) -> DeleteOutcome:
    """Remove ``host_root/name``; ``"missing"`` when it is already gone.

    Raises :class:`FolderDeleteRefused` (nothing removed) when the platform is
    unsupported, the name is not a single segment, the host root cannot be
    opened, the entry is a link or a special file, or removing it would remove
    one of *protected_paths* (another mount's host root, DeerFlow's own data).
    """
    if not _SUPPORTED:
        raise FolderDeleteRefused("unsupported_platform", "Deleting shared folders is not supported on this platform.")
    if not is_single_segment(name):
        raise FolderDeleteRefused("invalid_name", "The folder name is not a single path segment.")
    try:
        root_fd = os.open(host_root, os.O_RDONLY | os.O_DIRECTORY)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        raise FolderDeleteRefused("host_not_visible", "The mount's host directory is not visible from the Gateway.") from None
    try:
        try:
            info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return "missing"
        if stat.S_ISLNK(info.st_mode):
            raise FolderDeleteRefused("link", "The folder is a link; links are never followed or removed.")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise FolderDeleteRefused("unsupported_type", "Only directories and regular files can be deleted.")
        target = os.path.join(_real(host_root), os.path.normcase(name))
        for protected in protected_paths:
            if protected and _protects(target, _real(protected)):
                raise FolderDeleteRefused("protected", "The folder contains another mount or DeerFlow's own data.")
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(name, dir_fd=root_fd)
        else:
            os.unlink(name, dir_fd=root_fd)
        return "deleted"
    finally:
        os.close(root_fd)
