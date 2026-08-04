"""Tests for scripts/update_camoufox_searxng.py — the daily auto-update loop.

The updater closes two self-update gaps: the Camoufox browser binaries (only
ever *fetched when absent* by ensure_camoufox.py) and the bundled SearXNG
:latest image (Docker only pulls :latest when missing locally). These tests pin
the decision logic, the injected-runner wiring, and the launch-time throttle —
no real ``camoufox``, ``docker``, or filesystem side effects.

Run from repo root:
    cd backend && uv run pytest tests/test_update_camoufox_searxng.py -v
"""

from __future__ import annotations

from pathlib import Path

import update_camoufox_searxng as upd

# ---------------------------------------------------------------------------
# Config fixtures (mirror test_detect_searxng.py)
# ---------------------------------------------------------------------------

SEARXNG_CONFIG = """
tools:
  - name: web_search
    group: web
    use: deerflow.community.searxng.tools:web_search_tool
    base_url: http://localhost:8088
"""

DDG_CONFIG = """
tools:
  - name: web_search
    group: web
    use: deerflow.community.ddg_search.tools:web_search_tool
"""


# ---------------------------------------------------------------------------
# Camoufox
# ---------------------------------------------------------------------------


class TestUpdateCamoufox:
    def test_skips_when_not_installed(self):
        calls: list[list[str]] = []
        result = upd.update_camoufox(installed=lambda: False, run=lambda cmd: calls.append(cmd) or 0)
        assert result == "skipped"
        assert calls == []  # fetch never launched

    def test_runs_fetch_when_installed(self):
        calls: list[list[str]] = []
        result = upd.update_camoufox(installed=lambda: True, run=lambda cmd: calls.append(cmd) or 0)
        assert result == "ok"
        assert len(calls) == 1
        assert calls[0][1:] == ["-m", "camoufox", "fetch"]

    def test_dry_run_does_not_launch_fetch(self):
        calls: list[list[str]] = []
        result = upd.update_camoufox(installed=lambda: True, run=lambda cmd: calls.append(cmd) or 0, dry_run=True)
        assert result == "would-update"
        assert calls == []

    def test_nonzero_fetch_is_failed(self):
        result = upd.update_camoufox(installed=lambda: True, run=lambda cmd: 1)
        assert result == "failed"

    def test_fetch_launch_exception_is_swallowed(self):
        def boom(cmd):
            raise OSError("no python")

        result = upd.update_camoufox(installed=lambda: True, run=boom)
        assert result == "failed"  # never raises


# ---------------------------------------------------------------------------
# SearXNG decision (should_update_searxng)
# ---------------------------------------------------------------------------


class TestShouldUpdateSearxng:
    def test_true_when_provider_used_and_no_explicit_url(self):
        assert upd.should_update_searxng(SEARXNG_CONFIG, {}) is True

    def test_false_when_provider_not_used(self):
        assert upd.should_update_searxng(DDG_CONFIG, {}) is False

    def test_true_when_config_unreadable(self):
        # None config_text (unreadable) → don't skip on the marker check.
        assert upd.should_update_searxng(None, {}) is True

    def test_true_for_in_network_default(self):
        assert upd.should_update_searxng(SEARXNG_CONFIG, {"DEER_FLOW_SEARXNG_BASE_URL": upd._detect.IN_NETWORK_URL}) is True

    def test_true_for_loopback_url(self):
        assert upd.should_update_searxng(SEARXNG_CONFIG, {"DEER_FLOW_SEARXNG_BASE_URL": "http://127.0.0.1:8088"}) is True

    def test_false_for_foreign_remote_url(self):
        # The operator points at their own instance — not ours to recreate.
        assert upd.should_update_searxng(SEARXNG_CONFIG, {"DEER_FLOW_SEARXNG_BASE_URL": "http://searx.example.com"}) is False


# ---------------------------------------------------------------------------
# SearXNG update orchestration
# ---------------------------------------------------------------------------


class TestUpdateSearxng:
    def test_skips_when_provider_unused(self):
        calls: list[str] = []
        result = upd.update_searxng(config_text=DDG_CONFIG, env={}, run_searxng_sh=lambda c: calls.append(c) or 0)
        assert result == "skipped"
        assert calls == []

    def test_skips_when_docker_missing(self):
        calls: list[str] = []
        result = upd.update_searxng(
            config_text=SEARXNG_CONFIG,
            env={},
            run_searxng_sh=lambda c: calls.append(c) or 0,
            docker_available=lambda: False,
        )
        assert result == "skipped-no-docker"
        assert calls == []

    def test_runs_update_subcommand(self):
        calls: list[str] = []
        result = upd.update_searxng(
            config_text=SEARXNG_CONFIG,
            env={},
            run_searxng_sh=lambda c: calls.append(c) or 0,
            docker_available=lambda: True,
        )
        assert result == "ok"
        assert calls == ["update"]

    def test_dry_run_does_not_invoke_runner(self):
        calls: list[str] = []
        result = upd.update_searxng(
            config_text=SEARXNG_CONFIG,
            env={},
            run_searxng_sh=lambda c: calls.append(c) or 0,
            docker_available=lambda: True,
            dry_run=True,
        )
        assert result == "would-update"
        assert calls == []

    def test_nonzero_runner_is_failed(self):
        result = upd.update_searxng(
            config_text=SEARXNG_CONFIG,
            env={},
            run_searxng_sh=lambda c: 1,
            docker_available=lambda: True,
        )
        assert result == "failed"

    def test_runner_exception_is_swallowed(self):
        def boom(cmd):
            raise OSError("no searxng.sh")

        result = upd.update_searxng(
            config_text=SEARXNG_CONFIG,
            env={},
            run_searxng_sh=boom,
            docker_available=lambda: True,
        )
        assert result == "failed"


