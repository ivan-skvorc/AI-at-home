"""Durable backing store for auxiliary (non-graph) LLM token usage.

:mod:`deerflow.runtime.aux_usage` counts the tokens burned by the two LLM calls
that never become a graph run — background **memory** extraction and follow-up
**suggestions** — so the chat header can show what each is costing. Those totals
used to live only in process memory and reset on every Gateway restart, which is
fine for a display counter and useless as the foundation for a budget or a spend
report. This module is the durability half.

Why a dedicated SQLite file rather than the app database
--------------------------------------------------------
Memory usage is recorded from the memory updater's debounce worker
(``agents/memory/manager.py::_host_default_extraction_callback``), an ordinary
``threading.Timer`` thread with **no event loop**. The application database is
reached through an async SQLAlchemy engine bound to the Gateway's loop, so that
thread cannot write to it without a cross-thread handoff (a queue drained by the
loop), which would only work when a Gateway is running and would lose whatever
had not been drained at shutdown.

Three consequences settled the choice of a small dedicated store:

* **No loop affinity.** A plain ``sqlite3`` connection is usable from any
  thread, so one code path serves the Gateway, the embedded ``DeerFlowClient``,
  and the TUI. There is no queue to drain and nothing to lose on a hard crash —
  each call is committed where it happens.
* **No new dependency and no coupling to the app backend.** ``sqlite3`` is in
  the standard library, so this works identically under
  ``database.backend: memory | sqlite | postgres`` and needs no synchronous
  driver (there is no sync Postgres driver in the dependency set) and no alembic
  revision on the shared schema.
* **Nothing is gained by co-location.** Aux usage is append-only counter data
  with no foreign key into ``runs``; it is joined to a thread by ``thread_id``
  only, which any store can do.

Rows are append-only *events* rather than one cumulative row per counter. A per
call row costs ~100 bytes and gives the totals a time dimension, so a later
spend report or budget window (roadmap items 2 and 3) can slice by date without
a schema migration. Reads aggregate with ``SUM(...) GROUP BY``.

Everything here is best-effort: a store that cannot be opened or written
degrades to a warning and the caller keeps its process-local totals. A broken
cost counter must never disturb memory extraction or a chat response.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from deerflow.config.runtime_paths import runtime_home

logger = logging.getLogger(__name__)

# File name under the DeerFlow home dir when no explicit path is configured.
DEFAULT_DB_FILENAME = "aux_usage.sqlite3"

# ``DEER_FLOW_AUX_USAGE_DB`` selects the store: unset -> the default path under
# the DeerFlow home dir; one of the values below -> durability off (the counter
# stays process-local, i.e. the pre-durability behaviour); anything else -> an
# explicit database path.
AUX_USAGE_DB_ENV = "DEER_FLOW_AUX_USAGE_DB"
_DISABLED_VALUES = {"", "0", "off", "false", "no", "none", "disabled"}

SCHEMA_VERSION = 1

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS aux_usage_events (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id         TEXT    NOT NULL,
        category          TEXT    NOT NULL,
        model_name        TEXT    NOT NULL,
        input_tokens      INTEGER NOT NULL DEFAULT 0,
        output_tokens     INTEGER NOT NULL DEFAULT 0,
        total_tokens      INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
        calls             INTEGER NOT NULL DEFAULT 0,
        recorded_at       REAL    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_aux_usage_events_thread ON aux_usage_events (thread_id)",
    "CREATE INDEX IF NOT EXISTS ix_aux_usage_events_recorded_at ON aux_usage_events (recorded_at)",
)

_COUNTER_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "calls")


class AuxUsageStore:
    """Thread-safe SQLite store for auxiliary token usage.

    One connection is shared across threads (``check_same_thread=False``) and
    serialized by an instance lock, because the write volume is a handful of
    rows per conversation turn. Every method is best-effort: a SQLite or OS
    error is logged once and swallowed, leaving the caller's in-memory totals
    as the (non-durable) fallback.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._degraded_logged = False

    # -- lifecycle ---------------------------------------------------------

    def _connect_locked(self) -> sqlite3.Connection:
        """Return the live connection, opening it on first use. Caller holds the lock."""
        if self._conn is not None:
            return self._conn
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        try:
            # WAL keeps a reader (the header request) from blocking the memory
            # worker's write, and lets a second Gateway worker on the same host
            # share the file. ``synchronous=NORMAL`` is the standard
            # safe-and-fast pairing, matching the app database's own pragmas.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
        except BaseException:
            # Never leak a half-initialized connection: the caller degrades to
            # the in-memory counter and will retry on the next call.
            conn.close()
            raise
        self._conn = conn
        return conn

    def _degrade(self, action: str, exc: BaseException) -> None:
        """Report a failed store operation, at WARNING the first time only.

        Failure is deliberately *not* sticky: auxiliary calls are rare (a
        handful per turn), so a transient condition — a full disk, a
        briefly-unavailable mount — should heal on its own rather than leave the
        counter non-durable until the next restart. The one-shot WARNING keeps a
        persistent failure from spamming the log.
        """
        if not self._degraded_logged:
            self._degraded_logged = True
            logger.warning(
                "Durable auxiliary-usage store unavailable at %s (%s: %s); auxiliary token counters stay process-local until it recovers",
                self.path,
                action,
                exc,
            )
        else:
            logger.debug("auxiliary-usage store %s failed", action, exc_info=True)

    def close(self) -> None:
        """Close the underlying connection (idempotent)."""
        with self._lock:
            conn, self._conn = self._conn, None
            if conn is not None:
                try:
                    conn.close()
                except (sqlite3.Error, OSError):  # pragma: no cover - defensive
                    logger.debug("failed to close auxiliary-usage store", exc_info=True)

    # -- writes ------------------------------------------------------------

    def add(
        self,
        thread_id: str,
        category: str,
        model_name: str,
        *,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cache_read_tokens: int,
        calls: int,
        recorded_at: float | None = None,
    ) -> bool:
        """Append one auxiliary call's usage. Returns ``True`` when persisted."""
        with self._lock:
            try:
                conn = self._connect_locked()
                conn.execute(
                    "INSERT INTO aux_usage_events (thread_id, category, model_name, input_tokens, output_tokens, total_tokens, cache_read_tokens, calls, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        thread_id,
                        category,
                        model_name,
                        int(input_tokens),
                        int(output_tokens),
                        int(total_tokens),
                        int(cache_read_tokens),
                        int(calls),
                        float(recorded_at if recorded_at is not None else time.time()),
                    ),
                )
                conn.commit()
                return True
            except (sqlite3.Error, OSError) as exc:
                self._degrade("write", exc)
                return False

    def clear(self) -> None:
        """Delete every recorded row (test helper / explicit reset)."""
        with self._lock:
            try:
                conn = self._connect_locked()
                conn.execute("DELETE FROM aux_usage_events")
                conn.commit()
            except (sqlite3.Error, OSError) as exc:
                self._degrade("clear", exc)

    # -- reads -------------------------------------------------------------

    def read_thread(self, thread_id: str) -> dict[str, dict[str, dict[str, int]]]:
        """Return one thread's persisted totals: category -> model -> counters."""
        with self._lock:
            try:
                conn = self._connect_locked()
                rows = conn.execute(
                    "SELECT category, model_name, SUM(input_tokens), SUM(output_tokens), SUM(total_tokens), SUM(cache_read_tokens), SUM(calls) FROM aux_usage_events WHERE thread_id = ? GROUP BY category, model_name",
                    (thread_id,),
                ).fetchall()
            except (sqlite3.Error, OSError) as exc:
                self._degrade("read", exc)
                return {}

        usage: dict[str, dict[str, dict[str, int]]] = {}
        for category, model_name, *totals in rows:
            usage.setdefault(category, {})[model_name] = {field: int(value or 0) for field, value in zip(_COUNTER_FIELDS, totals, strict=True)}
        return usage


