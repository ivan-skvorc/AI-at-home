"""Regression coverage for the fork's passwordless-by-default launch behavior.

This fork makes the local stack reachable with no username/password by defaulting
``DEER_FLOW_AUTH_DISABLED=1`` in ``scripts/serve.sh`` (exported before the gateway
and frontend are launched, so both inherit it). The default is opt-out: an explicit
``DEER_FLOW_AUTH_DISABLED=0`` in ``.env`` restores the normal login, and any explicit
value is preserved. These tests extract the ``apply_default_auth_mode`` shell function
and exercise it in isolation — a large upstream merge that silently dropped the hook
would otherwise pass every Python unit test while quietly re-enabling the login wall.
"""

from __future__ import annotations

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


def _run_apply_default_auth_mode(preset: str | None) -> str:
    """Run apply_default_auth_mode and return the resulting DEER_FLOW_AUTH_DISABLED.

    ``preset`` sets the variable before the function runs (``None`` leaves it unset,
    matching a fresh shell with no ``.env`` entry).
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to exercise serve.sh helpers")

    function = _extract_shell_function("apply_default_auth_mode")
    preset_line = "" if preset is None else f"export DEER_FLOW_AUTH_DISABLED={preset}\n"
    script = f"""
set -e
{preset_line}{function}

apply_default_auth_mode
printf '%s' "${{DEER_FLOW_AUTH_DISABLED-<unset>}}"
"""
    result = subprocess.run([bash, "-c", script], check=True, capture_output=True, text=True)
    return result.stdout


def test_defaults_to_disabled_when_unset() -> None:
    # Fresh shell, no .env entry → the fork turns auth off by default.
    assert _run_apply_default_auth_mode(None) == "1"


def test_explicit_opt_out_is_preserved() -> None:
    # A user who wants the login wall back sets 0; the default must not clobber it.
    assert _run_apply_default_auth_mode("0") == "0"


def test_explicit_enabled_value_is_preserved() -> None:
    # An explicit 1 is likewise left untouched (idempotent).
    assert _run_apply_default_auth_mode("1") == "1"
