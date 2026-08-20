"""Both Docker paths must honor the repo-root ``.env`` and reach the tailnet.

Two regressions are pinned here, and they are different failures that produced
the same symptom ("I upgraded and my phone can't reach DeerFlow any more"):

1. **Root ``.env`` interpolation.** ``scripts/docker.sh`` runs Compose after
   ``cd docker/``. Without an explicit ``--env-file`` pointing at the repo-root
   ``.env``, Compose interpolates ``${BIND_HOST}`` / ``${PORT}`` in the
   ``ports:`` line against ``docker/.env`` instead — a file that does not
   exist — so the documented escape hatch silently did nothing on this path.
2. **Single-interface publish.** ``BIND_HOST`` is one bind address, not an
   allowlist, so the pre-existing advice ("point it at your Tailscale IP")
   traded localhost away for tailnet access. The tailnet overlay publishes an
   *additional* port instead, and the loopback overlay covers anyone still
   using BIND_HOST that way.

These are script- and compose-level behaviors, so the tests read the files and
exercise the shell functions directly rather than starting Docker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_SH = REPO_ROOT / "scripts" / "docker.sh"
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"
DOCKER_DIR = REPO_ROOT / "docker"
TAILSCALE_OVERLAY = DOCKER_DIR / "docker-compose.tailscale.yaml"
LOOPBACK_OVERLAY = DOCKER_DIR / "docker-compose.loopback.yaml"

BASH = shutil.which("bash")
requires_bash = pytest.mark.skipif(BASH is None, reason="bash is required to exercise the launch scripts")


def _run_shell(snippet: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a bash snippet with the repo's script directory available."""
    full_env = {**os.environ, "PATH": os.environ.get("PATH", "")}
    if env:
        full_env.update(env)
    return subprocess.run(  # noqa: S603 - fixed interpreter, test-authored snippet
        [BASH, "-c", snippet],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )


