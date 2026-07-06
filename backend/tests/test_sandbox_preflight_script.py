"""Tests for scripts/sandbox-preflight.sh (AIO sandbox preflight for make dev).

Follows the pattern of test_docker_sandbox_mode_detection.py: the script is
source-guarded, so its functions are sourced into a bash subprocess and
exercised directly. Docker itself is faked with shell functions (bash resolves
functions before PATH lookups), keeping the tests hermetic.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sandbox-preflight.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)

if BASH_EXECUTABLE is None:
    pytestmark = pytest.mark.skip(reason="bash is required for sandbox-preflight.sh tests")

LOCAL_CONFIG = """
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
""".strip()

AIO_CONFIG = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
""".strip()

AIO_CONFIG_WITH_IMAGE = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  image: my.registry/sandbox:1.2.3   # pinned
""".strip()

PROVISIONER_CONFIG = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  provisioner_url: http://provisioner:8002
""".strip()


def _run_sourced(config_content: str | None, snippet: str) -> subprocess.CompletedProcess:
    """Source the script, write an optional config, and run a bash snippet.

    The snippet sees the config path as $CONFIG.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        if config_content is not None:
            config_path.write_text(config_content, encoding="utf-8")

        command = f"source '{SCRIPT_PATH}' && CONFIG='{config_path}' && {snippet}"
        return subprocess.run(
            [BASH_EXECUTABLE, "-c", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )


# ── detect_sandbox_mode_from_config ──────────────────────────────────────────


class TestDetectSandboxMode:
    def test_missing_config_defaults_to_local(self):
        result = _run_sourced(None, 'detect_sandbox_mode_from_config "$CONFIG"')
        assert result.stdout.strip() == "local"

    def test_local_provider(self):
        result = _run_sourced(LOCAL_CONFIG, 'detect_sandbox_mode_from_config "$CONFIG"')
        assert result.stdout.strip() == "local"

    def test_aio_provider(self):
        result = _run_sourced(AIO_CONFIG, 'detect_sandbox_mode_from_config "$CONFIG"')
        assert result.stdout.strip() == "aio"

    def test_provisioner_mode(self):
        result = _run_sourced(PROVISIONER_CONFIG, 'detect_sandbox_mode_from_config "$CONFIG"')
        assert result.stdout.strip() == "provisioner"


# ── sandbox_image_from_config ────────────────────────────────────────────────


class TestSandboxImage:
    def test_configured_image_with_trailing_comment(self):
        result = _run_sourced(AIO_CONFIG_WITH_IMAGE, 'sandbox_image_from_config "$CONFIG"')
        assert result.stdout.strip() == "my.registry/sandbox:1.2.3"

    def test_default_image_when_not_configured(self):
        result = _run_sourced(AIO_CONFIG, 'sandbox_image_from_config "$CONFIG"')
        assert result.stdout.strip() == ("enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest")


# ── aio_sandbox_preflight ────────────────────────────────────────────────────

# Fake docker as a bash function: functions shadow PATH executables, so the
# preflight exercises its logic without a real daemon. uname is pinned to
# Linux so the Apple Container branch never triggers on macOS dev machines.
_FAKE_ENV = "uname() { echo Linux; }; "


class TestAioSandboxPreflight:
    def test_local_mode_is_silent_success(self):
        result = _run_sourced(LOCAL_CONFIG, 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_provisioner_mode_skips_docker_checks(self):
        result = _run_sourced(PROVISIONER_CONFIG, 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 0
        assert "provisioner" in result.stdout

    def test_daemon_unreachable_fails_with_fallback_hint(self):
        fake = 'docker() { if [ "$1" = "info" ]; then return 1; fi; return 0; }; '
        result = _run_sourced(AIO_CONFIG, _FAKE_ENV + fake + 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 1
        assert "daemon is not reachable" in result.stderr
        assert "LocalSandboxProvider" in result.stderr

    def test_image_present_passes(self):
        fake = "docker() { return 0; }; "
        result = _run_sourced(AIO_CONFIG_WITH_IMAGE, _FAKE_ENV + fake + 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 0
        assert "my.registry/sandbox:1.2.3" in result.stdout
        assert "created per conversation" in result.stdout

    def test_missing_image_is_pulled(self):
        fake = 'docker() { if [ "$1" = "image" ]; then return 1; fi; if [ "$1" = "pull" ]; then echo "PULLED $2"; fi; return 0; }; '
        result = _run_sourced(AIO_CONFIG_WITH_IMAGE, _FAKE_ENV + fake + 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 0
        assert "PULLED my.registry/sandbox:1.2.3" in result.stdout

    def test_pull_failure_fails_with_setup_sandbox_hint(self):
        fake = 'docker() { if [ "$1" = "info" ]; then return 0; fi; return 1; }; '
        result = _run_sourced(AIO_CONFIG, _FAKE_ENV + fake + 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 1
        assert "failed to pull" in result.stderr
        assert "make setup-sandbox" in result.stderr
        assert "LocalSandboxProvider" in result.stderr


# ── External base_url mode ───────────────────────────────────────────────────

AIO_EXTERNAL_CONFIG = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  base_url: http://localhost:8091
  request_timeout: 120.0
""".strip()


