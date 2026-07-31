"""Process-local, per-thread token accounting for auxiliary LLM calls.

The durable per-thread token totals (the chat sidebar's main counter) come from
the ``runs`` table, but two useful token sinks never become a graph run and so
never land there:

* **memory** — the background memory updater's fact-extraction LLM call, which
  runs off the request loop on a debounce worker thread; and
* **suggestions** — the follow-up-question one-shot LLM call the composer makes
  after each answer.

Both are opt-in fork features (off by default) that quietly cost tokens, so the
sidebar surfaces a separate counter for each when it is on. This module is that
counter's backing store: a small, thread-safe, in-memory registry keyed by
``thread_id`` then category then provider model name.

**Deliberately process-local and non-durable.** Recording from the memory
worker thread rules out the async ``runs`` engine (loop affinity), and these
auxiliary costs are a running "since server start" tally rather than an audited
ledger — a personal single-process deployment (the fork's target) never needs
more. The counter therefore resets on Gateway restart and is not shared across
workers, matching other process-local runtime state. The durable main token/
cost counter is unaffected.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

# Cap the number of distinct threads retained so a long-lived Gateway serving
# many conversations cannot grow this map without bound. Oldest-touched threads
# are evicted first (LRU); an evicted thread simply restarts its auxiliary tally
# from zero on its next auxiliary call, same as a restart.
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
    """
    if not thread_id or not category:
        return
    model = (model_name or _UNKNOWN_MODEL).strip() or _UNKNOWN_MODEL
    in_tokens = _coerce_int(input_tokens)
    out_tokens = _coerce_int(output_tokens)
    total = _coerce_int(total_tokens) if total_tokens is not None else in_tokens + out_tokens
    cache_read = _coerce_int(cache_read_tokens)
    if in_tokens == 0 and out_tokens == 0 and total == 0:
        return

    with _LOCK:
        thread_entry = _USAGE.get(thread_id)
        if thread_entry is None:
            thread_entry = {}
            _USAGE[thread_id] = thread_entry
            while len(_USAGE) > _MAX_THREADS:
                _USAGE.popitem(last=False)
        _USAGE.move_to_end(thread_id)
        category_entry = thread_entry.setdefault(category, {})
        model_entry = category_entry.setdefault(
            model,
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "calls": 0},
        )
        model_entry["input_tokens"] += in_tokens
        model_entry["output_tokens"] += out_tokens
        model_entry["total_tokens"] += total
        model_entry["cache_read_tokens"] += cache_read
        model_entry["calls"] += max(int(calls), 0)


def get_thread_aux_usage(thread_id: str | None) -> dict[str, dict[str, dict[str, int]]]:
    """Return a deep copy of one thread's auxiliary usage: category → model → totals."""
    if not thread_id:
        return {}
    with _LOCK:
        thread_entry = _USAGE.get(thread_id)
        if not thread_entry:
            return {}
        return {category: {model: dict(totals) for model, totals in models.items()} for category, models in thread_entry.items()}


def reset_aux_usage() -> None:
    """Clear all recorded auxiliary usage (test helper)."""
    with _LOCK:
        _USAGE.clear()
