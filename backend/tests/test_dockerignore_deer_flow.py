"""Regression test: the Docker build context must exclude ``.deer-flow/``.

The Docker images build from a repo-root context (``docker/docker-compose.yaml``
sets ``context: ../`` for both the gateway and frontend, and ``backend/Dockerfile``
does ``COPY backend ./backend``). DeerFlow writes per-user runtime state under
``.deer-flow/`` (integrations, uploads, backups) — and the DooD sandbox writes
into the host-mounted ``backend/.deer-flow/`` **as root**. If that tree is not
ignored, two things break:

* BuildKit's context sender tries to read every non-ignored file to assemble the
  context and dies on the root-owned ones with
  ``error from sender: open .../backend/.deer-flow/.../lark-cli: permission
  denied``, failing the whole ``make docker-start``; and
* even when readable, the runtime user data (and any credentials in it) would be
  baked into the image.

This test pins the ``.deer-flow/`` exclusions in the repo-root ``.dockerignore``
so a future edit can't silently drop them.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# Patterns that keep both the repo-root `.deer-flow/` and nested copies such as
# `backend/.deer-flow/` out of the build context.
REQUIRED_PATTERNS = {".deer-flow/", "**/.deer-flow/"}


def _ignore_patterns() -> set[str]:
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return {stripped for line in lines if (stripped := line.strip()) and not stripped.startswith("#")}


def test_dockerignore_exists() -> None:
    assert DOCKERIGNORE.is_file(), f"missing {DOCKERIGNORE}"


def test_dockerignore_excludes_deer_flow_runtime_state() -> None:
    patterns = _ignore_patterns()
    missing = REQUIRED_PATTERNS - patterns
    assert not missing, f"repo-root .dockerignore must exclude DeerFlow runtime state from the Docker build context; missing pattern(s): {sorted(missing)}"
