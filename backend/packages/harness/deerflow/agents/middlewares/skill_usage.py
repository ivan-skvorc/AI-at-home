"""Bounded, display-only snapshots of skill content actually loaded by the agent.

Kept on the producing message so normal run history supplies ownership, ordering
and persistence. This metadata must never be used for tool/secret authorization.

``record_skill_usage`` is also where a load is counted in the per-user skill
ledger (``deerflow.skills.learning``) while skill evolution is on, for the lead
agent and for subagents alike. Counting at the load, not from the messages left
at the end of a run, survives compaction and Goal continuations, and sees the
loads of subagents, whose messages never reach the lead's state.
"""

import functools
import hashlib
import logging
import os
import posixpath
import queue
import threading
from collections.abc import Callable

import yaml

from deerflow.agents.middlewares.skill_context import _FRONT_MATTER_RE, build_skill_entry_metadata_from_read
from deerflow.sandbox.read_file_contract import READ_FILE_NO_CONTENT_RESULTS, READ_FILE_TRUNCATION_PREFIX

SKILL_USAGE_KEY = "skill_usage"
SKILL_USAGES_KEY = "skill_usages"
MAX_SKILL_SNAPSHOT_CHARS = 100_000
# Ledger jobs waiting for the recorder thread. Past this, a job is dropped (a
# lost count), so a stalled disk cannot grow memory without bound.
MAX_PENDING_LEDGER_JOBS = 256
logger = logging.getLogger(__name__)


class _LedgerRecorder:
    """One daemon thread that runs skill-ledger jobs in submission order.

    ``submit`` never blocks: it puts the job on a C-level ``SimpleQueue``, so
    the event loop and the tool call that loaded a skill never wait on the
    ledger's file lock or disk. The single worker keeps the order, so a
    curation queued at the end of a run runs after that run's loads.
    """

    def __init__(self) -> None:
        self._jobs: queue.SimpleQueue[Callable[[], object]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def submit(self, job: Callable[[], object]) -> bool:
        if self._jobs.qsize() >= MAX_PENDING_LEDGER_JOBS:
            logger.warning("Skill ledger queue is full; dropping one update")
            return False
        self._ensure_started()
        self._jobs.put(job)
        return True

    def flush(self, timeout: float | None = None) -> bool:
        """Wait until every job submitted before this call has run."""
        done = threading.Event()
        self._ensure_started()
        self._jobs.put(done.set)
        return done.wait(timeout)

    def _ensure_started(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="skill-ledger", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception:
                logger.warning("Skill ledger update failed; the run is unaffected", exc_info=True)


_recorder = _LedgerRecorder()


def _reset_recorder_after_fork() -> None:
    # A forked child has no recorder thread and must not share the parent's queue.
    global _recorder
    _recorder = _LedgerRecorder()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_recorder_after_fork)


def submit_skill_ledger_job(job: Callable[[], object]) -> bool:
    """Run ``job`` on the skill-ledger recorder thread; ``False`` when it was dropped."""
    return _recorder.submit(job)


def flush_skill_ledger_jobs(timeout: float | None = 10.0) -> bool:
    """Wait for the recorder to finish the jobs submitted so far (tests and shutdown)."""
    return _recorder.flush(timeout)


def _skill_evolution_config(context: dict) -> object | None:
    """The run's config when it has skill evolution on; reads no file."""
    config = context.get("app_config")
    if getattr(config, "skill_evolution", None) is None:
        from deerflow.config.app_config import peek_loaded_app_config

        config = peek_loaded_app_config()
    return config if getattr(getattr(config, "skill_evolution", None), "enabled", False) else None


def _count_in_ledger(runtime: object, context: dict, usage: dict) -> None:
    name = usage.get("name")
    if not isinstance(name, str) or not name:
        return
    try:
        config = _skill_evolution_config(context)
        if config is None:
            return
        from deerflow.runtime.user_context import resolve_runtime_user_id
        from deerflow.skills.learning import record_skill_load

        # The user id comes from the caller's context variables, so it is
        # resolved here; storage and the file write happen on the recorder.
        submit_skill_ledger_job(functools.partial(record_skill_load, resolve_runtime_user_id(runtime), name, app_config=config))
    except Exception:
        logger.warning("Failed to queue a skill load for the skill ledger", exc_info=True)


def record_skill_usage(runtime: object, usage: dict | None) -> None:
    """Register evidence before the next model callback snapshots canonical history."""
    context = getattr(runtime, "context", None)
    if usage is None or not isinstance(context, dict):
        return
    if isinstance(usage, dict):
        _count_in_ledger(runtime, context, usage)
    if context.get("is_subagent"):
        return
    journal = context.get("__run_journal")
    record = getattr(journal, "record_skill_usage", None)
    if callable(record):
        try:
            record(usage)
        except Exception:
            logger.warning("Failed to record skill usage display snapshot", exc_info=True)


def build_skill_usage(
    path: str,
    content: str,
    *,
    skills_root: str,
    activation: str = "automatic",
    name: str | None = None,
    category: str | None = None,
    partial: bool = False,
) -> dict | None:
    entry = build_skill_entry_metadata_from_read(path, content, skills_root=skills_root)
    if entry is None or not content.strip() or content.strip() in READ_FILE_NO_CONTENT_RESULTS:
        return None
    normalized_path = entry["path"]
    relative = posixpath.relpath(normalized_path, posixpath.normpath(skills_root))
    if name is None:
        match = _FRONT_MATTER_RE.match(content)
        try:
            metadata = yaml.safe_load(match.group(1)) if match else None
        except yaml.YAMLError:
            metadata = None
        value = metadata.get("name") if isinstance(metadata, dict) else None
        name = value if isinstance(value, str) and value.strip() else posixpath.basename(posixpath.dirname(normalized_path))
    return {
        "name": name[:256],
        "description": entry["description"],
        "category": category or {"public": "public", "custom": "custom", "integrations": "integrations", "legacy": "legacy"}.get(relative.split("/")[0], "legacy"),
        "path": normalized_path,
        "content": content[:MAX_SKILL_SNAPSHOT_CHARS],
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "activation": activation,
        "partial": partial or len(content) > MAX_SKILL_SNAPSHOT_CHARS or READ_FILE_TRUNCATION_PREFIX in content,
    }
