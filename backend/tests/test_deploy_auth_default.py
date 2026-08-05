"""Regression coverage for passwordless-by-default on the Docker prod path.

The local launchers (``scripts/serve.sh``) already default
``DEER_FLOW_AUTH_DISABLED=1`` so ``make dev`` / ``make start`` are reachable with
no login wall. This fork extends that to ``make up`` (``scripts/deploy.sh``,
Docker prod) so a git-pull-then-``make up`` on the home lab is not silently
gated by a login wall the operator did not expect.

``deploy.sh`` does not source ``.env`` into the shell (compose reads it via
``--env-file``), so ``apply_default_auth_mode`` must consult ``.env`` through
``read_dotenv_value`` to honor an explicit ``DEER_FLOW_AUTH_DISABLED=0``
opt-out. These tests extract both shell functions and exercise the decision in
isolation, so a large upstream merge that dropped the hook or reordered the
precedence would fail here instead of quietly re-enabling (or force-disabling)
the login wall in production Docker.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yaml"


def _extract_shell_function(name: str) -> str:
    text = DEPLOY_SH.read_text(encoding="utf-8")
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


def _run_apply_default_auth_mode(
    tmp_path: Path,
    *,
    env_line: str | None,
    shell_preset: str | None,
) -> str:
    """Resolve DEER_FLOW_AUTH_DISABLED the way ``deploy.sh`` would.

    ``env_line`` is written verbatim into a temp ``.env`` (``None`` = no entry).
    ``shell_preset`` exports the variable before the functions run (``None`` =
    unset), modelling a value already present in the process environment.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to exercise deploy.sh helpers")

    env_file = tmp_path / ".env"
    env_file.write_text("" if env_line is None else env_line + "\n", encoding="utf-8")

    read_fn = _extract_shell_function("read_dotenv_value")
    apply_fn = _extract_shell_function("apply_default_auth_mode")
    preset_line = "" if shell_preset is None else f"export DEER_FLOW_AUTH_DISABLED={shell_preset}\n"

    script = f"""
set -e
ENV_FILE="{env_file}"
{preset_line}{read_fn}
{apply_fn}

apply_default_auth_mode
printf '%s' "${{DEER_FLOW_AUTH_DISABLED-<unset>}}"
"""
    result = subprocess.run([bash, "-c", script], check=True, capture_output=True, text=True)
    return result.stdout


def test_defaults_to_disabled_when_absent_everywhere(tmp_path: Path) -> None:
    # No .env entry, nothing in the shell → the fork turns auth off by default.
    assert _run_apply_default_auth_mode(tmp_path, env_line=None, shell_preset=None) == "1"


def test_explicit_opt_out_in_dotenv_is_preserved(tmp_path: Path) -> None:
    # A user who wants the login wall back sets 0 in .env; the default must honor it.
    assert _run_apply_default_auth_mode(tmp_path, env_line="DEER_FLOW_AUTH_DISABLED=0", shell_preset=None) == "0"


def test_explicit_enable_in_dotenv_is_preserved(tmp_path: Path) -> None:
    assert _run_apply_default_auth_mode(tmp_path, env_line="DEER_FLOW_AUTH_DISABLED=1", shell_preset=None) == "1"


def test_dotenv_export_prefix_is_parsed(tmp_path: Path) -> None:
    # `export DEER_FLOW_AUTH_DISABLED=0` in .env must also be honored.
    assert _run_apply_default_auth_mode(tmp_path, env_line="export DEER_FLOW_AUTH_DISABLED=0", shell_preset=None) == "0"


def test_exported_shell_var_wins_over_dotenv(tmp_path: Path) -> None:
    # read_dotenv_value gives an already-exported shell var precedence, matching
    # docker compose interpolation precedence.
    assert _run_apply_default_auth_mode(tmp_path, env_line="DEER_FLOW_AUTH_DISABLED=1", shell_preset="0") == "0"


def _service_env(service_name: str) -> dict[str, str]:
    """Return the ``key -> raw value`` map for one compose service's environment."""
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    service = compose["services"][service_name]
    env: dict[str, str] = {}
    for entry in service.get("environment", []):
        key, _, value = str(entry).partition("=")
        env[key] = value
    return env


class TestComposeForwardsAuthEnv:
    """Both containers must see the auth flag and the production self-disable markers.

    The frontend's ``env_file`` is ``frontend/.env`` (not the root ``.env``), so
    the SSR auth check only sees these three keys if the compose ``environment``
    block forwards them. The gateway needs the ``environment`` interpolation too,
    so ``deploy.sh``'s exported shell default reaches it even when the key is
    absent from the root ``.env``.
    """

    @pytest.mark.parametrize("service", ["gateway", "frontend"])
    @pytest.mark.parametrize("key", ["DEER_FLOW_AUTH_DISABLED", "DEER_FLOW_ENV", "ENVIRONMENT"])
    def test_service_forwards_key(self, service: str, key: str) -> None:
        assert key in _service_env(service), f"{service} must forward {key} to the container"

    @pytest.mark.parametrize("service", ["gateway", "frontend"])
    def test_auth_flag_defaults_to_off_in_compose(self, service: str) -> None:
        # Compose's own default is auth-ON (safe if compose is invoked directly);
        # deploy.sh is what exports the passwordless home-lab default of 1.
        assert _service_env(service)["DEER_FLOW_AUTH_DISABLED"] == "${DEER_FLOW_AUTH_DISABLED:-0}"
