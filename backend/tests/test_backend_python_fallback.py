"""scripts/backend-python.sh: the interpreter for scripts that need only PyYAML.

`make config-upgrade` and `make sandbox-enable` / `sandbox-disable` used to run
through `uv run` inside backend/, so on a Docker-only host (`make up`, no uv, no
backend/.venv) they failed before the script started, although both scripts
need nothing but PyYAML. The helper prefers the backend environment where
`make install` built one and falls back to the host's python3 otherwise.

Each case runs a copy of the helper inside a throwaway repo layout, so whether
this checkout has a backend/.venv cannot decide the outcome.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "backend-python.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None or os.name == "nt", reason="exercises the POSIX launch path")


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _path_without_uv() -> list[str]:
    """Host PATH entries, minus any that would supply a real uv."""
    return [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry and not (Path(entry) / "uv").exists()]


@pytest.fixture
def layout(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "backend").mkdir()
    shutil.copy2(HELPER, repo / "scripts" / "backend-python.sh")
    target = repo / "scripts" / "probe.py"
    target.write_text("import os, sys, yaml\nprint('ran', os.getcwd(), *sys.argv[1:])\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # A python3 that has PyYAML: the test interpreter itself.
    _executable(bin_dir / "python3", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    return repo, bin_dir


def _run(repo: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": os.pathsep.join([str(bin_dir), *_path_without_uv()])}
    return subprocess.run([BASH, str(repo / "scripts" / "backend-python.sh"), *args], capture_output=True, text=True, env=env, cwd=str(repo), timeout=60)


def _fake_uv(bin_dir: Path) -> None:
    _executable(bin_dir / "uv", '#!/bin/sh\necho "uv $* in $(pwd)"\n')


def test_uses_uv_inside_backend_when_the_venv_exists(layout):
    repo, bin_dir = layout
    _fake_uv(bin_dir)
    (repo / "backend" / ".venv").mkdir()

    result = _run(repo, bin_dir, "scripts/probe.py", "--flag")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"uv run python {repo}/scripts/probe.py --flag in {repo}/backend"


def test_uv_without_a_venv_does_not_build_one(layout):
    # `uv run` would first sync the whole backend just to edit config.yaml.
    repo, bin_dir = layout
    _fake_uv(bin_dir)

    result = _run(repo, bin_dir, "scripts/probe.py", "--flag")

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"ran {repo} --flag")
    assert not (repo / "backend" / ".venv").exists()


def test_no_uv_falls_back_to_the_host_python(layout):
    repo, bin_dir = layout
    (repo / "backend" / ".venv").mkdir()

    result = _run(repo, bin_dir, "scripts/probe.py", "a b")

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"ran {repo} a b")


def test_a_python_without_pyyaml_is_refused_with_the_fix(layout, tmp_path):
    repo, bin_dir = layout
    _executable(bin_dir / "python3", '#!/bin/sh\n[ "$1" = -c ] && exit 1\nexit 0\n')
    _executable(bin_dir / "python", '#!/bin/sh\n[ "$1" = -c ] && exit 1\nexit 0\n')

    result = _run(repo, bin_dir, "scripts/probe.py")

    assert result.returncode != 0
    assert "PyYAML" in result.stderr
    assert "make install" in result.stderr


def test_the_make_targets_route_through_the_helper():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("sandbox-enable", "sandbox-disable"):
        recipe = makefile.split(f"\n{target}:\n", 1)[1].split("\n\n", 1)[0]
        assert "$(RUN_SHELL_SCRIPT) ./scripts/backend-python.sh" in recipe, recipe
        assert "uv run" not in recipe
    wrapper = (REPO_ROOT / "scripts" / "config-upgrade.sh").read_text(encoding="utf-8")
    assert "backend-python.sh" in wrapper
    assert "uv run" not in wrapper
