"""The skill learning ledger: how often each custom skill is used, and the curator.

Closes the loop the ``skill_manage`` tool opens. The agent writes a skill, the
lead agent records every later load of it here, and the curator retires
agent-written skills nobody has loaded for ``archive_unused_after_days`` by
switching them off, so a library the agent grows on its own does not bloat
every system prompt with procedures that stopped being useful.

Design choices that are easy to undo by accident:

- **Only agent-written skills are curated.** A skill counts as agent-written
  when the first record of its ``.history/<name>.jsonl`` is a ``create`` by
  ``author: agent``. A skill the user wrote or installed is never switched off.
- **Archiving is a switch, not a deletion.** The skill's per-user enabled state
  goes to ``False`` (the same flag Settings → Skills toggles), so the user
  turns it back on in one click and nothing is lost.
- **A user's decision wins.** Once archived, the curator never touches the
  skill again: re-enabling it in Settings keeps it on even if it stays unused.
  Loading it again marks it active, which makes it eligible again later.
- **Never-used is not evidence.** A skill is judged from its last activity:
  its last load, or failing that its last write, so a skill created yesterday
  is not archived for having no loads yet.
- **Telemetry, never a gate.** Every failure here is logged and swallowed by
  the caller; a run never fails because the ledger could not be written.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LEDGER_DIRNAME = ".learning"
LEDGER_FILENAME = "ledger.json"
LEDGER_VERSION = 1
# The curator runs at most this often per user, from the end of a run.
CURATE_INTERVAL = timedelta(hours=24)

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


@dataclass(frozen=True)
class CurationResult:
    archived: list[str]
    checked: int


class SkillLedger:
    """Per-user usage counts for skills, stored beside the user's custom skills.

    ``root`` is the user's custom-skill root; the ledger lives in
    ``<root>/.learning/ledger.json``, a dot-directory the skill loader skips.
    """

    def __init__(self, root: Path) -> None:
        self.path = Path(root) / LEDGER_DIRNAME / LEDGER_FILENAME

    # -- storage -----------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": LEDGER_VERSION, "skills": {}}
        except (OSError, ValueError):
            logger.warning("Skill ledger at %s is unreadable; starting a fresh one", self.path, exc_info=True)
            return {"version": LEDGER_VERSION, "skills": {}}
        if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
            return {"version": LEDGER_VERSION, "skills": {}}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".ledger_", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            Path(tmp).replace(self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- recording -----------------------------------------------------------------

    def record_use(self, names: Iterable[str], *, now: datetime | None = None) -> None:
        """Count one load of each named skill (duplicates in ``names`` count once)."""
        unique = sorted({name for name in names if isinstance(name, str) and name})
        if not unique:
            return
        stamp = (now or datetime.now(UTC)).isoformat()
        with _lock_for(self.path):
            data = self.load()
            skills = data["skills"]
            for name in unique:
                entry = skills.setdefault(name, {"use_count": 0, "first_used_at": stamp})
                entry["use_count"] = int(entry.get("use_count", 0)) + 1
                entry["last_used_at"] = stamp
                if entry.get("state") == "archived":
                    # Loaded again (the user switched it back on and it is in use):
                    # it is an ordinary active skill from here on.
                    entry["state"] = "active"
                    entry.pop("archived_at", None)
            self._save(data)

    def stats(self, name: str) -> dict[str, Any]:
        return dict(self.load()["skills"].get(name, {}))

    # -- curation ------------------------------------------------------------------

    def curation_due(self, *, now: datetime | None = None) -> bool:
        last = _parse_ts(self.load().get("last_curated_at"))
        return last is None or (now or datetime.now(UTC)) - last >= CURATE_INTERVAL

    def curate(self, storage: Any, *, archive_after_days: int, now: datetime | None = None) -> CurationResult:
        """Switch off agent-written custom skills unused for ``archive_after_days``.

        ``storage`` is the user's ``UserScopedSkillStorage`` (anything with
        ``load_skills``, ``read_history``, ``get_custom_skill_file`` and
        ``set_skill_enabled_state``). A non-positive ``archive_after_days``
        disables the curator.
        """
        current = now or datetime.now(UTC)
        if archive_after_days <= 0:
            return CurationResult(archived=[], checked=0)
        cutoff = current - timedelta(days=archive_after_days)
        with _lock_for(self.path):
            data = self.load()
            skills_stats = data["skills"]
            archived: list[str] = []
            checked = 0
            for skill in storage.load_skills(enabled_only=True):
                category = getattr(getattr(skill, "category", None), "value", getattr(skill, "category", None))
                if category != "custom":
                    continue
                name = skill.name
                entry = skills_stats.get(name, {})
                if entry.get("state") == "archived":
                    continue
                history = _safe_history(storage, name)
                if not _agent_created(history):
                    continue
                checked += 1
                last_activity = max(
                    (ts for ts in (_parse_ts(entry.get("last_used_at")), _last_write(history), _mtime(storage, name)) if ts is not None),
                    default=None,
                )
                if last_activity is None or last_activity > cutoff:
                    continue
                try:
                    storage.set_skill_enabled_state(name, False)
                except Exception:
                    logger.warning("Curator could not switch off unused skill %r", name, exc_info=True)
                    continue
                entry = skills_stats.setdefault(name, {"use_count": 0})
                entry["state"] = "archived"
                entry["archived_at"] = current.isoformat()
                archived.append(name)
            data["last_curated_at"] = current.isoformat()
            self._save(data)
        return CurationResult(archived=archived, checked=checked)


def _safe_history(storage: Any, name: str) -> list[dict]:
    try:
        history = storage.read_history(name)
    except Exception:
        logger.debug("No readable history for skill %r", name, exc_info=True)
        return []
    return [record for record in history if isinstance(record, dict)]


def _agent_created(history: list[dict]) -> bool:
    return bool(history) and history[0].get("action") == "create" and history[0].get("author") == "agent"


def _last_write(history: list[dict]) -> datetime | None:
    stamps = [ts for ts in (_parse_ts(record.get("ts")) for record in history) if ts is not None]
    return max(stamps, default=None)


def _mtime(storage: Any, name: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(Path(storage.get_custom_skill_file(name)).stat().st_mtime, tz=UTC)
    except Exception:
        return None
