"""Which tool paths fall inside a tracked folder, and what the Gateway can see of it.

A tracked *folder* is the first path segment below the ``container_path`` of a
**writable** custom ``sandbox.mounts`` entry, for example ``/mnt/projects/acme``
under a ``/mnt/projects`` mount. A bare file at the mount root is tracked too,
as ``kind="file"``. Never tracked:

- the conversation's own ``/mnt/user-data`` (deleted with the thread), the ACP
  workspace and the skills mount, which the sandbox reserves;
- read-only mounts, including a read-only mount nested inside a writable one
  (the longest matching mount decides, as in the sandbox);
- the mount root itself.

Mounts only map host directories for providers that honor them: the local
provider, and the AIO provider in local-container mode. With an external AIO
``base_url`` or a provisioner the mounts are ignored, so nothing is tracked.

Everything here except :func:`probe_entry` and :func:`host_root_visible` is
pure: no filesystem access, safe on the event loop.
"""

from __future__ import annotations

import os
import posixpath
import re
import stat
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH

USER_DATA_PREFIX = "/mnt/user-data"
ACP_WORKSPACE_PREFIX = "/mnt/acp-workspace"
# The skills literal is owned by deerflow.constants
# (tests/test_skill_container_path_defaults.py).
DEFAULT_SKILLS_PREFIX = DEFAULT_SKILLS_CONTAINER_PATH

#: Database limits of the ledger columns (see persistence/folder_ledger/model.py).
MAX_MOUNT_PATH_CHARS = 512
MAX_NAME_CHARS = 255
MAX_REL_PATH_CHARS = 1024
#: Distinct folders one bash command can be credited with.
MAX_BASH_REFERENCES = 16

EntryState = Literal["missing", "dir", "file", "other", "link"]

# A path token in a shell command ends at whitespace, a quote, an operator, an
# expansion or a glob character: what follows such a character is not a literal
# path segment the ledger can attribute.
_TOKEN_TAIL = r"(/[^\s'\"`;|&<>()$*?\[\]{}\\]*)"
_TOKEN_LEAD = r"(?<![A-Za-z0-9_.~/-])"


@dataclass(frozen=True)
class LedgerMount:
    """One configured custom mount, as the sandbox honors it."""

    container_path: str
    host_path: str
    read_only: bool


@dataclass(frozen=True)
class FolderRef:
    """A tracked folder a tool path points into."""

    mount: LedgerMount
    name: str
    #: "dir" when the path continues below the folder, else "file".
    kind: str
    #: Path relative to the mount root, starting with ``name``.
    rel_path: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.mount.container_path, self.name)

    @property
    def container_path(self) -> str:
        return f"{self.mount.container_path}/{self.name}"


def mounts_effective(sandbox_config: Any) -> bool:
    """Whether the configured provider maps ``sandbox.mounts`` to host directories."""
    use = str(getattr(sandbox_config, "use", "") or "")
    provider = use.rsplit(":", 1)[-1].rsplit(".", 1)[-1]
    if provider == "LocalSandboxProvider":
        return True
    if provider == "AioSandboxProvider":
        return not getattr(sandbox_config, "base_url", None) and not getattr(sandbox_config, "provisioner_url", None)
    return False


def _reserved_prefixes(app_config: Any) -> tuple[str, ...]:
    skills = getattr(getattr(app_config, "skills", None), "container_path", None)
    skills_prefix = str(skills).rstrip("/") if isinstance(skills, str) and skills.strip("/") else DEFAULT_SKILLS_PREFIX
    return (USER_DATA_PREFIX, ACP_WORKSPACE_PREFIX, skills_prefix)


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _host_path_is_absolute(host_path: str) -> bool:
    return PurePosixPath(host_path).is_absolute() or PureWindowsPath(host_path).is_absolute()


def _normalize_virtual(path: str) -> str | None:
    """Collapse ``.`` and duplicate slashes; reject relative paths, ``..`` and NULs."""
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        return None
    if ".." in path.split("/"):
        return None
    normalized = posixpath.normpath(path)
    if normalized.startswith("//"):
        normalized = "/" + normalized.lstrip("/")
    return normalized