class TestSandboxBaseUrl:
    def test_base_url_parsed_with_trailing_comment(self):
        config = "sandbox:\n  use: deerflow.community.aio_sandbox:AioSandboxProvider\n  base_url: http://localhost:8091  # external\n"
        result = _run_sourced(config, 'sandbox_base_url_from_config "$CONFIG"')
        assert result.stdout.strip() == "http://localhost:8091"

    def test_base_url_empty_when_unset(self):
        result = _run_sourced(AIO_CONFIG, 'sandbox_base_url_from_config "$CONFIG"')
        assert result.stdout.strip() == ""


class TestExternalPreflight:
    # Fake curl (health probe) and docker (compose) as shell functions.
    def test_already_reachable_is_success_without_compose(self):
        # curl succeeds immediately → no compose call.
        fake = "curl() { return 0; }; docker() { echo 'DOCKER SHOULD NOT RUN'; return 1; }; "
        result = _run_sourced(AIO_EXTERNAL_CONFIG, _FAKE_ENV + fake + 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 0
        assert "already reachable" in result.stdout
        assert "DOCKER SHOULD NOT RUN" not in result.stdout

    def test_unreachable_then_compose_up_then_healthy(self):
        # curl fails first (health check before up), then succeeds after up.
        fake = (
            "STATE=/tmp/pf_state_$$; rm -f $STATE; "
            'curl() { if [ -f "$STATE" ]; then return 0; else return 1; fi; }; '
            'docker() { if [ "$1" = "compose" ] && [ "$2" = "version" ]; then return 0; fi; '
            'if [ "$1" = "compose" ]; then touch "$STATE"; echo "COMPOSE UP"; return 0; fi; return 0; }; '
        )
        result = _run_sourced(AIO_EXTERNAL_CONFIG, _FAKE_ENV + fake + 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 0
        assert "COMPOSE UP" in result.stdout
        assert "is ready" in result.stdout

    def test_compose_up_but_never_ready_fails_with_hints(self):
        # curl always fails; compose up "succeeds" but health never passes.
        fake = 'curl() { return 1; }; docker() { if [ "$1" = "compose" ] && [ "$2" = "version" ]; then return 0; fi; return 0; }; '
        # Shorten the loop by faking sleep to a no-op so the 60s poll returns fast.
        fake = "sleep() { return 0; }; " + fake
        result = _run_sourced(AIO_EXTERNAL_CONFIG, _FAKE_ENV + fake + 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 1
        assert "did not become ready" in result.stderr
        assert "make sandbox-logs" in result.stderr
        assert "make sandbox-disable" in result.stderr

    def test_no_compose_available_fails_with_hints(self):
        # curl fails, docker compose version fails, docker-compose absent.
        fake = "curl() { return 1; }; docker() { return 1; }; command() { return 1; }; "
        result = _run_sourced(AIO_EXTERNAL_CONFIG, _FAKE_ENV + fake + 'aio_sandbox_preflight "$CONFIG"')
        assert result.returncode == 1
        assert "make sandbox-disable" in result.stderr