# ---------------------------------------------------------------------------
# Throttle (--if-stale)
# ---------------------------------------------------------------------------


class TestThrottle:
    def test_missing_stamp_is_stale(self, tmp_path: Path):
        assert upd.is_stale(tmp_path / "nope.stamp", 24) is True

    def test_fresh_stamp_is_not_stale(self, tmp_path: Path):
        stamp = tmp_path / "auto-update.stamp"
        upd.touch_stamp(stamp, now=1000.0)
        assert upd.is_stale(stamp, 24, now=1000.0 + 3600) is False  # 1h < 24h

    def test_old_stamp_is_stale(self, tmp_path: Path):
        stamp = tmp_path / "auto-update.stamp"
        upd.touch_stamp(stamp, now=1000.0)
        assert upd.is_stale(stamp, 24, now=1000.0 + 25 * 3600) is True  # 25h >= 24h


# ---------------------------------------------------------------------------
# main() orchestration
# ---------------------------------------------------------------------------


class TestMain:
    def test_throttled_run_short_circuits(self, tmp_path: Path, monkeypatch):
        stamp = tmp_path / "auto-update.stamp"
        upd.touch_stamp(stamp)
        camoufox_called = []
        monkeypatch.setattr(upd, "update_camoufox", lambda **kw: camoufox_called.append(kw) or "ok")
        rc = upd.main(["--if-stale", "24", "--stamp", str(stamp)])
        assert rc == 0
        assert camoufox_called == []  # skipped by throttle

    def test_stale_run_executes_and_stamps(self, tmp_path: Path, monkeypatch):
        stamp = tmp_path / "auto-update.stamp"  # missing → stale
        seen = {"camoufox": 0, "searxng": 0}
        monkeypatch.setattr(upd, "update_camoufox", lambda **kw: seen.__setitem__("camoufox", seen["camoufox"] + 1) or "ok")
        monkeypatch.setattr(upd, "update_searxng", lambda **kw: seen.__setitem__("searxng", seen["searxng"] + 1) or "ok")
        rc = upd.main(["--if-stale", "24", "--stamp", str(stamp), "--config", str(tmp_path / "none.yaml")])
        assert rc == 0
        assert seen == {"camoufox": 1, "searxng": 1}
        assert stamp.exists()  # advanced the throttle

    def test_camoufox_only_skips_searxng(self, tmp_path: Path, monkeypatch):
        seen = {"camoufox": 0, "searxng": 0}
        monkeypatch.setattr(upd, "update_camoufox", lambda **kw: seen.__setitem__("camoufox", seen["camoufox"] + 1) or "ok")
        monkeypatch.setattr(upd, "update_searxng", lambda **kw: seen.__setitem__("searxng", seen["searxng"] + 1) or "ok")
        rc = upd.main(["--camoufox-only", "--stamp", str(tmp_path / "s.stamp")])
        assert rc == 0
        assert seen == {"camoufox": 1, "searxng": 0}

    def test_searxng_only_skips_camoufox(self, tmp_path: Path, monkeypatch):
        seen = {"camoufox": 0, "searxng": 0}
        monkeypatch.setattr(upd, "update_camoufox", lambda **kw: seen.__setitem__("camoufox", seen["camoufox"] + 1) or "ok")
        monkeypatch.setattr(upd, "update_searxng", lambda **kw: seen.__setitem__("searxng", seen["searxng"] + 1) or "ok")
        rc = upd.main(["--searxng-only", "--stamp", str(tmp_path / "s.stamp")])
        assert rc == 0
        assert seen == {"camoufox": 0, "searxng": 1}

    def test_dry_run_does_not_write_stamp(self, tmp_path: Path, monkeypatch):
        stamp = tmp_path / "auto-update.stamp"
        monkeypatch.setattr(upd, "update_camoufox", lambda **kw: "would-update")
        monkeypatch.setattr(upd, "update_searxng", lambda **kw: "would-update")
        rc = upd.main(["--dry-run", "--stamp", str(stamp), "--config", str(tmp_path / "none.yaml")])
        assert rc == 0
        assert not stamp.exists()
