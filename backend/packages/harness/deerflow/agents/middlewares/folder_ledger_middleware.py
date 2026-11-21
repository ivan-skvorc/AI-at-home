"""Record which conversation created or edited a folder in a shared writable mount.

Custom ``sandbox.mounts`` are shared by every conversation and every user, and
they outlive any one thread, so nothing else records who wrote there. This
middleware fills the folder ledger (``deerflow.persistence.folder_ledger``) from
the tool calls that write to such a mount:

- ``write_file`` (``write`` / ``append``) and ``str_replace`` (``edit``) are
  recorded when the tool's result is not an error and its first line is
  exactly ``"OK"`` (a write may append a syntax warning below it; the write
  still happened). Before the call, when the Gateway can see the mount's host
  directory, the folder entry is checked with ``lstat``: an entry that did not
  exist yet is credited to this conversation as ``observed_create``; otherwise
  the folder is ``preexisting`` (an unseen host also reads as pre-existing, so
  it is never offered for deletion).
- ``bash`` is best effort: literal ``<mount>/<name>`` references in the
  command are checked on the host before and after the call. A referenced
  entry that appeared is ``inferred_shell`` (never offered for deletion: a
  ``mv`` of an existing folder also makes a name appear); one that existed is
  a shell touch; one the command removed retires its ledger row, so a later
  folder of that name starts a new row with its real creator. Without a
  visible host nothing is recorded for bash.

Every probe also reads the entry's ``st_dev:st_ino``. The ledger binds a folder
row to the entry it saw created (and to the entry a recorded write left behind,
when that write started from the bound one), and the confined delete refuses an
entry that no longer matches.

The position in the chain is the contract: appended just before
``ToolErrorHandlingMiddleware``, so every gate outside it (authorization,
audit, read-before-write, harness guard, tool-progress short circuits) has
already let the call through, and the result it inspects is the normalized
one. Being in the shared base chain is what makes subagent writes count.

It **fails open**: a ledger error is logged and never changes the tool result
or the agent state. All filesystem and database I/O runs off the event loop.
The write goes through the synchronous engine in a worker thread, because this
also runs on the subagents' persistent loop, where the Gateway's loop-bound
async pool must not be used. Without a SQL session factory (``database.backend:
memory``) or a thread id it does nothing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.folder_ledger.mounts import EntryProbe, FolderClassifier, FolderRef, host_root_key, probe_entry
from deerflow.persistence.folder_ledger.sql import OP_APPEND, OP_EDIT, OP_SHELL, OP_WRITE, FolderLedgerRecorderStore, TouchRecord
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

_WRITE_TOOLS = frozenset({"write_file", "str_replace"})
_BASH_TOOL = "bash"
_SUCCESS = "OK"
_MAX_ID_CHARS = 64
#: How long a tool call waits for its ledger write. The write itself finishes
#: in its worker thread either way; the call only stops waiting.
WRITE_WAIT_SECONDS = 10.0

Probes = dict[tuple[str, str], EntryProbe | None]


@dataclass(frozen=True)
class _Plan:
    tool: str
    op: str
    refs: tuple[FolderRef, ...]
    thread_id: str
    user_id: str
    run_id: str | None
    tool_call_id: str | None


def _context(request: ToolCallRequest) -> Mapping[str, Any]:
    context = getattr(request.runtime, "context", None)
    return context if isinstance(context, Mapping) else {}


def _short_id(value: Any) -> str | None:
    return value if isinstance(value, str) and value and len(value) <= _MAX_ID_CHARS else None


def _default_ledger_available() -> bool:
    from deerflow.persistence.engine import get_session_factory

    return get_session_factory() is not None


def _tool_message(result: Any, tool_call_id: str | None) -> ToolMessage | None:
    if isinstance(result, ToolMessage):
        return result
    if isinstance(result, Command):
        update = result.update if isinstance(result.update, Mapping) else {}
        for message in update.get("messages") or []:
            if isinstance(message, ToolMessage) and (tool_call_id is None or message.tool_call_id == tool_call_id):
                return message
    return None


def _text(message: ToolMessage) -> str | None:
    content = message.content
    if isinstance(content, str):
        return content
    return None


def _probe_all(refs: tuple[FolderRef, ...]) -> Probes:
    """Host state of each referenced folder (blocking; run off the loop)."""
    return {ref.key: probe_entry(ref.mount, ref.name) for ref in refs}


class FolderLedgerMiddleware(AgentMiddleware):
    """Fill the folder ledger from successful writes to writable custom mounts."""

    def __init__(
        self,
        *,
        app_config: Any,
        store_factory: Callable[[], FolderLedgerRecorderStore | None] | None = None,
        ledger_available: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self._classifier = FolderClassifier(app_config)
        self._database = getattr(app_config, "database", None)
        self._store_factory = store_factory or self._default_store
        self._ledger_available = ledger_available or _default_ledger_available
        self._store: FolderLedgerRecorderStore | None = None
        self._store_unavailable = False

    @property
    def tracks_anything(self) -> bool:
        """Whether any writable mount is configured for a provider that honors it."""
        return self._classifier.enabled

    # -- planning (pure, on the loop) ------------------------------------

    def _plan(self, request: ToolCallRequest) -> _Plan | None:
        tool = request.tool_call.get("name")
        if tool not in _WRITE_TOOLS and tool != _BASH_TOOL:
            return None
        if not self._classifier.enabled:
            return None
        context = _context(request)
        thread_id = _short_id(context.get("thread_id"))
        if thread_id is None:
            return None
        try:
            if not self._ledger_available():
                return None
        except Exception:
            return None
        args = request.tool_call.get("args")
        if not isinstance(args, Mapping):
            return None
        if tool == _BASH_TOOL:
            refs = tuple(self._classifier.bash_references(args.get("command")))
            op = OP_SHELL
        else:
            ref = self._classifier.classify(args.get("path"))
            refs = (ref,) if ref is not None else ()
            if tool == "str_replace":
                if args.get("old_str") == "":
                    return None  # a no-op edit: the tool returns OK without writing
                op = OP_EDIT
            else:
                op = OP_APPEND if args.get("append") is True else OP_WRITE
        if not refs:
            return None
        from deerflow.runtime.user_context import resolve_runtime_user_id

        user_id = _short_id(resolve_runtime_user_id(request.runtime))
        if user_id is None:
            return None
        tool_call_id = request.tool_call.get("id")
        return _Plan(
            tool=tool,
            op=op,
            refs=refs,
            thread_id=thread_id,
            user_id=user_id,
            run_id=_short_id(context.get("run_id")),
            tool_call_id=tool_call_id if isinstance(tool_call_id, str) and len(tool_call_id) <= 128 else None,
        )

    @staticmethod
    def _succeeded(plan: _Plan, result: Any) -> bool:
        message = _tool_message(result, plan.tool_call_id)
        if message is None or getattr(message, "status", None) == "error":
            return False
        text = _text(message)
        if plan.tool in _WRITE_TOOLS:
            # "OK", or "OK" then a blank line and the syntax warning (sandbox/syntax_check.py).
            return text is not None and text.strip().partition("\n")[0].rstrip() == _SUCCESS
        return text is None or not text.lstrip().startswith("Error:")

    def _records(self, plan: _Plan, before: Probes, after: Probes) -> tuple[list[TouchRecord], list[tuple[str, str]]]:
        """The touches to record, and the ``(mount_path, name)`` entries a shell command removed."""
        records: list[TouchRecord] = []
        removed: list[tuple[str, str]] = []
        for ref in plan.refs:
            probe_before = before.get(ref.key)
            probe_after = after.get(ref.key)
            state_before = probe_before.state if probe_before is not None else None
            state_after = probe_after.state if probe_after is not None else None
            if plan.op == OP_SHELL:
                if state_before is None or state_after is None:
                    continue  # host not visible
                if state_after == "missing":
                    if state_before in ("dir", "file"):
                        removed.append(ref.key)
                    continue
                created = state_before == "missing"
                kind = "dir" if state_after == "dir" else "file"
            else:
                created = state_before == "missing"
                kind = "dir" if state_before == "dir" else "file" if state_before == "file" else ref.kind
            records.append(
                TouchRecord(
                    mount_path=ref.mount.container_path,
                    name=ref.name,
                    kind=kind,
                    rel_path=ref.rel_path,
                    op=plan.op,
                    created=created,
                    user_id=plan.user_id,
                    thread_id=plan.thread_id,
                    run_id=plan.run_id,
                    tool_call_id=plan.tool_call_id,
                    host_root=host_root_key(ref.mount),
                    entry_before=probe_before.identity if probe_before is not None else None,
                    entry_after=probe_after.identity if probe_after is not None else None,
                )
            )
        return records, removed

    # -- storage (blocking; worker threads only) --------------------------

    def _default_store(self) -> FolderLedgerRecorderStore | None:
        url = getattr(self._database, "app_sync_sqlalchemy_url", None)
        if not isinstance(url, str) or not url:
            return None
        from deerflow.persistence.agents.sql import get_sync_sessionmaker

        return FolderLedgerRecorderStore(get_sync_sessionmaker(url))

    def _write(self, records: list[TouchRecord], removed: list[tuple[str, str]]) -> None:
        if self._store is None:
            if self._store_unavailable:
                return
            try:
                self._store = self._store_factory()
            except Exception:
                # A missing sync driver would otherwise log on every write.
                self._store_unavailable = True
                logger.warning("folder ledger: the synchronous database engine is unavailable; recording is off for this agent", exc_info=True)
                return
        if self._store is not None:
            self._store.record(records, removed)

    def _safe_plan(self, request: ToolCallRequest) -> _Plan | None:
        try:
            return self._plan(request)
        except Exception:
            logger.warning("folder ledger: could not inspect a tool call; it runs unrecorded", exc_info=True)
            return None

    @staticmethod
    def _safe_probe(refs: tuple[FolderRef, ...]) -> Probes:
        try:
            return _probe_all(refs)
        except Exception:
            logger.debug("folder ledger: host probe failed; treating folders as not visible", exc_info=True)
            return {}

    # -- wrappers ----------------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        plan = self._safe_plan(request)
        if plan is None:
            return handler(request)
        before = self._safe_probe(plan.refs)
        result = handler(request)
        try:
            if self._succeeded(plan, result):
                records, removed = self._records(plan, before, self._safe_probe(plan.refs))
                if records or removed:
                    self._write(records, removed)
        except Exception:
            logger.warning("folder ledger: could not record %s; the tool result is unchanged", plan.tool, exc_info=True)
        return result

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        plan = self._safe_plan(request)
        if plan is None:
            return await handler(request)
        try:
            before = await run_file_io(self._safe_probe, plan.refs)
        except Exception:
            logger.debug("folder ledger: host probe could not be scheduled", exc_info=True)
            before = {}
        result = await handler(request)
        try:
            if self._succeeded(plan, result):
                records, removed = self._records(plan, before, await run_file_io(self._safe_probe, plan.refs))
                if records or removed:
                    await self._await_write(records, removed)
        except Exception:
            logger.warning("folder ledger: could not record %s; the tool result is unchanged", plan.tool, exc_info=True)
        return result

    async def _await_write(self, records: list[TouchRecord], removed: list[tuple[str, str]]) -> None:
        """Wait (bounded) for the worker-thread write; a slow database only stops the wait."""
        task = asyncio.ensure_future(asyncio.to_thread(self._write, records, removed))
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=WRITE_WAIT_SECONDS)
        except TimeoutError:
            logger.warning("folder ledger: write still running after %.0fs; continuing without waiting", WRITE_WAIT_SECONDS)
            task.add_done_callback(_log_late_failure)
        except asyncio.CancelledError:
            task.add_done_callback(_log_late_failure)
            raise


def _log_late_failure(task: asyncio.Future[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("folder ledger: late write failed: %s", type(error).__name__)
