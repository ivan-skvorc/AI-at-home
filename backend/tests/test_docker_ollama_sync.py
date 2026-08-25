"""Regression coverage: the Docker launch paths run the Ollama model sync.

Both Docker entry points must reconcile the host's installed Ollama models into
``config.yaml`` *before* starting the containers, so an already-running host
Ollama auto-populates the config without anyone installing Ollama or running the
sync by hand:

  - ``scripts/deploy.sh`` (Docker prod, ``make up``)
  - ``scripts/docker.sh``  (Docker dev,  ``make docker-start``)

These tests stub out ``scripts/sync-ollama-models.py`` with a recorder and fake
the ``docker`` CLI, then assert each launch script invoked the sync with
``--container`` (so the written ``base_url`` targets ``host.docker.internal``,
reachable from the gateway container) and pointed it at the repo ``config.yaml``.
The sync script's own behavior is covered by ``test_sync_ollama_models.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# A local-sandbox config with no SearXNG provider: keeps detect_sandbox_mode on
# the no-Docker-socket "local" path and lets detect_searxng short-circuit to
# "skip" without probing ports or shelling out to the fake docker.
_MINIMAL_CONFIG = "sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n"

# Stub sync-ollama-models.py: record argv, touch nothing else, exit clean.
_SYNC_STUB = "#!/usr/bin/env python3\nimport os, sys\nwith open(os.environ['CAPTURE_OLLAMA_ARGS'], 'w', encoding='utf-8') as fh:\n    fh.write('\\n'.join(sys.argv[1:]))\n"

# Fake docker CLI: accept any subcommand (compose ... up ...) and succeed.
_FAKE_DOCKER = "#!/usr/bin/env sh\nexit 0\n"


def _make_worktree(tmp_path: Path) -> Path:
    """A minimal repo copy with real scripts/ + docker/ and a stubbed sync script."""
    worktree = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", worktree / "scripts")
    shutil.copytree(REPO_ROOT / "docker", worktree / "docker")
    (worktree / "backend").mkdir()
    (worktree / "config.yaml").write_text(_MINIMAL_CONFIG, encoding="utf-8")
    (worktree / "extensions_config.json").write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")
    # docker.sh's ensure_env_files copies .env from .env.example and exits 1 when
    # neither exists (Compose env_file entries fail closed on Windows). The real
    # repo always ships the example, so the worktree must too.
    (worktree / ".env.example").write_text("", encoding="utf-8")
    (worktree / "frontend").mkdir()
    (worktree / "frontend" / ".env.example").write_text("", encoding="utf-8")

    sync_stub = worktree / "scripts" / "sync-ollama-models.py"
    sync_stub.write_text(_SYNC_STUB, encoding="utf-8")
    sync_stub.chmod(0o755)
    return worktree


def _env_with_fake_docker(tmp_path: Path, capture: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(_FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["CAPTURE_OLLAMA_ARGS"] = str(capture)
    # Keep the launch scripts on their default (local) sandbox path.
    env.pop("DEER_FLOW_DOCKER_SOCKET", None)
    env.pop("DEER_FLOW_SEARXNG_BASE_URL", None)
    return env


def test_deploy_start_runs_ollama_sync_container(tmp_path):
    """`make up` (deploy.sh start) reconciles host Ollama models into config.yaml."""
    worktree = _make_worktree(tmp_path)
    capture = tmp_path / "ollama_args.txt"
    env = _env_with_fake_docker(tmp_path, capture)

    subprocess.run(
        ["bash", str(worktree / "scripts" / "deploy.sh"), "start"],
        cwd=worktree,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert capture.exists(), "deploy.sh did not invoke scripts/sync-ollama-models.py"
    args = capture.read_text(encoding="utf-8").splitlines()
    assert "--container" in args
    assert "--config" in args
    assert str(worktree / "config.yaml") in args


def test_docker_start_runs_ollama_sync_container(tmp_path):
    """`make docker-start` (docker.sh start) reconciles host Ollama models into config.yaml."""
    worktree = _make_worktree(tmp_path)
    capture = tmp_path / "ollama_args.txt"
    env = _env_with_fake_docker(tmp_path, capture)

    subprocess.run(
        ["bash", str(worktree / "scripts" / "docker.sh"), "start"],
        cwd=worktree,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert capture.exists(), "docker.sh did not invoke scripts/sync-ollama-models.py"
    args = capture.read_text(encoding="utf-8").splitlines()
    assert "--container" in args
    assert "--config" in args
    assert str(worktree / "config.yaml") in args