# ---------------------------------------------------------------------------
# Process-wide accessor
# ---------------------------------------------------------------------------

_STORE_LOCK = threading.Lock()
_STORE: AuxUsageStore | None = None
_STORE_RESOLVED = False


def resolve_aux_usage_db_path() -> Path | None:
    """Resolve the store path, or ``None`` when durability is switched off."""
    configured = os.getenv(AUX_USAGE_DB_ENV)
    if configured is not None:
        if configured.strip().lower() in _DISABLED_VALUES:
            return None
        return Path(configured).expanduser()
    return runtime_home() / DEFAULT_DB_FILENAME


def get_aux_usage_store() -> AuxUsageStore | None:
    """Return the process-wide store, or ``None`` when durability is off.

    The path is resolved once per process (or after :func:`reset_aux_usage_store`)
    so a mid-run environment change does not silently split the totals across
    two files.
    """
    global _STORE, _STORE_RESOLVED
    with _STORE_LOCK:
        if _STORE_RESOLVED:
            return _STORE
        path = resolve_aux_usage_db_path()
        _STORE = AuxUsageStore(path) if path is not None else None
        _STORE_RESOLVED = True
        return _STORE


def reset_aux_usage_store(*, clear: bool = False) -> None:
    """Drop the process-wide store handle; optionally delete its rows.

    ``clear=False`` is the "restart the process" shape used by tests and by
    anything that needs the next call to re-resolve the configured path.
    """
    global _STORE, _STORE_RESOLVED
    with _STORE_LOCK:
        store, _STORE = _STORE, None
        _STORE_RESOLVED = False
    if store is None:
        return
    if clear:
        store.clear()
    store.close()