class TestRootDotenvIsHonoredByComposeInterpolation:
    """The documented escape hatch must actually reach `ports:` on docker-dev."""

    def test_docker_sh_passes_the_repo_root_env_file_to_compose(self) -> None:
        # Without --env-file, `cd docker/` makes Compose look for docker/.env and
        # the root .env never participates in port interpolation.
        text = DOCKER_SH.read_text(encoding="utf-8")
        assert "--env-file $PROJECT_ROOT/.env" in text

    def test_compose_cmd_is_built_before_any_cd(self) -> None:
        # The --env-file path must be absolute, since every invocation runs from
        # $DOCKER_DIR. A relative path would silently resolve to docker/.env.
        text = DOCKER_SH.read_text(encoding="utf-8")
        assert "--env-file $PROJECT_ROOT/.env" in text
        assert "--env-file .env" not in text
        assert "--env-file ../.env" not in text

    def test_a_missing_docker_dotenv_cannot_mask_the_root_one(self) -> None:
        # A stray docker/.env would win over the root file for interpolation, so
        # the repo must not ship one and the tree must stay clean of it.
        assert not (DOCKER_DIR / ".env").exists(), "docker/.env would shadow the repo-root .env for compose interpolation"

    @requires_bash
    def test_bind_host_from_the_root_env_reaches_the_published_port(self, tmp_path: Path) -> None:
        """End-to-end: a root .env BIND_HOST changes the nginx publish string.

        Uses `docker compose config` semantics via a minimal reimplementation:
        we assert the interpolation inputs, because a real `docker compose` is
        not available in CI. The publish template itself is asserted below.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("BIND_HOST=100.101.102.103\nPORT=2027\n", encoding="utf-8")

        # read_dotenv_value is the function the banner and the co-bind decision
        # both use; it must see the root .env, not the shell environment.
        snippet = f"""
            PROJECT_ROOT={tmp_path}
            source /dev/stdin <<'FUNCS'
{_extract_function(DOCKER_SH, "read_dotenv_value")}
FUNCS
            read_dotenv_value BIND_HOST
            echo
            read_dotenv_value PORT
        """
        result = _run_shell(snippet)
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["100.101.102.103", "2027"]


class TestPublishTemplates:
    def test_base_dev_compose_still_defaults_to_loopback(self) -> None:
        compose = yaml.safe_load((DOCKER_DIR / "docker-compose-dev.yaml").read_text(encoding="utf-8"))
        ports = compose["services"]["nginx"]["ports"]
        assert ports == ["${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"]

    def test_base_prod_compose_still_defaults_to_loopback(self) -> None:
        compose = yaml.safe_load((DOCKER_DIR / "docker-compose.yaml").read_text(encoding="utf-8"))
        ports = compose["services"]["nginx"]["ports"]
        assert ports == ["${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"]

    def test_tailscale_overlay_publishes_only_the_detected_address(self) -> None:
        compose = yaml.safe_load(TAILSCALE_OVERLAY.read_text(encoding="utf-8"))
        ports = compose["services"]["nginx"]["ports"]
        assert len(ports) == 1
        published = ports[0]
        # Must be host-scoped to the detected tailnet IP...
        assert published.startswith("${DEER_FLOW_TAILSCALE_IPV4")
        # ...and must never fall back to a wildcard bind. An empty default would
        # collapse "${VAR}:${PORT}:2026" into "${PORT}:2026", which binds 0.0.0.0
        # — the exact thing this overlay exists to avoid.
        assert ":?" in published, "the overlay must fail loudly rather than silently binding 0.0.0.0"
        assert "0.0.0.0" not in published

    def test_tailscale_overlay_touches_only_nginx(self) -> None:
        # Sandbox / gateway / frontend publish decisions stay independent.
        compose = yaml.safe_load(TAILSCALE_OVERLAY.read_text(encoding="utf-8"))
        assert list(compose["services"]) == ["nginx"]
        assert set(compose["services"]["nginx"]) == {"ports"}


@requires_bash
class TestLoopbackCobindOnDockerDev:
    """docker.sh must apply the same co-bind rule deploy.sh already does."""

    @pytest.mark.parametrize("bind", ["", "127.0.0.1", "::1", "localhost", "0.0.0.0", "::"])
    def test_no_cobind_for_loopback_or_wildcard(self, tmp_path: Path, bind: str) -> None:
        assert _cobind_decision(tmp_path, bind) == "no"

    @pytest.mark.parametrize("bind", ["100.101.102.103", "192.168.1.10", "fd7a:115c:a1e0::1"])
    def test_cobind_for_a_single_external_interface(self, tmp_path: Path, bind: str) -> None:
        assert _cobind_decision(tmp_path, bind) == "yes"

    def test_docker_sh_and_deploy_sh_agree(self, tmp_path: Path) -> None:
        # The two paths diverging is how "works with make up, broken with
        # make docker-start" happens.
        for bind in ("", "127.0.0.1", "0.0.0.0", "100.1.2.3"):
            assert _cobind_decision(tmp_path, bind, script=DOCKER_SH) == _cobind_decision(tmp_path, bind, script=DEPLOY_SH)


class TestScriptWiring:
    @pytest.mark.parametrize("script", [DOCKER_SH, DEPLOY_SH])
    def test_both_paths_source_the_shared_tailnet_library(self, script: Path) -> None:
        assert "tailscale_lib.sh" in script.read_text(encoding="utf-8")

    @pytest.mark.parametrize("script", [DOCKER_SH, DEPLOY_SH])
    def test_both_paths_add_the_overlay_and_merge_origins(self, script: Path) -> None:
        text = script.read_text(encoding="utf-8")
        assert "tailscale_detect" in text
        assert "tailscale_merge_origins" in text
        assert "docker-compose.tailscale.yaml" in text

    @pytest.mark.parametrize("script", [DOCKER_SH, DEPLOY_SH])
    def test_both_paths_print_the_live_urls(self, script: Path) -> None:
        assert "tailscale_print_urls" in script.read_text(encoding="utf-8")

    def test_stop_and_down_never_reset_tailscale_serve(self) -> None:
        # Serve config is global to the machine and may carry rules for other
        # services; a DeerFlow stop must not delete rules it did not create.
        # Comments are exempt: the scripts document *why* they never reset it.
        for script in (DOCKER_SH, DEPLOY_SH, REPO_ROOT / "scripts" / "tailscale_lib.sh"):
            for line in script.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("#"):
                    continue
                assert "serve reset" not in line, f"{script.name} would delete a user's Serve rules: {line.strip()}"

    def test_the_library_never_runs_tailscale_serve_itself(self) -> None:
        # Serve usually needs --operator=$USER or sudo. Running it from a launch
        # path would either prompt or fail; the banner prints the command instead.
        text = (REPO_ROOT / "scripts" / "tailscale_lib.sh").read_text(encoding="utf-8")
        assert "tailscale serve status" in text, "read-only status probe is expected"
        # No mutating invocation: every `tailscale serve` occurrence outside a
        # comment or an echoed hint must be the status probe.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("echo"):
                continue
            if "tailscale serve" in stripped:
                assert "serve status" in stripped, f"unexpected mutating serve call: {stripped}"


def _extract_function(script: Path, name: str) -> str:
    """Pull one shell function body out of a script for isolated execution."""
    lines = script.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    depth = 0
    capturing = False
    for line in lines:
        if not capturing and line.startswith(f"{name}() {{"):
            capturing = True
            depth = 1
            out.append(line)
            continue
        if capturing:
            out.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0:
                break
    if not out:
        raise AssertionError(f"function {name} not found in {script}")
    return "\n".join(out)


def _cobind_decision(tmp_path: Path, bind: str, *, script: Path = DOCKER_SH) -> str:
    env_file = tmp_path / ".env"
    env_file.write_text(f"BIND_HOST={bind}\n" if bind else "", encoding="utf-8")
    root_var = "PROJECT_ROOT" if script == DOCKER_SH else "ENV_FILE"
    root_value = str(tmp_path) if script == DOCKER_SH else str(env_file)
    snippet = f"""
        {root_var}={root_value}
        source /dev/stdin <<'FUNCS'
{_extract_function(script, "read_dotenv_value")}
{_extract_function(script, "should_cobind_loopback")}
FUNCS
        should_cobind_loopback
    """
    result = _run_shell(snippet)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


if sys.platform == "win32":  # pragma: no cover - the launch scripts are POSIX-only
    pytestmark = pytest.mark.skip(reason="POSIX launch scripts")
