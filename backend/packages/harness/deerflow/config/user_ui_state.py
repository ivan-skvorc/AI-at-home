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
CHAT_FOLDERS_KEY = "chat_folders"
PUSH_SUBSCRIPTIONS_KEY = "push_subscriptions"

# Mirrors ``MAX_CHAT_TABS`` in ``frontend/src/core/threads/chat-tabs.ts``: every
# pinned tab holds a live chat instance, so the ceiling is a resource guard.
# Enforced here too because the API is untrusted input.
MAX_CHAT_TABS = 8
# A cached display hint only — the live title is resolved from the thread list.
MAX_TITLE_CHARS = 200
MAX_ID_CHARS = 128

# Sidebar chat folders (fork feature). The registry is only the folder list —
# id, display name, order, and the optional parent that makes it a tree. Which
# conversation is in which folder lives in that thread's own metadata
# (``deerflow_folder``), so renaming a folder is one small write here rather
# than a rewrite of every thread inside it. Bounded because the API is untrusted
# input and the sidebar has to stay a sidebar.
MAX_CHAT_FOLDERS = 50
MAX_FOLDER_NAME_CHARS = 80
# Nesting depth, counting the top level as 1. Mirrors ``MAX_FOLDER_DEPTH`` in
# ``frontend/src/core/threads/chat-folders.ts``: the sidebar indents one step
# per level inside a fixed-width column, so this is a legibility bound as much
# as a data one.
MAX_FOLDER_DEPTH = 5

# Web Push subscriptions (fork feature). One per browser/device the user opted
# in from, so the same account can be pushed on a phone and a laptop. Bounded
# because the endpoint is untrusted input and a stale subscription is never
# cleaned up by the browser — only by a 404/410 from the push service.
MAX_PUSH_SUBSCRIPTIONS = 10
MAX_ENDPOINT_CHARS = 1024
MAX_KEY_CHARS = 256

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
    _write_state(user_id, {CHAT_TABS_KEY: normalized})
    return normalized


