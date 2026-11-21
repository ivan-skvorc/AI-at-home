"""The skill ledger and its curator (FORK.md §55).

The curator switches skills off, so its guards are the test: it must only ever
touch skills the *agent* wrote, judge them from their last activity (a load,
else a write), leave alone a skill the user switched back on, and run at most
daily. Usage counting is the evidence it judges by.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from deerflow.skills.learning import CURATE_INTERVAL, SkillLedger

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


@dataclass
class _Skill:
    name: str
    category: str


class _Storage:
    """The slice of UserScopedSkillStorage the curator uses."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.history: dict[str, list[dict]] = {}
        self.enabled: dict[str, bool] = {}
        self.categories: dict[str, str] = {}

    def add(self, name: str, *, category: str = "custom", author: str | None = "agent", written: datetime | None = None, mtime: datetime | None = None) -> None:
        self.categories[name] = category
        self.enabled[name] = True
        skill_file = self.root / name / "SKILL.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text("---\nname: x\n---\n", encoding="utf-8")
        stamp = (mtime or written or NOW).timestamp()
        import os

        os.utime(skill_file, (stamp, stamp))
        if author is not None:
            self.history[name] = [{"ts": (written or NOW).isoformat(), "action": "create", "author": author}]

    def load_skills(self, *, enabled_only: bool = False):
        return [_Skill(name, self.categories[name]) for name, on in self.enabled.items() if on or not enabled_only]

    def read_history(self, name: str) -> list[dict]:
        return self.history.get(name, [])

    def get_custom_skill_file(self, name: str) -> Path:
        return self.root / name / "SKILL.md"

    def set_skill_enabled_state(self, name: str, enabled: bool) -> None:
        self.enabled[name] = enabled


def test_record_use_counts_each_skill_once_per_call(tmp_path) -> None:
    ledger = SkillLedger(tmp_path)
    ledger.record_use(["deploy", "deploy", "review"], now=NOW)
    ledger.record_use(["deploy"], now=NOW + timedelta(hours=1))

    assert ledger.stats("deploy")["use_count"] == 2
    assert ledger.stats("deploy")["last_used_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert ledger.stats("review")["use_count"] == 1
    assert ledger.path == tmp_path / ".learning" / "ledger.json"


def test_an_unreadable_ledger_starts_fresh_instead_of_failing(tmp_path) -> None:
    ledger = SkillLedger(tmp_path)
    ledger.path.parent.mkdir(parents=True)
    ledger.path.write_text("{not json", encoding="utf-8")
    ledger.record_use(["deploy"], now=NOW)
    assert json.loads(ledger.path.read_text(encoding="utf-8"))["skills"]["deploy"]["use_count"] == 1


def test_only_unused_agent_written_custom_skills_are_switched_off(tmp_path) -> None:
    storage = _Storage(tmp_path)
    old = NOW - timedelta(days=200)
    storage.add("agent-old", written=old)
    storage.add("agent-recent", written=NOW - timedelta(days=10))
    storage.add("user-old", author="user", written=old)
    storage.add("installed-old", author=None, mtime=old)
    storage.add("public-old", category="public", written=old)
    ledger = SkillLedger(tmp_path)

    result = ledger.curate(storage, archive_after_days=90, now=NOW)

    assert result.archived == ["agent-old"]
    assert storage.enabled == {"agent-old": False, "agent-recent": True, "user-old": True, "installed-old": True, "public-old": True}
    assert ledger.stats("agent-old")["state"] == "archived"


def test_a_recent_load_keeps_an_old_skill_on(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = SkillLedger(tmp_path)
    ledger.record_use(["agent-old"], now=NOW - timedelta(days=5))

    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == []
    assert storage.enabled["agent-old"] is True


def test_a_skill_the_user_switched_back_on_is_left_on(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = SkillLedger(tmp_path)
    ledger.curate(storage, archive_after_days=90, now=NOW)
    storage.set_skill_enabled_state("agent-old", True)  # Settings → Skills

    later = NOW + CURATE_INTERVAL * 3
    assert ledger.curate(storage, archive_after_days=90, now=later).archived == []
    assert storage.enabled["agent-old"] is True


def test_loading_an_archived_skill_makes_it_active_again(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = SkillLedger(tmp_path)
    ledger.curate(storage, archive_after_days=90, now=NOW)
    ledger.record_use(["agent-old"], now=NOW + timedelta(days=1))

    assert ledger.stats("agent-old")["state"] == "active"
    assert "archived_at" not in ledger.stats("agent-old")


def test_zero_days_disables_the_curator_and_it_runs_at_most_daily(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = SkillLedger(tmp_path)

    assert ledger.curate(storage, archive_after_days=0, now=NOW).archived == []
    assert storage.enabled["agent-old"] is True

    assert ledger.curation_due(now=NOW)
    ledger.curate(storage, archive_after_days=90, now=NOW)
    assert not ledger.curation_due(now=NOW + CURATE_INTERVAL - timedelta(minutes=1))
    assert ledger.curation_due(now=NOW + CURATE_INTERVAL)


def test_a_failed_switch_off_is_skipped_not_raised(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))

    def refuse(name, enabled):
        raise PermissionError("read-only")

    storage.set_skill_enabled_state = refuse
    ledger = SkillLedger(tmp_path)
    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == []
    assert ledger.stats("agent-old").get("state") != "archived"
