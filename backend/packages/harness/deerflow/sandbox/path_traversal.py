"""The one ``..`` segment check that the sandbox tools and every provider share.

Each provider keeps its own extra checks (non-empty, absolute, under the
user-data prefix) and calls this for the traversal part, so the rule for what
counts as a parent segment cannot drift between copies.
"""

from __future__ import annotations


def reject_path_traversal(path: str, *, name_path: bool = False) -> str:
    """Return *path* with forward slashes, or raise if any segment is ``..``.

    Both separators count, so ``a\\..\\b`` is rejected on a POSIX host as well.
    Windows reserved names and trailing dots or spaces are not checked here:
    portability is enforced when a path is created, not on every read of a name
    the host already stored.

    *name_path* quotes *path* in the error message. The remote providers name
    it; the local tools keep the shorter message.

    Raises:
        PermissionError: If a segment of *path* is ``..``.
    """
    normalized = path.replace("\\", "/")
    if any(segment == ".." for segment in normalized.split("/")):
        detail = f" in '{path}'" if name_path else ""
        raise PermissionError(f"Access denied: path traversal detected{detail}")
    return normalized
