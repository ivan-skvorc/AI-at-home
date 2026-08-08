"""Durable per-user UI state, persisted under the DeerFlow home directory.

Sibling of :mod:`deerflow.config.runtime_settings`: that module owns *server-wide*
runtime settings, this one owns state that belongs to a single user's workspace
and must outlive the browser that produced it.

**Chat tabs** (fork feature). The keep-alive chat tab strip is a curated set of
pinned conversations. It was originally persisted only in ``localStorage``, which
is per-browser *and* per-origin — so the set was silently lost whenever the
browser cleared site data on exit, evicted storage for an insecure-origin site
(a plain-HTTP LAN deployment, the fork's documented setup), or the app was
reopened on a different origin than the one that pinned them (``localhost`` vs a
LAN/Tailscale address both reach the same server). Persisting server-side makes
the set survive a machine restart and follow the user across browsers and
devices, with ``localStorage`` demoted to a first-paint cache.

The file is a small JSON bag at ``{base_dir}/users/{user_id}/ui_state.json`` so
later per-user UI state can join it without another store; writes merge into the
existing document rather than replacing it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UI_STATE_FILENAME = "ui_state.json"
CHAT_TABS_KEY = "chat_tabs"

# Mirrors ``MAX_CHAT_TABS`` in ``frontend/src/core/threads/chat-tabs.ts``: every
# pinned tab holds a live chat instance, so the ceiling is a resource guard.
# Enforced here too because the API is untrusted input.
MAX_CHAT_TABS = 8
# A cached display hint only — the live title is resolved from the thread list.
MAX_TITLE_CHARS = 200
MAX_ID_CHARS = 128

# Per-user cache keyed by the file's (mtime, size) so a sibling worker's write or
# an out-of-band edit is picked up without a restart, matching how
# ``runtime_settings`` and the config loader invalidate.
_lock = threading.Lock()
_cache: dict[str, tuple[Any, dict[str, Any]]] = {}


def _state_path(user_id: str) -> Path:
    # ``make_safe_user_id`` first: an authenticated identity may legitimately be
    # an email or another string outside the directory charset, and ``user_dir``
    # raises on those. This is the same normalization the memory store applies,
    # so both land in the same per-user bucket.
    from deerflow.config.paths import get_paths, make_safe_user_id

    return get_paths().user_dir(make_safe_user_id(user_id)) / UI_STATE_FILENAME


def _signature(path: Path) -> Any:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _load(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("user_ui_state: could not read %s (%s); using defaults", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _read_state(user_id: str) -> dict[str, Any]:
    path = _state_path(user_id)
    signature = _signature(path)
    key = str(path)
    with _lock:
        cached = _cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        data = _load(path)
        _cache[key] = (signature, data)
        return data


def _clean_text(value: Any, limit: int) -> str | None:
    """A non-empty, length-capped string, or ``None`` when unusable."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:limit]


def normalize_chat_tabs(raw: Any) -> list[dict[str, str]]:
    """Validate and bound an incoming tab list.

    Mirrors ``deserializeChatTabs`` in the frontend model: malformed entries are
    dropped rather than rejected (a tampered or partially-written store must
    degrade, not break the strip), duplicate keys/thread ids collapse first-wins,
    and the result is capped at :data:`MAX_CHAT_TABS`.
    """
    if not isinstance(raw, list):
        return []
    tabs: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    seen_threads: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        key = _clean_text(entry.get("key"), MAX_ID_CHARS)
        thread_id = _clean_text(entry.get("threadId"), MAX_ID_CHARS)
        if key is None or thread_id is None:
            continue
        if key in seen_keys or thread_id in seen_threads:
            continue
        seen_keys.add(key)
        seen_threads.add(thread_id)
        tab: dict[str, str] = {"key": key, "threadId": thread_id}
        title = _clean_text(entry.get("title"), MAX_TITLE_CHARS)
        if title is not None:
            tab["title"] = title
        tabs.append(tab)
        if len(tabs) >= MAX_CHAT_TABS:
            break
    return tabs


def get_chat_tabs(user_id: str) -> list[dict[str, str]]:
    """The user's persisted pinned tabs (empty when never set)."""
    return normalize_chat_tabs(_read_state(user_id).get(CHAT_TABS_KEY))


def set_chat_tabs(user_id: str, tabs: Any) -> list[dict[str, str]]:
    """Persist the user's pinned tabs atomically; returns the stored value.

    An empty list is a legitimate value (the user closed their last tab), so it
    is written rather than treated as a no-op.
    """
    normalized = normalize_chat_tabs(tabs)
    path = _state_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        data = _load(path)
        data[CHAT_TABS_KEY] = normalized
        tmp = path.with_name(f"{path.name}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        _cache[str(path)] = (_signature(path), data)
    return normalized


def reset_cache_for_tests() -> None:
    """Drop the in-process cache so a test's fresh state file is re-read."""
    with _lock:
        _cache.clear()
