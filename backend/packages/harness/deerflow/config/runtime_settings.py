"""Runtime-toggleable server settings, persisted separately from ``config.yaml``.

`config.yaml` is the operator's config file (models, sandbox, credentials); we
deliberately do not let the Web UI rewrite it. This module owns the small set of
settings a user is allowed to flip from the UI at runtime, persisted as JSON
under the DeerFlow home directory so the choice survives restarts and is shared
by every worker reading the same data dir.

**Multi-user mode** (fork feature). Default ``True`` = per-user thread isolation
(each login only sees its own conversations — upstream behavior). When set to
``False`` the server treats every conversation as one shared workspace: thread
listing and per-thread access ignore the owner filter, so all conversations are
visible regardless of which login/device created them (matching the passwordless
"personal server" use case, where the effective user is always ``default`` but
older per-account histories may be stranded under other ids). Writes still stamp
the real owner, so turning multi-user mode back ON cleanly restores isolation.

Security note: with multi-user mode OFF, anyone who can reach the server sees all
conversations. That is the intended semantics for a trusted personal/LAN setup;
do not disable it on a shared or public deployment.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SETTINGS_FILENAME = "runtime_settings.json"
MULTI_USER_MODE_KEY = "multi_user_mode"
DEFAULT_MULTI_USER_MODE = True

# In-process cache keyed by (path, mtime) so hot read paths (every thread
# read/access check) do not re-parse the file. The mtime check still picks up an
# out-of-band edit or a sibling worker's write, mirroring how the config loader
# invalidates on file signature changes.
_lock = threading.Lock()
_cache: dict[str, Any] = {"path": None, "mtime": None, "data": {}}


def _settings_path() -> Path:
    # Lazy import: config.paths has no dependency on this module, but keeping the
    # import local avoids any import-time ordering surprises.
    from deerflow.config.paths import get_paths

    return get_paths().base_dir / _SETTINGS_FILENAME


def _load(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("runtime_settings: could not read %s (%s); using defaults", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _read_settings() -> dict[str, Any]:
    path = _settings_path()
    try:
        mtime: float | None = path.stat().st_mtime
    except OSError:
        mtime = None
    with _lock:
        if _cache["path"] == str(path) and _cache["mtime"] == mtime:
            return _cache["data"]
        data = _load(path)
        _cache["path"] = str(path)
        _cache["mtime"] = mtime
        _cache["data"] = data
        return data


def is_multi_user_mode_enabled() -> bool:
    """Whether per-user thread isolation is active (default ``True``).

    ``False`` means a single shared workspace: owner scoping is bypassed on
    reads/access so every conversation is visible regardless of login.
    """
    value = _read_settings().get(MULTI_USER_MODE_KEY, DEFAULT_MULTI_USER_MODE)
    return value if isinstance(value, bool) else DEFAULT_MULTI_USER_MODE


def set_multi_user_mode(enabled: bool) -> None:
    """Persist the multi-user-mode setting (atomic write) and refresh the cache."""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        data = _load(path)
        data[MULTI_USER_MODE_KEY] = bool(enabled)
        tmp = path.with_name(f"{path.name}.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
        try:
            mtime: float | None = path.stat().st_mtime
        except OSError:
            mtime = None
        _cache["path"] = str(path)
        _cache["mtime"] = mtime
        _cache["data"] = data


def reset_cache_for_tests() -> None:
    """Drop the in-process cache so a test's fresh settings file is re-read."""
    with _lock:
        _cache["path"] = None
        _cache["mtime"] = None
        _cache["data"] = {}


def resolve_owner_scope(value: Any, *, method_name: str = "repository read") -> str | None:
    """Resolve the owner filter for a **read/access** repository call.

    In normal (multi-user) mode this is exactly :func:`resolve_user_id`. When
    multi-user mode is OFF it returns ``None`` — the documented "no owner WHERE
    clause / bypass ownership check" value — so shared-workspace reads see every
    conversation. Write/stamp paths must keep calling :func:`resolve_user_id`
    directly so new rows still record their real owner.
    """
    if not is_multi_user_mode_enabled():
        return None
    from deerflow.runtime.user_context import resolve_user_id

    return resolve_user_id(value, method_name=method_name)