def configured_mounts(app_config: Any) -> tuple[LedgerMount, ...]:
    """Every custom mount the sandbox honors, read-only ones included.

    Read-only mounts stay in the list so that a read-only mount nested inside a
    writable one still wins the longest-prefix match and keeps its paths
    untracked. Mounts the providers skip (relative paths, reserved container
    paths) are left out the same way. Pure: reads the config object only.
    """
    sandbox = getattr(app_config, "sandbox", None)
    if sandbox is None or not mounts_effective(sandbox):
        return ()
    reserved = _reserved_prefixes(app_config)
    mounts: list[LedgerMount] = []
    for mount in getattr(sandbox, "mounts", None) or []:
        container_path = _normalize_virtual(str(getattr(mount, "container_path", "") or ""))
        host_path = str(getattr(mount, "host_path", "") or "")
        if container_path is None or container_path == "/" or not host_path or not _host_path_is_absolute(host_path):
            continue
        if len(container_path) > MAX_MOUNT_PATH_CHARS or any(_under(container_path, prefix) for prefix in reserved):
            continue
        mounts.append(LedgerMount(container_path=container_path, host_path=host_path, read_only=bool(getattr(mount, "read_only", False))))
    return tuple(mounts)


def writable_mounts(mounts: tuple[LedgerMount, ...]) -> tuple[LedgerMount, ...]:
    return tuple(mount for mount in mounts if not mount.read_only)


def find_mount(mounts: tuple[LedgerMount, ...], container_path: str) -> LedgerMount | None:
    """The configured mount with exactly this container path, if any."""
    for mount in mounts:
        if mount.container_path == container_path:
            return mount
    return None


def classify_path(path: str, mounts: tuple[LedgerMount, ...], *, reserved: tuple[str, ...] = (USER_DATA_PREFIX, ACP_WORKSPACE_PREFIX, DEFAULT_SKILLS_PREFIX)) -> FolderRef | None:
    """The tracked folder a virtual tool path points into, or None."""
    normalized = _normalize_virtual(path)
    if normalized is None or any(_under(normalized, prefix) for prefix in reserved):
        return None
    best: LedgerMount | None = None
    for mount in mounts:
        if _under(normalized, mount.container_path) and (best is None or len(mount.container_path) > len(best.container_path)):
            best = mount
    if best is None or best.read_only:
        return None
    rel = normalized[len(best.container_path) + 1 :]
    if not rel:
        return None  # the mount root itself is never a folder
    name, _, rest = rel.partition("/")
    if name in ("", ".", "..") or len(name) > MAX_NAME_CHARS:
        return None
    return FolderRef(mount=best, name=name, kind="dir" if rest else "file", rel_path=rel[:MAX_REL_PATH_CHARS])


class FolderClassifier:
    """Classifies tool paths against one config snapshot (pure after construction)."""

    def __init__(self, app_config: Any) -> None:
        self.mounts = configured_mounts(app_config)
        self.reserved = _reserved_prefixes(app_config)
        writable = writable_mounts(self.mounts)
        self._bash_patterns = tuple(re.compile(_TOKEN_LEAD + "(" + re.escape(mount.container_path) + ")" + _TOKEN_TAIL) for mount in writable)

    @property
    def enabled(self) -> bool:
        return bool(writable_mounts(self.mounts))

    def classify(self, path: Any) -> FolderRef | None:
        if not isinstance(path, str):
            return None
        return classify_path(path, self.mounts, reserved=self.reserved)

    def bash_references(self, command: Any, *, limit: int = MAX_BASH_REFERENCES) -> list[FolderRef]:
        """Tracked folders a shell command names literally, deduplicated, in order.

        Best effort: expansions, globs, ``cd`` followed by a relative path and
        quoted names with spaces are invisible. The recorder confirms each
        reference against the host before crediting it.
        """
        if not isinstance(command, str) or not command:
            return []
        found: dict[tuple[str, str], FolderRef] = {}
        for pattern in self._bash_patterns:
            for match in pattern.finditer(command):
                ref = self.classify(match.group(1) + match.group(2))
                if ref is not None and ref.key not in found:
                    found[ref.key] = ref
                    if len(found) >= limit:
                        return list(found.values())
        return list(found.values())


# ---------------------------------------------------------------------------
# Host probes (blocking; call through run_file_io)
# ---------------------------------------------------------------------------


def host_root_visible(mount: LedgerMount) -> bool:
    """Whether the Gateway process sees the mount's host directory.

    With the AIO provider under Docker-out-of-Docker, ``host_path`` names a
    directory on the Docker host that the Gateway container may not have.
    """
    try:
        return os.path.isdir(mount.host_path)
    except (OSError, ValueError):
        return False


def probe_entry(mount: LedgerMount, name: str) -> EntryState | None:
    """The folder's state on the host, without following a link; None when not visible."""
    if not host_root_visible(mount):
        return None
    try:
        info = os.lstat(os.path.join(mount.host_path, name))
    except FileNotFoundError:
        return "missing"
    except (OSError, ValueError):
        return None
    if stat.S_ISLNK(info.st_mode):
        return "link"
    if stat.S_ISDIR(info.st_mode):
        return "dir"
    if stat.S_ISREG(info.st_mode):
        return "file"
    return "other"
