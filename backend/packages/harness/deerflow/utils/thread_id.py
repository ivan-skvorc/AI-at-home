"""Canonical thread identifier validation shared across DeerFlow backends."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import AfterValidator, StringConstraints

from deerflow.utils.host_paths import windows_incompatible_segment

THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_THREAD_ID_RE = re.compile(THREAD_ID_PATTERN)


def validate_thread_id(thread_id: str) -> str:
    """Return a valid thread ID or raise ``ValueError``.

    Thread IDs are caller-defined opaque identifiers, not necessarily UUIDs,
    but they must be safe for every persistence and filesystem backend.
    """
    if not isinstance(thread_id, str) or _THREAD_ID_RE.fullmatch(thread_id) is None:
        raise ValueError("Invalid thread_id: expected 1-64 ASCII letters, digits, hyphens, or underscores")
    # Windows reserves device names such as NUL in every directory; creating a
    # thread workspace named "NUL" fails with FileNotFoundError on Windows
    # hosts. Reuse the canonical Windows-name check that uploads, sandbox
    # writes and skill support files already go through, so thread IDs follow
    # the same documented "rejected on every platform when a name is created"
    # contract instead of keeping a second name list in sync.
    reason = windows_incompatible_segment(thread_id)
    if reason is not None:
        raise ValueError(f"Invalid thread_id {thread_id!r}: {reason}")
    return thread_id


def resolve_thread_id(thread_id: str | None) -> str:
    """Validate a supplied ID, generating a UUID only when it is ``None``."""
    if thread_id is None:
        return str(uuid.uuid4())
    return validate_thread_id(thread_id)


def _configured_thread_id(config: object) -> str | None:
    configurable = config.get("configurable") if isinstance(config, Mapping) else None
    thread_id = configurable.get("thread_id") if isinstance(configurable, Mapping) else None
    return thread_id if isinstance(thread_id, str) and thread_id else None


def runtime_thread_id(runtime: Any, *, ambient: bool = False) -> str | None:
    """Return the thread ID a tool runtime runs under, or ``None``.

    Reads ``runtime.context["thread_id"]``, then the runtime's
    ``RunnableConfig``. With ``ambient``, a runtime that carries neither (or
    no runtime at all) falls back to the LangGraph config of the current task,
    which exists only inside a graph run. Only a non-empty string counts.
    """
    context = getattr(runtime, "context", None)
    if isinstance(context, Mapping):
        thread_id = context.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
    thread_id = _configured_thread_id(getattr(runtime, "config", None))
    if thread_id is not None or not ambient:
        return thread_id

    # Imported here so validators that import this module do not load LangGraph.
    from langgraph.config import get_config

    try:
        return _configured_thread_id(get_config())
    except RuntimeError:
        return None


ThreadId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=THREAD_ID_PATTERN),
    AfterValidator(validate_thread_id),
]
