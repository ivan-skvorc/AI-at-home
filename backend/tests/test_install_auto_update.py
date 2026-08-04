"""Tests for scripts/install_auto_update.py — the daily systemd-timer installer.

Only the pure unit-file / cron content generation and the XDG unit-dir
resolution are exercised; the real ``systemctl`` side effects are not.

Run from repo root:
    cd backend && uv run pytest tests/test_install_auto_update.py -v
"""

from __future__ import annotations

from pathlib import Path

import install_auto_update as inst


class TestServiceUnit:
    def test_is_oneshot_running_the_updater_via_uv(self):
        content = inst.service_unit(Path("/repo"), "/usr/bin/uv")
        assert "Type=oneshot" in content
        assert "WorkingDirectory=/repo/backend" in content
        assert "ExecStart=/usr/bin/uv run python /repo/scripts/update_camoufox_searxng.py --verbose" in content

    def test_tolerates_updater_self_reported_failure(self):
        # The updater swallows its own errors and exits 0/1; the unit must not
        # treat exit 1 as a systemd failure.
        content = inst.service_unit(Path("/repo"), "uv")
        assert "SuccessExitStatus=0 1" in content


class TestTimerUnit:
    def test_is_daily_persistent_and_jittered(self):
        content = inst.timer_unit()
        assert "OnCalendar=daily" in content
        assert "Persistent=true" in content
        assert "RandomizedDelaySec=1h" in content
        assert "WantedBy=timers.target" in content


class TestCronLine:
    def test_daily_cron_line_runs_the_updater(self):
        line = inst.cron_line()
        # Five cron fields then the command.
        assert line.split()[0:5] == ["17", "4", "*", "*", "*"]
        assert "update_camoufox_searxng.py" in line
        assert "run python" in line


class TestUserUnitDir:
    def test_honors_xdg_config_home(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/cfg")
        assert inst.user_unit_dir() == Path("/custom/cfg/systemd/user")

    def test_defaults_to_home_config(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/tester")))
        assert inst.user_unit_dir() == Path("/home/tester/.config/systemd/user")


class TestPrintUnitsIsSideEffectFree:
    def test_print_mode_makes_no_changes(self, capsys):
        rc = inst.main(["--print"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "deer-flow-auto-update.service" in out
        assert "deer-flow-auto-update.timer" in out
