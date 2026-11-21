"""The skill ledger and its curator (FORK.md §55).

The curator switches skills off, so its guards are the test: it must only ever
touch skills the *agent* wrote (judged from the current lifecycle, not the
first history record), judge them from their last activity (a load, a write,
or when tracking started), leave alone a skill the user switched back on, and
run at most daily. Usage counting is the evidence it judges by, so a read
error, a held lock or a failed save must never wipe it, and the ledger must
live outside the custom-skill tree the sandbox projection hashes.
"""

import errno
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import deerflow.skills.learning as learning
from deerflow.skills.learning import CURATE_INTERVAL, SkillLedger

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
LONG_AGO = NOW - timedelta(days=365)


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

    def add(self, name: str, *, category: str = "custom", author: str | None = "agent", written: datetime | None = None, mtime: datetime | None = None, history: list[dict] | None = None) -> None:
        self.categories[name] = category
        self.enabled[name] = True
        skill_file = self.root / name / "SKILL.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text("---\nname: x\n---\n", encoding="utf-8")
        stamp = (mtime or written or NOW).timestamp()
        os.utime(skill_file, (stamp, stamp))
        if history is not None:
            self.history[name] = history
        elif author is not None:
            self.history[name] = [{"ts": (written or NOW).isoformat(), "action": "create", "author": author}]

    def load_skills(self, *, enabled_only: bool = False):
        return [_Skill(name, self.categories[name]) for name, on in self.enabled.items() if on or not enabled_only]

    def read_history(self, name: str) -> list[dict]:
        return self.history.get(name, [])

    def get_custom_skill_file(self, name: str) -> Path:
        return self.root / name / "SKILL.md"

    def set_skill_enabled_state(self, name: str, enabled: bool) -> None:
        self.enabled[name] = enabled


def _ledger(tmp_path: Path, *, tracking_since: datetime | None = LONG_AGO) -> SkillLedger:
    """A ledger that has been tracking loads since ``tracking_since`` (None: brand new)."""
    ledger = SkillLedger(tmp_path)
    if tracking_since is not None:
        ledger.path.parent.mkdir(parents=True, exist_ok=True)
        ledger.path.write_text(json.dumps({"version": 1, "skills": {}, "tracking_since": tracking_since.isoformat()}), encoding="utf-8")
    return ledger


def _on_disk(ledger: SkillLedger) -> dict:
    return json.loads(ledger.path.read_text(encoding="utf-8"))


