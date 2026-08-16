"""Durable per-thread token accounting for auxiliary LLM calls.

The durable per-thread token totals (the chat sidebar's main counter) come from
the ``runs`` table, but two useful token sinks never become a graph run and so
never land there:

* **memory** — the background memory updater's fact-extraction LLM call, which
  runs off the request loop on a debounce worker thread; and
* **suggestions** — the follow-up-question one-shot LLM call the composer makes
  after each answer.

Both are opt-in fork features (off by default) that quietly cost tokens, so the
sidebar surfaces a separate counter for each when it is on. This module is that
counter's registry: a small, thread-safe map keyed by ``thread_id`` then
category then provider model name.

**Durable, with the map as a write-through cache.** Every call is appended to
:mod:`deerflow.runtime.aux_usage_store` — a small dedicated SQLite file, chosen
because the memory worker thread has no event loop and so cannot reach the async
runs engine (that module's docstring records the full reasoning). The in-memory
map is hydrated from the store the first time a thread is touched and then
serves reads without further disk access, so the chat header stays fast. Totals
therefore survive a Gateway restart, and the LRU cap below evicts cache entries
rather than data — an evicted thread simply re-hydrates on its next touch. Set
``DEER_FLOW_AUX_USAGE_DB=0`` to switch durability off and get the previous
process-local behaviour.

**Blocking IO.** Because the write-through store is a local file, the sync
functions here may touch the disk (once per thread for a hydrate, once per call
for a write). They are safe to call from any thread — including the memory
updater's debounce worker — but must NOT be called from the event loop. Async
callers use :func:`arecord_aux_usage` / :func:`aget_thread_aux_usage`, which
offload to a worker thread.

**Known limitation.** With more than one Gateway worker on one machine the cache
is per process, so a worker's header can lag a sibling's auxiliary writes until
that thread is re-hydrated (process restart or LRU eviction). The persisted
totals are always complete; only one process's cached view can be behind. The
fork's target is a single-process personal deployment.
"""

from __future__ import annotations

import asyncio
import functools
import threading
from collections import OrderedDict
from typing import Any

from deerflow.runtime.aux_usage_store import AuxUsageStore, get_aux_usage_store, reset_aux_usage_store

# Cap the number of distinct threads cached in memory so a long-lived Gateway
# serving many conversations cannot grow this map without bound. Oldest-touched
# threads are evicted first (LRU); eviction now only drops the cached copy — the
# thread's totals stay in the durable store and are re-hydrated on next touch.
_MAX_THREADS = 4096

_UNKNOWN_MODEL = "unknown"

_LOCK = threading.Lock()
# thread_id -> category -> model_name -> {input_tokens, output_tokens,
#                                         total_tokens, cache_read_tokens, calls}
_USAGE: OrderedDict[str, dict[str, dict[str, dict[str, int]]]] = OrderedDict()


def _coerce_int(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _new_totals() -> dict[str, int]:
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "calls": 0}


def _cached_thread_entry(thread_id: str, store: AuxUsageStore | None, *, create: bool) -> dict[str, dict[str, dict[str, int]]]:
    """Return this thread's cache entry, hydrating from the store on first touch.

    The caller must hold ``_LOCK``: hydration has to happen inside the same
    critical section as the increment that follows it, or a concurrent record
    could be written to the store and then counted a second time when the
    persisted totals are merged in.

    ``create=False`` keeps a read miss out of the cache so that polling an
    unknown thread cannot evict a live one.
    """
    entry = _USAGE.get(thread_id)
    if entry is None:
        entry = store.read_thread(thread_id) if store is not None else {}
        if not entry and not create:
            return {}
        _USAGE[thread_id] = entry
        while len(_USAGE) > _MAX_THREADS:
            _USAGE.popitem(last=False)
    _USAGE.move_to_end(thread_id)
    return entry


def record_aux_usage(
    thread_id: str | None,
    category: str,
    *,
    model_name: str | None,
    input_tokens: Any = 0,
    output_tokens: Any = 0,
    total_tokens: Any = None,
    cache_read_tokens: Any = 0,
    calls: int = 1,
) -> None:
    """Add one auxiliary LLM call's token usage to the per-thread tally.

    Best-effort and never raises: an unusable ``thread_id`` / ``category`` is a
    silent no-op, and non-numeric token fields coerce to ``0``. ``total_tokens``
    defaults to ``input + output`` when not supplied.

    Performs file IO (see the module docstring) — call it from a worker thread,
    or use :func:`arecord_aux_usage` from async code.
    """
    if not thread_id or not category:
        return
    model = (model_name or _UNKNOWN_MODEL).strip() or _UNKNOWN_MODEL
    in_tokens = _coerce_int(input_tokens)
    out_tokens = _coerce_int(output_tokens)
    total = _coerce_int(total_tokens) if total_tokens is not None else in_tokens + out_tokens
    cache_read = _coerce_int(cache_read_tokens)
    call_count = max(int(calls), 0)
    if in_tokens == 0 and out_tokens == 0 and total == 0:
        return

    # Resolved outside ``_LOCK`` so the store singleton's own lock is never
    # taken in the other order.
    store = get_aux_usage_store()

    with _LOCK:
        thread_entry = _cached_thread_entry(thread_id, store, create=True)
        category_entry = thread_entry.setdefault(category, {})
        model_entry = category_entry.setdefault(model, _new_totals())
        model_entry["input_tokens"] += in_tokens
        model_entry["output_tokens"] += out_tokens
        model_entry["total_tokens"] += total
        model_entry["cache_read_tokens"] += cache_read
        model_entry["calls"] += call_count
        if store is not None:
            # Inside the lock on purpose: the cache is only a valid mirror of
            # the store while the two are updated together.
            store.add(
                thread_id,
                category,
                model,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                total_tokens=total,
                cache_read_tokens=cache_read,
                calls=call_count,
            )


def get_thread_aux_usage(thread_id: str | None) -> dict[str, dict[str, dict[str, int]]]:
    """Return a deep copy of one thread's auxiliary usage: category → model → totals.

    Reads the durable store once per thread per process, then serves subsequent
    reads from the cache. Performs file IO on that first read — call it from a
    worker thread, or use :func:`aget_thread_aux_usage` from async code.
    """
    if not thread_id:
        return {}
    store = get_aux_usage_store()
    with _LOCK:
        thread_entry = _cached_thread_entry(thread_id, store, create=False)
        if not thread_entry:
            return {}
        return {category: {model: dict(totals) for model, totals in models.items()} for category, models in thread_entry.items()}


async def arecord_aux_usage(
    thread_id: str | None,
    category: str,
    **kwargs: Any,
) -> None:
    """Async wrapper for :func:`record_aux_usage` (offloads the store write)."""
    await asyncio.to_thread(functools.partial(record_aux_usage, thread_id, category, **kwargs))


async def aget_thread_aux_usage(thread_id: str | None) -> dict[str, dict[str, dict[str, int]]]:
    """Async wrapper for :func:`get_thread_aux_usage` (offloads the store read)."""
    return await asyncio.to_thread(get_thread_aux_usage, thread_id)


def reset_aux_usage_cache() -> None:
    """Drop the process-local cache and store handle, keeping persisted rows.

    This is the "restart the Gateway" shape: the next read re-hydrates from the
    durable store.
    """
    with _LOCK:
        _USAGE.clear()
    reset_aux_usage_store()


def reset_aux_usage() -> None:
    """Clear all recorded auxiliary usage, cached and persisted (test helper)."""
    with _LOCK:
        _USAGE.clear()
    reset_aux_usage_store(clear=True)
