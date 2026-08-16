"""Tests for scripts/backup.py — whole-instance backup and restore (roadmap item 8).

The load-bearing behaviors, in rough order of how badly getting them wrong hurts:

1. Credentials are excluded by default. A backup that quietly widens credential
   exposure is worse than no backup.
2. `--include-secrets` produces an owner-only archive, or nothing at all.
3. Restore refuses to write underneath a running stack.
4. Restore cannot be walked out of the target directory by a crafted archive.
5. File modes survive the round trip (0700/0600 credential dirs stay that way).
"""

from __future__ import annotations

import importlib.util
import json
import stat
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "backup.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("deerflow_backup", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = _load_script()


@pytest.fixture
def instance(tmp_path: Path) -> Path:
    """A minimal but realistic instance layout."""
    root = tmp_path / "deer-flow"
    home = root / "backend" / ".deer-flow"
    (home / "users" / "default" / "threads" / "t1" / "user-data" / "workspace").mkdir(parents=True)
    (home / "users" / "default" / "integrations" / "lark" / "config").mkdir(parents=True)

    (root / "config.yaml").write_text("config_version: 34\nmodels: []\n", encoding="utf-8")
    (root / "extensions_config.json").write_text(json.dumps({"skills": {}}), encoding="utf-8")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-real-secret\n", encoding="utf-8")

    (root / "skills" / "custom" / "my-skill").mkdir(parents=True)
    (root / "skills" / "custom" / "my-skill" / "SKILL.md").write_text("---\nname: my-skill\n---\n", encoding="utf-8")
    (root / "skills" / "public" / "builtin").mkdir(parents=True)
    (root / "skills" / "public" / "builtin" / "SKILL.md").write_text("---\nname: builtin\n---\n", encoding="utf-8")

    (home / "users" / "default" / "memory.json").write_text('{"version": 2}', encoding="utf-8")
    (home / "users" / "default" / "ui_state.json").write_text('{"chat_tabs": []}', encoding="utf-8")
    (home / "runtime_settings.json").write_text('{"multi_user_mode": false}', encoding="utf-8")
    (home / "aux_usage.sqlite3").write_bytes(b"SQLite format 3\x00")
    (home / "deerflow.sqlite3").write_bytes(b"SQLite format 3\x00")
    (home / "users" / "default" / "threads" / "t1" / "user-data" / "workspace" / "note.md").write_text("hi", encoding="utf-8")

    creds = home / "users" / "default" / "integrations" / "lark" / "config" / "app.json"
    creds.write_text('{"appSecret": "very-secret"}', encoding="utf-8")
    creds.chmod(0o600)
    (home / "users" / "default" / "integrations").chmod(0o700)
    return root


def _members(archive: Path) -> set[str]:
    with tarfile.open(archive, "r:gz") as tar:
        return {m.name for m in tar.getmembers()}


# ---------------------------------------------------------------------------
# What goes in
# ---------------------------------------------------------------------------


