"""Tests for the `update` subcommand added to scripts/searxng.sh.

`docker` is faked with a throwaway executable on PATH (the script runs in a
subprocess, so a shell function would not be inherited) that records its argv
and simulates the running / not-running container states. Keeps the test
hermetic — no real Docker, no real SearXNG.

Run from repo root:
    cd backend && uv run pytest tests/test_searxng_update_script.py -v
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "searxng.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(p) for p in BASH_CANDIDATES if p is not None and p.exists() and "WindowsApps" not in str(p)),
    None,
)

if BASH_EXECUTABLE is None:
    pytestmark = pytest.mark.skip(reason="bash is required for searxng.sh tests")


def _write_fake_docker(bin_dir: Path, log: Path, *, container_running: bool) -> None:
    """A fake `docker` that logs argv and simulates `compose ps -q searxng`."""
    ps_output = "deadbeefcafe" if container_running else ""
    script = f"""#!/usr/bin/env bash
echo "$*" >> "{log}"
# `docker compose ... ps -q searxng` decides whether a recreate happens.
for arg in "$@"; do
    if [ "$arg" = "ps" ]; then
        printf '%s' "{ps_output}"
        exit 0
    fi
done
# pull / up / anything else: succeed quietly.
exit 0
"""
    docker = bin_dir / "docker"
    docker.write_text(script, encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_update(tmp_path: Path, *, container_running: bool) -> tuple[subprocess.CompletedProcess, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    _write_fake_docker(bin_dir, log, container_running=container_running)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    proc = subprocess.run(
        [BASH_EXECUTABLE, str(SCRIPT_PATH), "update"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    log_text = log.read_text(encoding="utf-8") if log.exists() else ""
    return proc, log_text


class TestSearxngUpdate:
    def test_pulls_and_recreates_when_running(self, tmp_path: Path):
        proc, log = _run_update(tmp_path, container_running=True)
        assert proc.returncode == 0, proc.stderr
        assert "pull searxng" in log
        assert "up -d searxng" in log  # recreated because it was running

    def test_pulls_but_skips_recreate_when_not_running(self, tmp_path: Path):
        proc, log = _run_update(tmp_path, container_running=False)
        assert proc.returncode == 0, proc.stderr
        assert "pull searxng" in log
        assert "up -d searxng" not in log  # nothing to recreate

    def test_unknown_command_still_rejected(self, tmp_path: Path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write_fake_docker(bin_dir, tmp_path / "d.log", container_running=False)
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        proc = subprocess.run(
            [BASH_EXECUTABLE, str(SCRIPT_PATH), "bogus"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert proc.returncode == 1
        assert "Usage:" in proc.stdout + proc.stderr