def test_record_use_counts_each_skill_once_per_call(tmp_path) -> None:
    ledger = SkillLedger(tmp_path)
    assert ledger.record_use(["deploy", "deploy", "review"], now=NOW)
    ledger.record_use(["deploy"], now=NOW + timedelta(hours=1))

    assert ledger.stats("deploy")["use_count"] == 2
    assert ledger.stats("deploy")["last_used_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert ledger.stats("review")["use_count"] == 1
    assert _on_disk(ledger)["tracking_since"] == NOW.isoformat()


def test_an_undecodable_ledger_starts_fresh_instead_of_failing(tmp_path) -> None:
    ledger = SkillLedger(tmp_path)
    ledger.path.write_text("{not json", encoding="utf-8")
    ledger.record_use(["deploy"], now=NOW)
    assert _on_disk(ledger)["skills"]["deploy"]["use_count"] == 1


def test_malformed_entries_are_replaced_not_raised(tmp_path) -> None:
    ledger = SkillLedger(tmp_path)
    ledger.path.write_text(json.dumps({"version": 1, "skills": {"deploy": "garbage", "review": {"use_count": "many"}}}), encoding="utf-8")
    assert ledger.record_use(["deploy", "review"], now=NOW)
    assert ledger.stats("deploy")["use_count"] == 1 and ledger.stats("review")["use_count"] == 1


def test_the_ledger_lives_outside_the_projected_custom_tree(tmp_path) -> None:
    """Every write inside ``custom/`` changed the sandbox projection's source
    signature and forced a projection rebuild after each skill-loading run."""
    from deerflow.skills.projection import _update_tree_digest

    custom_root = tmp_path / "users" / "u1" / "skills" / "custom"
    (custom_root / "mine").mkdir(parents=True)
    (custom_root / "mine" / "SKILL.md").write_text("---\nname: mine\n---\n", encoding="utf-8")
    storage = SimpleNamespace(get_user_custom_root=lambda: custom_root)

    def signature() -> str:
        digest = hashlib.sha256()
        _update_tree_digest(digest, custom_root, "custom", follow_package_directory_symlinks=True)
        return digest.hexdigest()

    before = signature()
    ledger = SkillLedger.for_storage(storage)
    assert ledger.record_use(["mine"], now=NOW)
    assert ledger.record_use(["mine"], now=NOW + timedelta(minutes=1))

    assert ledger.path == custom_root.parent / "_skill_ledger.json"
    assert signature() == before


def test_a_read_error_skips_the_write_instead_of_wiping_the_ledger(tmp_path, monkeypatch) -> None:
    """Only an undecodable file starts fresh; a transient read error must not
    replace the archived markers and the curation date with an empty ledger."""
    ledger = SkillLedger(tmp_path)
    original = {"version": 1, "skills": {"old": {"use_count": 3, "state": "archived"}}, "last_curated_at": NOW.isoformat(), "tracking_since": LONG_AGO.isoformat()}
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    ledger.path.write_text(json.dumps(original), encoding="utf-8")
    failed = []

    def unreadable(read):
        def wrapper(self, *args, **kwargs):
            if self == ledger.path:
                failed.append(self)
                raise OSError(errno.EIO, "I/O error")
            return read(self, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(Path, "read_bytes", unreadable(Path.read_bytes))
    monkeypatch.setattr(Path, "read_text", unreadable(Path.read_text))

    assert not ledger.record_use(["new"], now=NOW)
    assert ledger.curate(_Storage(tmp_path), archive_after_days=90, now=NOW).archived == []
    assert not ledger.curation_due(now=NOW + CURATE_INTERVAL)
    assert failed  # the injected error fired
    monkeypatch.undo()
    assert _on_disk(ledger) == original


@pytest.mark.skipif(os.name == "nt", reason="the cross-process ledger lock is POSIX flock")
def test_a_writer_waits_for_another_process_and_then_skips(tmp_path, monkeypatch) -> None:
    import fcntl

    monkeypatch.setattr(learning, "LOCK_TIMEOUT_SECONDS", 0.1)
    ledger = SkillLedger(tmp_path)
    ledger.record_use(["deploy"], now=NOW)
    # A separate open file description conflicts with the ledger's own flock,
    # exactly as another Gateway process holding the lock would.
    with open(tmp_path / learning.LEDGER_LOCK_FILENAME, "a", encoding="utf-8") as other_process:
        fcntl.flock(other_process, fcntl.LOCK_EX)
        try:
            assert not ledger.record_use(["deploy"], now=NOW + timedelta(hours=1))
        finally:
            fcntl.flock(other_process, fcntl.LOCK_UN)
    assert ledger.stats("deploy")["use_count"] == 1
    assert ledger.record_use(["deploy"], now=NOW + timedelta(hours=2))
    assert ledger.stats("deploy")["use_count"] == 2


def test_record_skill_load_counts_only_while_skill_evolution_is_on(tmp_path, monkeypatch) -> None:
    custom_root = tmp_path / "users" / "u1" / "skills" / "custom"
    monkeypatch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", lambda user_id, **_kw: SimpleNamespace(get_user_custom_root=lambda: custom_root))
    on = SimpleNamespace(skill_evolution=SimpleNamespace(enabled=True))
    off = SimpleNamespace(skill_evolution=SimpleNamespace(enabled=False))

    assert not learning.record_skill_load("u1", "deploy", app_config=off, now=NOW)
    assert not (custom_root.parent / learning.LEDGER_FILENAME).exists()
    assert learning.record_skill_load("u1", "deploy", app_config=on, now=NOW)
    assert SkillLedger(custom_root.parent).stats("deploy")["use_count"] == 1


def test_only_unused_agent_written_custom_skills_are_switched_off(tmp_path) -> None:
    storage = _Storage(tmp_path)
    old = NOW - timedelta(days=200)
    storage.add("agent-old", written=old)
    storage.add("agent-recent", written=NOW - timedelta(days=10))
    storage.add("user-old", author="user", written=old)
    storage.add("installed-old", author=None, mtime=old)
    storage.add("public-old", category="public", written=old)
    ledger = _ledger(tmp_path)

    result = ledger.curate(storage, archive_after_days=90, now=NOW)

    assert result.archived == ["agent-old"]
    assert storage.enabled == {"agent-old": False, "agent-recent": True, "user-old": True, "installed-old": True, "public-old": True}
    assert ledger.stats("agent-old")["state"] == "archived"


def test_a_recent_load_keeps_an_old_skill_on(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = _ledger(tmp_path)
    ledger.record_use(["agent-old"], now=NOW - timedelta(days=5))

    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == []
    assert storage.enabled["agent-old"] is True


def test_a_skill_the_user_switched_back_on_is_left_on(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = _ledger(tmp_path)
    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == ["agent-old"]
    storage.set_skill_enabled_state("agent-old", True)  # Capability Center → Skills

    later = NOW + CURATE_INTERVAL * 3
    assert ledger.curate(storage, archive_after_days=90, now=later).archived == []
    assert storage.enabled["agent-old"] is True


def test_loading_an_archived_skill_makes_it_active_again(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = _ledger(tmp_path)
    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == ["agent-old"]
    ledger.record_use(["agent-old"], now=NOW + timedelta(days=1))

    assert ledger.stats("agent-old")["state"] == "active"
    assert "archived_at" not in ledger.stats("agent-old")


def test_zero_days_disables_the_curator_and_it_runs_at_most_daily(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = _ledger(tmp_path)

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
    ledger = _ledger(tmp_path)
    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == []
    assert ledger.stats("agent-old").get("state") != "archived"
    assert storage.enabled["agent-old"] is True


def test_an_upgraded_install_does_not_archive_on_its_first_pass(tmp_path) -> None:
    """Loads before the ledger existed were never counted, so the clock starts
    when tracking starts: a skill written 120 days ago and used daily since
    must not be switched off by the first curation after an upgrade."""
    storage = _Storage(tmp_path)
    storage.add("deploy-helper", written=NOW - timedelta(days=120))
    ledger = _ledger(tmp_path, tracking_since=None)

    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == []
    assert storage.enabled["deploy-helper"] is True
    assert _on_disk(ledger)["tracking_since"] == NOW.isoformat()

    # Still never loaded a full window later: now it is evidence.
    assert ledger.curate(storage, archive_after_days=90, now=NOW + timedelta(days=91)).archived == ["deploy-helper"]


def test_the_archived_marker_is_saved_before_the_switch_off(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = _ledger(tmp_path)
    seen = []

    def switch_off(name, enabled):
        seen.append(_on_disk(ledger)["skills"][name]["state"])
        storage.enabled[name] = enabled

    storage.set_skill_enabled_state = switch_off
    ledger.curate(storage, archive_after_days=90, now=NOW)
    assert seen == ["archived"]


def test_a_failed_final_save_still_reports_what_was_switched_off(tmp_path, monkeypatch) -> None:
    """The middleware refreshes the prompt caches from the returned names; a
    late failure must not hide a switch-off that already happened."""
    storage = _Storage(tmp_path)
    storage.add("agent-old", written=NOW - timedelta(days=200))
    ledger = _ledger(tmp_path)
    save = SkillLedger._save
    failures = []

    def save_unless_final(self, data):
        if "last_curated_at" in data:
            failures.append(data)
            raise OSError(errno.ENOSPC, "No space left on device")
        save(self, data)

    monkeypatch.setattr(SkillLedger, "_save", save_unless_final)
    result = ledger.curate(storage, archive_after_days=90, now=NOW)

    assert failures
    assert result.archived == ["agent-old"] and storage.enabled["agent-old"] is False
    assert ledger.stats("agent-old")["state"] == "archived"


def test_a_skill_reinstalled_after_an_agent_skill_was_deleted_is_not_curated(tmp_path) -> None:
    """History outlives a delete, and an install writes none: create(agent) ->
    human_delete -> the user installs their own skill of that name."""
    storage = _Storage(tmp_path)
    storage.add(
        "deploy",
        mtime=NOW - timedelta(days=200),
        history=[
            {"ts": (NOW - timedelta(days=300)).isoformat(), "action": "create", "author": "agent"},
            {"ts": (NOW - timedelta(days=250)).isoformat(), "action": "human_delete", "author": "human"},
        ],
    )
    ledger = _ledger(tmp_path)

    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == []
    assert storage.enabled["deploy"] is True


def test_an_agent_skill_created_after_a_deletion_is_curated(tmp_path) -> None:
    storage = _Storage(tmp_path)
    storage.add(
        "deploy",
        history=[
            {"ts": (NOW - timedelta(days=300)).isoformat(), "action": "human_delete", "author": "human"},
            {"ts": (NOW - timedelta(days=200)).isoformat(), "action": "create", "author": "agent"},
            {"ts": (NOW - timedelta(days=150)).isoformat(), "action": "patch", "author": "agent"},
        ],
        mtime=NOW - timedelta(days=150),
    )
    ledger = _ledger(tmp_path)

    assert ledger.curate(storage, archive_after_days=90, now=NOW).archived == ["deploy"]
