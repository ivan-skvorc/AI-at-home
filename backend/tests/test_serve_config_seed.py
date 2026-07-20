"""Regression coverage for first-run config seeding in scripts/serve.sh.

`make dev` / `make start` used to abort with "run make config first" when no
config.yaml existed, so a fresh checkout could not start without a manual step.
`serve.sh::seed_missing_config` now seeds config.yaml (plus the companion config
files) from the committed example templates on first run — matching the Docker
launch paths (scripts/deploy.sh, scripts/docker.sh). These tests extract the
shell function and exercise it in an isolated temp directory.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"


def _extract_shell_function(name: str) -> str:
    text = SERVE_SH.read_text(encoding="utf-8")
    marker = f"{name}() {{"
    start = text.index(marker)
    depth = 0
    chunks: list[str] = []

    for line in text[start:].splitlines(keepends=True):
        chunks.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            return "".join(chunks)

    raise AssertionError(f"Could not extract shell function {name}")


def _run_seed(repo_root: Path, *, config_path_env: str = "") -> int:
    """Run seed_missing_config with REPO_ROOT pointed at ``repo_root``.

    Returns the function's exit code. ``config_path_env`` sets
    ``DEER_FLOW_CONFIG_PATH`` for the run (empty means unset).
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to exercise serve.sh helpers")

    function = _extract_shell_function("seed_missing_config")
    script = f"""
set -e
REPO_ROOT={shlex.quote(str(repo_root))}
DEER_FLOW_CONFIG_PATH={shlex.quote(config_path_env)}

{function}

seed_missing_config
"""
    result = subprocess.run([bash, "-c", script], check=False, capture_output=True, text=True)
    return result.returncode


def _make_repo(tmp_path: Path, *, with_example: bool = True) -> Path:
    repo = tmp_path / "repo"
    (repo / "frontend").mkdir(parents=True)
    if with_example:
        (repo / "config.example.yaml").write_text("config_version: 26\nlog_level: info\n", encoding="utf-8")
        (repo / "extensions_config.example.json").write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")
        (repo / ".env.example").write_text("# ANTHROPIC_API_KEY=your-key\n", encoding="utf-8")
        (repo / "frontend" / ".env.example").write_text("# NEXT_PUBLIC_BACKEND_BASE_URL=\n", encoding="utf-8")
    return repo


def test_seeds_config_from_example_on_first_run(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    rc = _run_seed(repo)

    assert rc == 0
    assert (repo / "config.yaml").exists()
    assert (repo / "config.yaml").read_text() == (repo / "config.example.yaml").read_text()


def test_seeds_companion_config_files(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    rc = _run_seed(repo)

    assert rc == 0
    assert (repo / "extensions_config.json").exists()
    assert (repo / ".env").exists()
    assert (repo / "frontend" / ".env").exists()


def test_existing_config_is_not_overwritten(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "config.yaml").write_text("config_version: 99  # user edits\n", encoding="utf-8")

    rc = _run_seed(repo)

    assert rc == 0
    assert (repo / "config.yaml").read_text() == "config_version: 99  # user edits\n"
    # Companion files must not be seeded when config already exists.
    assert not (repo / ".env").exists()


def test_existing_backend_config_prevents_seeding(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "backend").mkdir()
    (repo / "backend" / "config.yaml").write_text("config_version: 5\n", encoding="utf-8")

    rc = _run_seed(repo)

    assert rc == 0
    assert not (repo / "config.yaml").exists()


def test_explicit_config_path_prevents_seeding(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    external = tmp_path / "elsewhere" / "config.yaml"
    external.parent.mkdir(parents=True)
    external.write_text("config_version: 7\n", encoding="utf-8")

    rc = _run_seed(repo, config_path_env=str(external))

    assert rc == 0
    assert not (repo / "config.yaml").exists()


def test_missing_example_template_fails_cleanly(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, with_example=False)

    rc = _run_seed(repo)

    assert rc == 1
    assert not (repo / "config.yaml").exists()