def _write_state(user_id: str, updates: dict[str, Any]) -> None:
    """Merge *updates* into the user's JSON bag and replace the file atomically.

    Merge rather than replace: the file holds several independent pieces of UI
    state (pinned tabs, push subscriptions), and a writer that only knows about
    one of them must not delete the others.
    """
    path = _state_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        data = _load(path)
        data.update(updates)
        tmp = path.with_name(f"{path.name}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        _cache[str(path)] = (_signature(path), data)


def reset_cache_for_tests() -> None:
    """Drop the in-process cache so a test's fresh state file is re-read."""
    with _lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Sidebar chat folders (fork feature)
# ---------------------------------------------------------------------------


def _repair_folder_tree(entries: list[dict[str, Any]]) -> None:
    """Force ``parentId`` links into a real forest, in place.

    Every parent must name an existing folder, no chain may loop, and nothing
    may sit deeper than :data:`MAX_FOLDER_DEPTH`. A violation is repaired by
    **moving the offending folder to the top level**, never by dropping it: a
    folder that disappears takes the chats inside it out of their folder with no
    way back, while a folder that surfaces at the top is visible, named, and one
    drag from where it belongs.

    One repair per pass, re-deriving depths in between, because a single fix can
    resolve several violations at once — orphaning the middle of an over-deep
    chain brings everything below it back into range.
    """
    by_id = {entry["id"]: entry for entry in entries}
    for entry in entries:
        parent_id = entry["parentId"]
        if parent_id is not None and (parent_id not in by_id or parent_id == entry["id"]):
            entry["parentId"] = None

    # Bounded by the folder count: each pass orphans exactly one folder, and an
    # all-root list has no violations left to find.
    for _ in range(len(entries) + 1):
        depths: dict[str, int] = {}
        frontier = [entry for entry in entries if entry["parentId"] is None]
        depth = 1
        while frontier:
            for entry in frontier:
                depths[entry["id"]] = depth
            depth += 1
            parents = {entry["id"] for entry in frontier}
            frontier = [entry for entry in entries if entry["id"] not in depths and entry["parentId"] in parents]
        # Too deep first, shallowest of those: orphaning the highest offender is
        # what pulls a whole over-long chain back into range in one move. A
        # folder no walk reached is in a cycle.
        too_deep = sorted(
            (entry for entry in entries if depths.get(entry["id"], 0) > MAX_FOLDER_DEPTH),
            key=lambda entry: depths.get(entry["id"], 0),
        )
        violator = next(
            iter(too_deep),
            next((entry for entry in entries if entry["id"] not in depths), None),
        )
        if violator is None:
            return
        violator["parentId"] = None


def normalize_chat_folders(raw: Any) -> list[dict[str, Any]]:
    """Validate and bound an incoming folder list.

    Mirrors ``normalizeChatFolders`` in the frontend model: malformed entries
    are dropped rather than rejected (a tampered or partially-written store must
    degrade to "fewer folders", never to a sidebar that will not render),
    duplicate ids collapse first-wins, the result is capped at
    :data:`MAX_CHAT_FOLDERS`, and the ``parentId`` links are repaired into a
    real forest by :func:`_repair_folder_tree`. List order is display order and
    is preserved. A top-level folder carries **no** ``parentId`` key at all, so
    a flat list round-trips through the tree feature byte-for-byte.

    A dropped folder is not a lost conversation: a thread whose
    ``deerflow_folder`` names an unknown folder falls back to the root list.
    """
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        folder_id = _clean_text(entry.get("id"), MAX_ID_CHARS)
        name = _clean_text(entry.get("name"), MAX_FOLDER_NAME_CHARS)
        if folder_id is None or name is None:
            continue
        if folder_id in seen_ids:
            continue
        seen_ids.add(folder_id)
        entries.append(
            {
                "id": folder_id,
                "name": name,
                "parentId": _clean_text(entry.get("parentId"), MAX_ID_CHARS),
            }
        )
        if len(entries) >= MAX_CHAT_FOLDERS:
            break
    _repair_folder_tree(entries)
    folders: list[dict[str, Any]] = []
    for entry in entries:
        folder: dict[str, Any] = {"id": entry["id"], "name": entry["name"]}
        if entry["parentId"] is not None:
            folder["parentId"] = entry["parentId"]
        folders.append(folder)
    return folders


def get_chat_folders(user_id: str) -> list[dict[str, Any]]:
    """The user's sidebar folders in display order (empty when never set)."""
    return normalize_chat_folders(_read_state(user_id).get(CHAT_FOLDERS_KEY))


def set_chat_folders(user_id: str, folders: Any) -> list[dict[str, Any]]:
    """Persist the user's folders atomically; returns the stored value.

    An empty list is a legitimate value (the user deleted their last folder), so
    it is written rather than treated as a no-op.
    """
    normalized = normalize_chat_folders(folders)
    _write_state(user_id, {CHAT_FOLDERS_KEY: normalized})
    return normalized


# ---------------------------------------------------------------------------
# Web Push subscriptions (fork feature)
# ---------------------------------------------------------------------------


def normalize_push_subscriptions(raw: Any) -> list[dict[str, Any]]:
    """Validate and bound a stored/incoming subscription list.

    Same posture as :func:`normalize_chat_tabs`: malformed entries are dropped
    rather than rejected, because a partially-written store must degrade to
    "fewer devices notified" and never to a failed settings load. Deduped by
    endpoint, which is the browser's own identity for a subscription — a
    re-subscribe on the same device replaces rather than accumulates.
    """
    if not isinstance(raw, list):
        return []
    subscriptions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        endpoint = _clean_text(entry.get("endpoint"), MAX_ENDPOINT_CHARS)
        keys = entry.get("keys")
        if endpoint is None or not isinstance(keys, dict):
            continue
        # A push service endpoint is always https; anything else cannot be
        # delivered to and is more likely a tampered payload than a typo.
        if not endpoint.startswith("https://"):
            continue
        p256dh = _clean_text(keys.get("p256dh"), MAX_KEY_CHARS)
        auth = _clean_text(keys.get("auth"), MAX_KEY_CHARS)
        if p256dh is None or auth is None:
            continue
        if endpoint in seen:
            continue
        seen.add(endpoint)
        subscription: dict[str, Any] = {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}
        label = _clean_text(entry.get("label"), MAX_TITLE_CHARS)
        if label is not None:
            subscription["label"] = label
        subscriptions.append(subscription)
        if len(subscriptions) >= MAX_PUSH_SUBSCRIPTIONS:
            break
    return subscriptions


def get_push_subscriptions(user_id: str) -> list[dict[str, Any]]:
    """The user's registered push subscriptions (empty when none)."""
    return normalize_push_subscriptions(_read_state(user_id).get(PUSH_SUBSCRIPTIONS_KEY))


def set_push_subscriptions(user_id: str, subscriptions: Any) -> list[dict[str, Any]]:
    """Replace the user's push subscriptions; returns the persisted value."""
    normalized = normalize_push_subscriptions(subscriptions)
    _write_state(user_id, {PUSH_SUBSCRIPTIONS_KEY: normalized})
    return normalized


def add_push_subscription(user_id: str, subscription: Any) -> list[dict[str, Any]]:
    """Register one subscription, replacing any entry with the same endpoint.

    Oldest-first eviction at the cap: the device the user just opted in from is
    the one they are looking at, so it must never be the one dropped.
    """
    existing = get_push_subscriptions(user_id)
    incoming = normalize_push_subscriptions([subscription])
    if not incoming:
        return existing
    endpoint = incoming[0]["endpoint"]
    merged = [entry for entry in existing if entry["endpoint"] != endpoint]
    merged.append(incoming[0])
    return set_push_subscriptions(user_id, merged[-MAX_PUSH_SUBSCRIPTIONS:])


def remove_push_subscription(user_id: str, endpoint: str) -> list[dict[str, Any]]:
    """Drop one subscription by endpoint (used on unsubscribe and on a 404/410)."""
    remaining = [entry for entry in get_push_subscriptions(user_id) if entry["endpoint"] != endpoint]
    return set_push_subscriptions(user_id, remaining)
