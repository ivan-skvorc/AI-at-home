"""Thread and run scope keys that per-run middlewares read from a runtime.

Guard middlewares keep state per thread and per run. They read the same two
context keys, and when a run carries no ``run_id`` they need one way to tell
graph invocations apart. Keeping that logic here makes the guards agree on what
one run is; each guard still owns its map and the lock that guards it.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from contextlib import AbstractContextManager
from typing import Any

DEFAULT_SCOPE = "default"

# id(anchor) -> (anchor, generated run id) for invocations without a run id.
FallbackRunIds = OrderedDict[int, tuple[object, str]]


def context_scope(runtime: Any, key: str) -> str:
    """Return ``runtime.context[key]`` as a string, or ``"default"`` when unset or empty."""
    context = getattr(runtime, "context", None)
    value = context.get(key) if context else None
    return str(value) if value else DEFAULT_SCOPE


def explicit_run_id(runtime: Any) -> tuple[bool, str | None]:
    """Return whether the runtime names its run, and the run id it names.

    A ``run_id`` key in the context is authoritative, including an explicit
    ``None``: ``SubagentExecutor`` consumes stop reasons with that raw value,
    so normalizing it would lose the signal. A RunnableConfig run id exposed
    through ``Runtime.execution_info`` is the next-best stable identifier.
    """
    context = getattr(runtime, "context", None)
    if isinstance(context, dict) and "run_id" in context:
        return True, context["run_id"]
    execution_run_id = getattr(getattr(runtime, "execution_info", None), "run_id", None)
    if execution_run_id is not None:
        return True, str(execution_run_id)
    return False, None


def invocation_anchor(runtime: Any) -> object:
    """Return the object that stays the same for one graph invocation.

    LangGraph creates a replacement Runtime wrapper per graph node, so
    ``id(runtime)`` changes from one node to the next, but it preserves
    ``Runtime.control`` across the invocation. A runtime without a control
    object anchors on itself.
    """
    control = getattr(runtime, "control", None)
    return control if control is not None else runtime


def invocation_run_id(fallbacks: FallbackRunIds, runtime: Any, *, max_entries: int | None = None) -> str:
    """Return the generated run id of the runtime's invocation, creating it on first use.

    The caller holds the lock that guards ``fallbacks``. The anchor maps to an
    opaque generated token instead of ``id(anchor)``, because CPython may
    reuse an address after garbage collection; the entry keeps the anchor
    alive and is matched by identity. The least recently used entry goes
    first, so a full map never evicts an active invocation. ``max_entries``
    bounds a plain ``OrderedDict``; a ``BoundedDict`` bounds itself.
    """
    anchor = invocation_anchor(runtime)
    anchor_id = id(anchor)
    entry = fallbacks.get(anchor_id)
    if entry is None or entry[0] is not anchor:
        entry = (anchor, f"__invocation__:{uuid.uuid4().hex}")
        fallbacks[anchor_id] = entry
    fallbacks.move_to_end(anchor_id)
    if max_entries is not None:
        while len(fallbacks) > max_entries:
            fallbacks.popitem(last=False)
    return entry[1]


def release_invocation_run_id(fallbacks: FallbackRunIds, runtime: Any) -> None:
    """Forget the runtime's generated run id, if it has one. The caller holds the lock."""
    anchor = invocation_anchor(runtime)
    entry = fallbacks.get(id(anchor))
    if entry is not None and entry[0] is anchor:
        del fallbacks[id(anchor)]


def runtime_run_id(runtime: Any, fallbacks: FallbackRunIds, lock: AbstractContextManager[Any], *, max_entries: int | None = None) -> str | None:
    """Return the run id the runtime names, else its invocation's generated one."""
    named, run_id = explicit_run_id(runtime)
    if named:
        return run_id
    with lock:
        return invocation_run_id(fallbacks, runtime, max_entries=max_entries)
