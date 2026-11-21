"""The skill learning ledger: how often each skill is loaded, and the curator.

Closes the loop the ``skill_manage`` tool opens. The agent writes a skill,
every later load of it is counted here when it happens (``read_file`` of its
``SKILL.md`` or a slash activation, by the lead agent or a subagent), and the
curator retires agent-written skills nobody has loaded for
``archive_unused_after_days`` by switching them off, so a library the agent
grows on its own does not bloat every system prompt with procedures that
stopped being useful.

Design choices that are easy to undo by accident:

- **The ledger lives outside the projected skill tree.** It is
  ``<user skills root>/_skill_ledger.json``, beside ``_skill_states.json``.
  Inside ``custom/`` every write would change the sandbox projection's source
  signature and force a projection rebuild after each run that loaded a skill.
- **Only agent-written skills are curated.** Authorship comes from the
  skill's current lifecycle: the last ``create``/``delete``/``human_delete``
  record of its ``.history/<name>.jsonl`` must be a ``create`` by
  ``author: agent``. History outlives a delete, so a user's own skill
  installed under the name of a deleted agent skill is never touched.
- **Archiving is a switch, not a deletion.** The skill's per-user enabled state
  goes to ``False`` (the same flag Capability Center → Skills toggles), so
  it is turned back on in one click and nothing is lost. That toggle is
  admin-only, so the lead agent curates only for admins and for runs with no
  role (``CompletionReviewMiddleware``).
- **A user's decision wins.** The archived marker is saved before the skill
  is switched off; once archived, the curator never touches the skill again,
  so re-enabling it keeps it on even if it stays unused. Loading it again
  marks it active, which makes it eligible again later.
- **Never-used is not evidence.** A skill is judged from its last activity:
  its last load, its last write, or when this ledger started tracking
  (``tracking_since``), whichever is latest. A skill created yesterday, or one
  in daily use before the ledger existed, is not archived for having no loads.
- **One writer at a time, across processes.** Every read-modify-write holds a
  per-process lock and an advisory file lock, because Gateway workers share
  the home volume. Only a file that cannot be decoded starts fresh; a read
  error or a lock timeout skips the write, so a transient failure cannot wipe
  the archived markers.
- **Telemetry, never a gate.** Every failure here is logged and swallowed;
  a run never fails because the ledger could not be written.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from deerflow.utils.atomic_write import cleanup_failed_atomic_write
from deerflow.utils.file_lock import retry_until_locked

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

LEDGER_FILENAME = "_skill_ledger.json"
LEDGER_LOCK_FILENAME = ".skill_ledger.lock"
LEDGER_VERSION = 1
# The curator runs at most this often per user, from the end of a run.
CURATE_INTERVAL = timedelta(hours=24)
# A writer that cannot get the ledger within this long skips its update: a
# lost count is cheaper than a run (or the recorder queue) waiting on a peer.
LOCK_TIMEOUT_SECONDS = 2.0
# The history actions that start or end a skill's life under its name. An
# archive install writes no history, so a skill whose last lifecycle record is
# a delete was put back by hand or by an install, not by ``skill_manage``.
_LIFECYCLE_ACTIONS = frozenset({"create", "delete", "human_delete"})

_ledger_locks: dict[str, threading.Lock] = {}
_ledger_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _ledger_locks_guard:
        lock = _ledger_locks.get(key)
        if lock is None:
            lock = _ledger_locks[key] = threading.Lock()
        return lock


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _fresh() -> dict[str, Any]:
    return {"version": LEDGER_VERSION, "skills": {}}


@dataclass(frozen=True)
class CurationResult:
    archived: list[str]
    checked: int


class SkillLedger:
    """Per-user load counts for skills, stored in the user's skills root.

    ``skills_root`` is ``{DEER_FLOW_HOME}/users/<user>/skills/``, the parent of
    the user's custom-skill root; :meth:`for_storage` derives it.
    """

    def __init__(self, skills_root: Path) -> None:
        root = Path(skills_root)
        self.path = root / LEDGER_FILENAME
        self.lock_path = root / LEDGER_LOCK_FILENAME

    @classmethod
    def for_storage(cls, storage: Any) -> SkillLedger | None:
        """The ledger of a per-user storage, or ``None`` for storage without a user root."""
        root_getter = getattr(storage, "get_user_custom_root", None)
        if not callable(root_getter):
            return None
        return cls(Path(root_getter()).parent)

    # -- storage -----------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Return the ledger; a missing or undecodable file reads as a fresh one.

        Raises ``OSError`` when the file exists but cannot be read, so a caller
        never writes a fresh ledger over one it merely failed to read.
        """
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return _fresh()
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:  # UnicodeDecodeError and JSONDecodeError are both ValueErrors
            logger.warning("Skill ledger at %s cannot be decoded; starting a fresh one", self.path)
            return _fresh()
        if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
            logger.warning("Skill ledger at %s has an unexpected shape; starting a fresh one", self.path)
            return _fresh()
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".skill_ledger_", suffix=".json.tmp")
        tmp_path = Path(tmp)
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8", newline="")
            fd = None  # The file object now owns the descriptor.
            with handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            tmp_path.replace(self.path)
        except BaseException:
            cleanup_failed_atomic_write(tmp_path, fd)
            raise

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold this process's lock and, on POSIX, the cross-process file lock.

        Raises ``TimeoutError`` (an ``OSError``) when either is not acquired
        within ``LOCK_TIMEOUT_SECONDS``.
        """
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        process_lock = _lock_for(self.path)
        if not process_lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
            raise TimeoutError("Skill ledger lock timeout")
        try:
            if fcntl is None:  # pragma: no cover - Windows: the process lock is all there is
                yield
                return
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a", encoding="utf-8") as lock_file:
                retry_until_locked(
                    lambda: fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB),
                    interval=0.02,
                    deadline=deadline,
                    timeout_message="Skill ledger lock timeout",
                )
                try:
                    yield
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
        finally:
            process_lock.release()

    # -- recording -----------------------------------------------------------------

    def record_use(self, names: Iterable[str], *, now: datetime | None = None) -> bool:
        """Count one load of each named skill (duplicates in ``names`` count once).

        Returns ``False`` when the ledger could not be read, locked or written;
        the count is then lost and the file is left as it was.
        """
        unique = sorted({name for name in names if isinstance(name, str) and name})
        if not unique:
            return False
        stamp = (now or datetime.now(UTC)).isoformat()
        try:
            with self._locked():
                data = self.load()
                if _parse_ts(data.get("tracking_since")) is None:
                    data["tracking_since"] = stamp
                skills = data["skills"]
                for name in unique:
                    entry = skills.get(name)
                    if not isinstance(entry, dict):
                        entry = skills[name] = {"first_used_at": stamp}
                    entry["use_count"] = _count(entry.get("use_count")) + 1
                    entry["last_used_at"] = stamp
                    if entry.get("state") == "archived":
                        # Loaded again (the user switched it back on and it is in use):
                        # it is an ordinary active skill from here on.
                        entry["state"] = "active"
                        entry.pop("archived_at", None)
                self._save(data)
        except OSError:
            logger.warning("Skill ledger at %s could not be updated; this load is not counted", self.path, exc_info=True)
            return False
        return True

    def stats(self, name: str) -> dict[str, Any]:
        entry = self.load()["skills"].get(name, {})
        return dict(entry) if isinstance(entry, dict) else {}

    # -- curation ------------------------------------------------------------------

    def curation_due(self, *, now: datetime | None = None) -> bool:
        try:
            data = self.load()
        except OSError:
            logger.warning("Skill ledger at %s cannot be read; skipping curation", self.path, exc_info=True)
            return False
        last = _parse_ts(data.get("last_curated_at"))
        return last is None or (now or datetime.now(UTC)) - last >= CURATE_INTERVAL

    def curate(self, storage: Any, *, archive_after_days: int, now: datetime | None = None) -> CurationResult:
        """Switch off agent-written custom skills unused for ``archive_after_days``.

        ``storage`` is the user's ``UserScopedSkillStorage`` (anything with
        ``load_skills``, ``read_history``, ``get_custom_skill_file`` and
        ``set_skill_enabled_state``). A non-positive ``archive_after_days``
        disables the curator. Never raises: the names already switched off are
        returned even when a later step fails, so the caller can still refresh
        the prompt caches that list them.
        """
        current = now or datetime.now(UTC)
        archived: list[str] = []
        checked = 0
        if archive_after_days <= 0:
            return CurationResult(archived=archived, checked=checked)
        cutoff = current - timedelta(days=archive_after_days)
        try:
            with self._locked():
                data = self.load()
                skills_stats = data["skills"]
                tracking_since = _parse_ts(data.get("tracking_since"))
                if tracking_since is None:
                    # Loads before this ledger existed were never counted, so the
                    # clock for every skill starts now (an upgraded install).
                    tracking_since = current
                    data["tracking_since"] = current.isoformat()
                for skill in storage.load_skills(enabled_only=True):
                    category = getattr(getattr(skill, "category", None), "value", getattr(skill, "category", None))
                    if category != "custom":
                        continue
                    name = skill.name
                    previous = skills_stats.get(name)
                    entry = previous if isinstance(previous, dict) else {}
                    if entry.get("state") == "archived":
                        continue
                    history = _safe_history(storage, name)
                    if not _agent_written(history):
                        continue
                    checked += 1
                    candidates = (_parse_ts(entry.get("last_used_at")), _last_write(history), _mtime(storage, name), tracking_since)
                    if max(ts for ts in candidates if ts is not None) > cutoff:
                        continue
                    # Persist the decision before acting on it: the marker is what
                    # keeps a skill the user switches back on from being archived again.
                    skills_stats[name] = {**entry, "use_count": _count(entry.get("use_count")), "state": "archived", "archived_at": current.isoformat()}
                    try:
                        self._save(data)
                    except OSError:
                        _restore(skills_stats, name, previous)
                        logger.warning("Curator cannot record its decisions in %s; switching nothing off", self.path, exc_info=True)
                        break
                    try:
                        storage.set_skill_enabled_state(name, False)
                    except Exception:
                        logger.warning("Curator could not switch off unused skill %r", name, exc_info=True)
                        _restore(skills_stats, name, previous)
                        self._save_quietly(data)
                        continue
                    archived.append(name)
                data["last_curated_at"] = current.isoformat()
                self._save_quietly(data)
        except Exception:
            logger.warning("Skill curation for %s stopped early", self.path, exc_info=True)
        return CurationResult(archived=archived, checked=checked)

    def _save_quietly(self, data: dict[str, Any]) -> None:
        try:
            self._save(data)
        except OSError:
            logger.warning("Skill ledger at %s could not be written", self.path, exc_info=True)


def record_skill_load(user_id: str, name: str, *, app_config: Any = None, now: datetime | None = None) -> bool:
    """Count one load of ``name`` in ``user_id``'s ledger while skill evolution is on.

    The background recorder in ``agents/middlewares/skill_usage.py`` runs this
    off the caller's thread; it resolves the per-user storage here, because
    that may read the configuration file.
    """
    if app_config is None:
        from deerflow.config import get_app_config

        app_config = get_app_config()
    if not getattr(getattr(app_config, "skill_evolution", None), "enabled", False):
        return False
    from deerflow.skills.storage import get_or_new_user_skill_storage

    ledger = SkillLedger.for_storage(get_or_new_user_skill_storage(user_id, app_config=app_config))
    if ledger is None:
        return False
    return ledger.record_use([name], now=now)


def _restore(skills_stats: dict[str, Any], name: str, previous: Any) -> None:
    if previous is None:
        skills_stats.pop(name, None)
    else:
        skills_stats[name] = previous


def _safe_history(storage: Any, name: str) -> list[dict]:
    try:
        history = storage.read_history(name)
    except Exception:
        logger.debug("No readable history for skill %r", name, exc_info=True)
        return []
    return [record for record in history if isinstance(record, dict)]


def _agent_written(history: list[dict]) -> bool:
    """True when the skill's current life began with ``skill_manage``'s ``create``."""
    for record in reversed(history):
        if record.get("action") in _LIFECYCLE_ACTIONS:
            return record.get("action") == "create" and record.get("author") == "agent"
    return False


def _last_write(history: list[dict]) -> datetime | None:
    stamps = [ts for ts in (_parse_ts(record.get("ts")) for record in history) if ts is not None]
    return max(stamps, default=None)


def _mtime(storage: Any, name: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(Path(storage.get_custom_skill_file(name)).stat().st_mtime, tz=UTC)
    except Exception:
        return None