class TestCreate:
    def test_includes_the_state_a_personal_instance_accumulates(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        names = _members(archive)
        assert any(n.endswith("config.yaml") for n in names)
        assert any(n.endswith("extensions_config.json") for n in names)
        assert any("memory.json" in n for n in names)
        assert any("ui_state.json" in n for n in names)
        assert any("runtime_settings.json" in n for n in names)
        assert any("aux_usage.sqlite3" in n for n in names)
        assert any("deerflow.sqlite3" in n for n in names)
        assert any("note.md" in n for n in names)
        assert any("skills/custom/my-skill/SKILL.md" in n for n in names)

    def test_public_skills_are_not_backed_up(self, instance, tmp_path):
        # They are committed to the repo; a restore onto a clean checkout has them.
        archive = backup.create_backup(instance, tmp_path / "out")
        assert not any("skills/public" in n for n in _members(archive))

    def test_credentials_are_excluded_by_default(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        names = _members(archive)
        assert not any("integrations" in n for n in names)
        assert not any(n.endswith(".env") for n in names)

    def test_the_manifest_records_that_secrets_were_excluded(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        with tarfile.open(archive, "r:gz") as tar:
            manifest = json.loads(tar.extractfile(f"{backup.ARCHIVE_ROOT}/{backup.MANIFEST_NAME}").read())
        assert manifest["includes_secrets"] is False
        assert manifest["version"] == backup.MANIFEST_VERSION
        assert "excluded" in manifest
        assert any("integrations" in entry for entry in manifest["excluded"])

    def test_include_secrets_opts_in_explicitly(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out", include_secrets=True)
        names = _members(archive)
        assert any("integrations" in n and "app.json" in n for n in names)
        assert any(n.endswith(".env") for n in names)

    def test_a_secret_bearing_archive_is_owner_only(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out", include_secrets=True)
        mode = stat.S_IMODE(archive.stat().st_mode)
        assert mode == 0o600, oct(mode)

    def test_a_secret_free_archive_is_still_not_world_readable(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        mode = stat.S_IMODE(archive.stat().st_mode)
        assert not (mode & 0o077), oct(mode)

    def test_archive_name_is_timestamped(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        assert archive.name.startswith("deerflow-backup-")
        assert archive.name.endswith(".tar.gz")

    def test_file_modes_are_recorded_in_the_archive(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out", include_secrets=True)
        with tarfile.open(archive, "r:gz") as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith("integrations/lark/config/app.json"))
            assert stat.S_IMODE(member.mode) == 0o600


# ---------------------------------------------------------------------------
# Database handling
# ---------------------------------------------------------------------------


class TestDatabaseBackend:
    def test_sqlite_file_is_copied_as_part_of_the_home_tree(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        assert any("deerflow.sqlite3" in n for n in _members(archive))

    def test_postgres_is_dumped_explicitly(self, instance, tmp_path):
        (instance / "config.yaml").write_text(
            "database:\n  backend: postgres\n  url: postgresql://u:p@localhost/deerflow\n",
            encoding="utf-8",
        )
        calls = []

        def fake_dump(url, destination):
            calls.append(url)
            destination.write_text("-- pg_dump output\n", encoding="utf-8")
            return True

        archive = backup.create_backup(instance, tmp_path / "out", pg_dump=fake_dump)
        assert calls and calls[0].startswith("postgresql://")
        assert any(n.endswith(backup.PG_DUMP_NAME) for n in _members(archive))

    def test_a_failed_postgres_dump_aborts_rather_than_shipping_a_partial_backup(self, instance, tmp_path):
        (instance / "config.yaml").write_text("database:\n  backend: postgres\n  url: postgresql://u:p@h/db\n", encoding="utf-8")

        def failing_dump(url, destination):
            return False

        with pytest.raises(backup.BackupError, match="pg_dump"):
            backup.create_backup(instance, tmp_path / "out", pg_dump=failing_dump)

    def test_the_manifest_names_the_database_backend(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        with tarfile.open(archive, "r:gz") as tar:
            manifest = json.loads(tar.extractfile(f"{backup.ARCHIVE_ROOT}/{backup.MANIFEST_NAME}").read())
        assert manifest["database_backend"] == "sqlite"


# ---------------------------------------------------------------------------
# Restore safety
# ---------------------------------------------------------------------------


class TestRestoreSafety:
    def test_refuses_while_the_stack_is_running(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        with pytest.raises(backup.BackupError, match="running"):
            backup.restore_backup(archive, instance, is_running=lambda: ["Gateway (127.0.0.1:8001)"])

    def test_the_refusal_names_what_is_running_and_how_to_stop_it(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        with pytest.raises(backup.BackupError) as excinfo:
            backup.restore_backup(archive, instance, is_running=lambda: ["Gateway (127.0.0.1:8001)"])
        assert "8001" in str(excinfo.value)
        assert "make stop" in str(excinfo.value)

    def test_force_overrides_the_running_check(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        target = tmp_path / "restored"
        backup.restore_backup(archive, target, is_running=lambda: ["Gateway"], force=True)
        assert (target / "config.yaml").exists()

    def _evil_archive(self, tmp_path: Path, arcname: str, name: str) -> Path:
        """A well-formed archive — valid manifest and all — carrying one bad member.

        The manifest is real on purpose: an archive that fails the manifest gate
        never reaches the path check, so testing without one would assert
        nothing about traversal defense.
        """
        archive = tmp_path / name
        payload = tmp_path / "payload"
        payload.write_text("pwned", encoding="utf-8")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"version": backup.MANIFEST_VERSION, "includes_secrets": False, "database_backend": "sqlite", "file_count": 1, "excluded": []}),
            encoding="utf-8",
        )
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(manifest, arcname=f"{backup.ARCHIVE_ROOT}/{backup.MANIFEST_NAME}")
            tar.add(payload, arcname=arcname)
        return archive

    def test_a_traversing_member_is_refused(self, tmp_path):
        archive = self._evil_archive(tmp_path, f"{backup.ARCHIVE_ROOT}/../../escaped.txt", "evil.tar.gz")
        with pytest.raises(backup.BackupError, match="unsafe"):
            backup.restore_backup(archive, tmp_path / "target", is_running=lambda: [])
        assert not (tmp_path.parent / "escaped.txt").exists()

    def test_an_absolute_member_is_refused(self, tmp_path):
        archive = self._evil_archive(tmp_path, "/etc/deerflow-pwned", "evil2.tar.gz")
        with pytest.raises(backup.BackupError, match="unsafe"):
            backup.restore_backup(archive, tmp_path / "target", is_running=lambda: [])

    def test_a_member_outside_the_archive_root_is_refused(self, tmp_path):
        archive = self._evil_archive(tmp_path, "elsewhere/payload.txt", "evil3.tar.gz")
        with pytest.raises(backup.BackupError, match="unsafe"):
            backup.restore_backup(archive, tmp_path / "target", is_running=lambda: [])

    def test_an_archive_without_a_manifest_is_refused(self, tmp_path):
        archive = tmp_path / "notours.tar.gz"
        payload = tmp_path / "payload"
        payload.write_text("x", encoding="utf-8")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(payload, arcname=f"{backup.ARCHIVE_ROOT}/random.txt")
        with pytest.raises(backup.BackupError, match="manifest"):
            backup.restore_backup(archive, tmp_path / "target", is_running=lambda: [])


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_state_lands_intact_on_a_clean_target(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        target = tmp_path / "clean"
        target.mkdir()
        backup.restore_backup(archive, target, is_running=lambda: [])

        assert (target / "config.yaml").read_text(encoding="utf-8").startswith("config_version: 34")
        assert (target / "extensions_config.json").exists()
        assert (target / "skills" / "custom" / "my-skill" / "SKILL.md").exists()
        home = target / "backend" / ".deer-flow"
        assert json.loads((home / "runtime_settings.json").read_text())["multi_user_mode"] is False
        assert (home / "users" / "default" / "memory.json").exists()
        assert (home / "users" / "default" / "threads" / "t1" / "user-data" / "workspace" / "note.md").read_text() == "hi"

    def test_credential_modes_survive_the_round_trip(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out", include_secrets=True)
        target = tmp_path / "clean2"
        backup.restore_backup(archive, target, is_running=lambda: [])
        restored = target / "backend" / ".deer-flow" / "users" / "default" / "integrations" / "lark" / "config" / "app.json"
        assert stat.S_IMODE(restored.stat().st_mode) == 0o600
        assert stat.S_IMODE((target / "backend" / ".deer-flow" / "users" / "default" / "integrations").stat().st_mode) == 0o700

    def test_restoring_a_secret_free_archive_leaves_existing_credentials_alone(self, instance, tmp_path):
        # The default archive has no integrations/; restore must not delete the
        # ones already on the target machine just because the backup omits them.
        archive = backup.create_backup(instance, tmp_path / "out")
        creds = instance / "backend" / ".deer-flow" / "users" / "default" / "integrations" / "lark" / "config" / "app.json"
        backup.restore_backup(archive, instance, is_running=lambda: [])
        assert creds.exists()

    def test_inspect_reports_the_manifest_without_extracting(self, instance, tmp_path):
        archive = backup.create_backup(instance, tmp_path / "out")
        info = backup.inspect_backup(archive)
        assert info["includes_secrets"] is False
        assert info["database_backend"] == "sqlite"
        assert info["file_count"] > 0


# ---------------------------------------------------------------------------
# Running-stack detection
# ---------------------------------------------------------------------------


class TestRunningDetection:
    def test_reports_each_listening_service_by_name(self):
        running = backup.detect_running_services(probe=lambda host, port: port in (8001, 2026))
        assert len(running) == 2
        assert any("8001" in entry for entry in running)

    def test_nothing_listening_is_an_empty_list(self):
        assert backup.detect_running_services(probe=lambda host, port: False) == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_create_then_restore_via_cli(self, instance, tmp_path, capsys):
        assert backup.main(["create", "--project-root", str(instance), "--output-dir", str(tmp_path / "out")]) == 0
        archives = list((tmp_path / "out").glob("*.tar.gz"))
        assert len(archives) == 1
        capsys.readouterr()

        target = tmp_path / "cli-restore"
        code = backup.main(["restore", str(archives[0]), "--project-root", str(target), "--force"])
        assert code == 0
        assert (target / "config.yaml").exists()

    def test_restore_refusal_exits_non_zero_with_a_readable_message(self, instance, tmp_path, capsys):
        backup.main(["create", "--project-root", str(instance), "--output-dir", str(tmp_path / "out")])
        archive = next((tmp_path / "out").glob("*.tar.gz"))
        capsys.readouterr()
        code = backup.main(["restore", str(archive), "--project-root", str(instance), "--assume-running"])
        assert code == 1
        assert "running" in capsys.readouterr().err
