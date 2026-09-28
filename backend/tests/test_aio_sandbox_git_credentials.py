"""Tests for in-container GitHub credential setup (aio_sandbox.git_credentials).

Covers:
- the credential helper script never embeds a token (it reads the container
  env at git-invocation time),
- setup never writes/executes/logs the token value,
- the helper is installed through the shell into the sandbox user's home, not
  through the file API into a root-owned directory (the pinned 1.11.0 image
  refuses that write, so git silently lost GITHUB_TOKEN),
- the install command really works: run under a local sh, git answers a
  github.com credential request from GITHUB_TOKEN,
- a refused file-API write surfaces as an OSError naming the path, not as the
  SDK's "validation error for ResponseFileWriteResult",
- setup failure paths degrade gracefully (no raise, sandbox still usable),
- provider env resolution injects GITHUB_TOKEN from the host environment,
- sandbox creation succeeds even when session init fails.
"""

from __future__ import annotations

import base64
import importlib
import os
import re
import shutil
import subprocess
import threading
from unittest.mock import MagicMock

import httpx
import pytest
from agent_sandbox import Sandbox as AioSandboxClient

from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
from deerflow.community.aio_sandbox.git_credentials import (
    CREDENTIAL_HELPER_HOME_PATH,
    CREDENTIAL_HELPER_SCRIPT,
    TOKEN_ENV_VAR,
    build_setup_command,
    setup_github_credentials,
)
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

SENTINEL_TOKEN = "github_pat_SENTINEL_NEVER_LEAK_1234567890"


def _make_sandbox(exec_output: str = "DEER_FLOW_GIT_CREDENTIALS_OK\n", write_error: Exception | None = None) -> AioSandbox:
    """Real AioSandbox with recorded, network-free file/shell operations."""
    sandbox = AioSandbox(id="test-sandbox", base_url="http://localhost:1")
    sandbox.written: list[tuple[str, str]] = []
    sandbox.commands: list[str] = []

    def write_file(path: str, content: str, append: bool = False) -> None:
        if write_error is not None:
            raise write_error
        sandbox.written.append((path, content))

    def execute_command(command: str) -> str:
        sandbox.commands.append(command)
        return exec_output

    sandbox.write_file = write_file
    sandbox.execute_command = execute_command
    return sandbox


# ── Helper script contents ───────────────────────────────────────────────────


class TestCredentialHelperScript:
    def test_is_posix_sh(self):
        assert CREDENTIAL_HELPER_SCRIPT.startswith("#!/bin/sh\n")

    def test_reads_token_from_environment_at_call_time(self):
        # The script must reference the env var, not an interpolated value.
        assert '"$GITHUB_TOKEN"' in CREDENTIAL_HELPER_SCRIPT

    def test_answers_github_over_https_with_x_access_token(self):
        assert "host=github.com" in CREDENTIAL_HELPER_SCRIPT
        assert "protocol=https" in CREDENTIAL_HELPER_SCRIPT
        assert "username=x-access-token" in CREDENTIAL_HELPER_SCRIPT

    def test_missing_token_prints_actionable_hint(self):
        assert "GITHUB_TOKEN is not set" in CREDENTIAL_HELPER_SCRIPT
        assert ".env.example" in CREDENTIAL_HELPER_SCRIPT

    def test_only_responds_to_get(self):
        # Store/erase requests must be ignored so git never persists the token.
        assert '[ "$1" != "get" ]' in CREDENTIAL_HELPER_SCRIPT


# ── setup_github_credentials ─────────────────────────────────────────────────


def _embedded_script(command: str) -> str:
    """Decode the helper script the setup command writes."""
    match = re.search(r"printf '%s' '([A-Za-z0-9+/=]+)' \| base64 -d", command)
    assert match, command
    return base64.b64decode(match.group(1)).decode("utf-8")


class TestSetupGithubCredentials:
    def test_installs_helper_through_the_shell_and_configures_git(self):
        sandbox = _make_sandbox()

        assert setup_github_credentials(sandbox, token_configured=True) is True

        # The file API writes as the API process; in the pinned 1.11.0 image
        # that cannot create files under /usr/local/bin, so the helper was
        # never installed. The shell writes as the sandbox user, into its home.
        assert sandbox.written == []
        assert sandbox.commands == [build_setup_command()]
        command = sandbox.commands[0]
        assert f'helper="$HOME/{CREDENTIAL_HELPER_HOME_PATH}"' in command
        assert "/usr/local/bin" not in command
        assert 'chmod 755 "$helper"' in command
        assert 'git config --global --replace-all credential.https://github.com.helper "$helper"' in command
        assert _embedded_script(command) == CREDENTIAL_HELPER_SCRIPT

    def test_command_is_one_line_in_a_subshell(self):
        # It runs in the agent's persistent shell: a newline would split it
        # into several prompts, and a bare variable would leak into the
        # agent's later commands.
        command = build_setup_command()
        assert "\n" not in command
        assert command.startswith("(") and command.endswith(")")

    def test_success_marker_is_not_in_the_command_text(self):
        # If the shell echoes the command back, the marker check must still
        # only pass when the command ran to the end.
        from deerflow.community.aio_sandbox import git_credentials

        assert git_credentials._SETUP_OK_MARKER not in build_setup_command()

    def test_token_value_never_reaches_the_sandbox_calls(self, monkeypatch):
        # The token travels exclusively via the container environment
        # (docker run -e, injected by the backend). Setup must not need it —
        # even with the token present on the host, nothing written or executed
        # may contain it.
        monkeypatch.setenv(TOKEN_ENV_VAR, SENTINEL_TOKEN)
        sandbox = _make_sandbox()

        setup_github_credentials(sandbox, token_configured=True)

        for _, content in sandbox.written:
            assert SENTINEL_TOKEN not in content
        for command in sandbox.commands:
            assert SENTINEL_TOKEN not in command

    def test_token_never_logged(self, monkeypatch, caplog):
        monkeypatch.setenv(TOKEN_ENV_VAR, SENTINEL_TOKEN)
        with caplog.at_level("DEBUG"):
            setup_github_credentials(_make_sandbox(), token_configured=True)
            setup_github_credentials(_make_sandbox(exec_output="Error: boom"), token_configured=True)
        assert SENTINEL_TOKEN not in caplog.text

    def test_git_missing_in_image_returns_false_without_raising(self):
        sandbox = _make_sandbox(exec_output="sh: git: not found\n")
        assert setup_github_credentials(sandbox, token_configured=False) is False

    def test_execute_error_returns_false_without_raising(self):
        # AioSandbox.execute_command reports failures as "Error: ..." strings.
        sandbox = _make_sandbox(exec_output="Error: connection refused")
        assert setup_github_credentials(sandbox, token_configured=True) is False

    def test_shell_permission_error_returns_false_and_logs_the_cause(self, caplog):
        # The shell's own error is the real cause; it must reach the log
        # verbatim instead of a generic "could not write".
        sandbox = _make_sandbox(exec_output="mkdir: cannot create directory '/home/gem/.local': Permission denied\n")
        with caplog.at_level("WARNING"):
            assert setup_github_credentials(sandbox, token_configured=True) is False
        assert "Permission denied" in caplog.text

    def test_execute_raising_returns_false_without_raising(self):
        sandbox = _make_sandbox()

        def boom(command: str) -> str:
            raise RuntimeError("sandbox client is closed")

        sandbox.execute_command = boom
        assert setup_github_credentials(sandbox, token_configured=True) is False


# ── The install command, executed for real ───────────────────────────────────


_GIT = shutil.which("git")
_SH = shutil.which("sh")
_BASE64 = shutil.which("base64")


@pytest.mark.skipif(not (_GIT and _SH and _BASE64), reason="needs git, sh and base64 on PATH")
class TestSetupCommandEndToEnd:
    def _clean_env(self, home, **extra):
        # Nothing from the host's git config may answer for the helper.
        return {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", **extra}

    def _fill(self, home, **extra):
        return subprocess.run(
            [_GIT, "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            env=self._clean_env(home, **extra),
            timeout=30,
        )

    def test_git_answers_github_with_the_container_token(self, tmp_path):
        setup = subprocess.run([_SH, "-c", build_setup_command()], capture_output=True, text=True, env=self._clean_env(tmp_path), timeout=30)
        assert "DEER_FLOW_GIT_CREDENTIALS_OK" in setup.stdout, setup.stderr

        helper = tmp_path / CREDENTIAL_HELPER_HOME_PATH
        assert helper.read_text(encoding="utf-8") == CREDENTIAL_HELPER_SCRIPT
        assert os.access(helper, os.X_OK)

        result = self._fill(tmp_path, GITHUB_TOKEN=SENTINEL_TOKEN)
        assert result.returncode == 0, result.stderr
        assert "username=x-access-token" in result.stdout
        assert f"password={SENTINEL_TOKEN}" in result.stdout
        # The token lives in the environment only, never in git's config.
        assert SENTINEL_TOKEN not in (tmp_path / ".gitconfig").read_text(encoding="utf-8")

    def test_rerun_keeps_a_single_helper_entry(self, tmp_path):
        for _ in range(2):
            subprocess.run([_SH, "-c", build_setup_command()], check=True, capture_output=True, env=self._clean_env(tmp_path), timeout=30)
        config = subprocess.run(
            [_GIT, "config", "--global", "--get-all", "credential.https://github.com.helper"],
            capture_output=True,
            text=True,
            env=self._clean_env(tmp_path),
            timeout=30,
        )
        assert config.stdout.strip().splitlines() == [str(tmp_path / CREDENTIAL_HELPER_HOME_PATH)]

    def test_unwritable_home_fails_without_the_marker(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        home.chmod(0o500)
        try:
            if os.access(home, os.W_OK):
                pytest.skip("running as a user that ignores directory permissions (root)")
            setup = subprocess.run([_SH, "-c", build_setup_command()], capture_output=True, text=True, env=self._clean_env(home), timeout=30)
        finally:
            home.chmod(0o700)
        assert "DEER_FLOW_GIT_CREDENTIALS_OK" not in setup.stdout
        assert "Permission denied" in setup.stdout + setup.stderr


# ── The pinned image's file-API refusal ──────────────────────────────────────


def _sandbox_answering_file_write(body: dict) -> AioSandbox:
    """A real AioSandbox whose HTTP layer answers /v1/file/write with ``body``."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/file/write"
        return httpx.Response(200, json=body)

    sandbox = AioSandbox(id="pinned-image", base_url="http://sandbox.test")
    sandbox._client = AioSandboxClient(base_url="http://sandbox.test", httpx_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return sandbox


class TestPinnedImageFileWriteRefusal:
    """agent-infra/sandbox 1.11.0 answers a write it cannot perform with HTTP 200
    and a ``data`` object that has no ``file`` key. The SDK's strict parse then
    raised ``1 validation error for ResponseFileWriteResult ... Field required``,
    which is what the Gateway logged instead of the permission problem."""

    REFUSAL = {"success": False, "message": "[Errno 13] Permission denied: '/usr/local/bin/deer-flow-git-credential'", "data": {"error": "PermissionError"}}

    def test_refusal_raises_oserror_naming_the_path(self):
        sandbox = _sandbox_answering_file_write(self.REFUSAL)
        with pytest.raises(OSError) as excinfo:
            sandbox.write_file("/usr/local/bin/deer-flow-git-credential", "#!/bin/sh\n")
        message = str(excinfo.value)
        assert "/usr/local/bin/deer-flow-git-credential" in message
        assert "PermissionError" in message
        assert "ResponseFileWriteResult" not in message

    def test_refusal_is_raised_for_binary_updates_too(self):
        sandbox = _sandbox_answering_file_write(self.REFUSAL)
        with pytest.raises(OSError, match="/usr/local/bin/x"):
            sandbox.update_file("/usr/local/bin/x", b"\x00")

    def test_a_successful_write_still_returns_quietly(self):
        sandbox = _sandbox_answering_file_write({"success": True, "message": "ok", "data": {"file": "/home/gem/x", "bytes_written": 3}})
        sandbox.write_file("/home/gem/x", "abc")


# ── Provider env resolution ──────────────────────────────────────────────────


def _provider_cls():
    return importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider").AioSandboxProvider


class TestResolveEnvVars:
    def test_github_token_resolved_from_host_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", SENTINEL_TOKEN)
        resolved = _provider_cls()._resolve_env_vars({"GITHUB_TOKEN": "$GITHUB_TOKEN"})
        assert resolved["GITHUB_TOKEN"] == SENTINEL_TOKEN

    def test_unset_reference_resolves_to_empty_string(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        resolved = _provider_cls()._resolve_env_vars({"GITHUB_TOKEN": "$GITHUB_TOKEN"})
        assert resolved["GITHUB_TOKEN"] == ""

    def test_literal_values_pass_through(self):
        resolved = _provider_cls()._resolve_env_vars({"NODE_ENV": "production", "DEBUG": "false"})
        assert resolved["NODE_ENV"] == "production"
        assert resolved["DEBUG"] == "false"

    def test_git_terminal_prompt_defaults_off(self):
        # Interactive git prompts would hang the agent's shell session.
        resolved = _provider_cls()._resolve_env_vars({})
        assert resolved["GIT_TERMINAL_PROMPT"] == "0"

    def test_git_terminal_prompt_user_override_wins(self):
        resolved = _provider_cls()._resolve_env_vars({"GIT_TERMINAL_PROMPT": "1"})
        assert resolved["GIT_TERMINAL_PROMPT"] == "1"


# ── Provider session init & lifecycle error paths ────────────────────────────


def _make_provider(environment: dict | None = None):
    """Minimal provider instance without __init__ side effects (idle checker, signals)."""
    from deerflow.community.aio_sandbox.ownership.memory import MemoryOwnershipStore
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    cls = _provider_cls()
    provider = cls.__new__(cls)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._config = {"environment": environment or {}, "replicas": 3}
    provider._backend = MagicMock()
    # Cross-instance ownership store state (upstream #4206): registration
    # publishes ownership, so a minimal provider still needs these attributes.
    provider._active_sandbox_identity = {}
    provider._warm_pool_identity = {}
    provider._local_teardown = set()
    provider._acquire_epoch = {}
    provider._acquire_epoch_counter = 0
    provider._acquire_inflight = {}
    provider._owner_id = "test-worker"
    provider._ownership_config = SandboxOwnershipConfig()
    provider._ownership = MemoryOwnershipStore(owner_id="test-worker", ttl_seconds=600)
    return provider


class TestSetupSandboxSession:
    def test_runs_credential_setup_for_tracked_sandbox(self, monkeypatch):
        provider = _make_provider(environment={"GITHUB_TOKEN": SENTINEL_TOKEN})
        sandbox = _make_sandbox()
        provider._sandboxes["sb1"] = sandbox

        recorded = {}

        def fake_setup(sb, *, token_configured):
            recorded["sandbox"] = sb
            recorded["token_configured"] = token_configured
            return True

        aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
        monkeypatch.setattr(aio_mod, "setup_github_credentials", fake_setup)

        provider._setup_sandbox_session("sb1")

        assert recorded["sandbox"] is sandbox
        assert recorded["token_configured"] is True

    def test_token_configured_false_when_env_missing(self, monkeypatch):
        provider = _make_provider(environment={})
        provider._sandboxes["sb1"] = _make_sandbox()

        recorded = {}
        aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
        monkeypatch.setattr(aio_mod, "setup_github_credentials", lambda sb, *, token_configured: recorded.setdefault("tc", token_configured))

        provider._setup_sandbox_session("sb1")
        assert recorded["tc"] is False

    def test_unknown_sandbox_is_a_noop(self):
        provider = _make_provider()
        provider._setup_sandbox_session("missing")  # must not raise

    def test_setup_exception_is_swallowed(self, monkeypatch):
        provider = _make_provider()
        provider._sandboxes["sb1"] = _make_sandbox()

        aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")

        def boom(sb, *, token_configured):
            raise RuntimeError("setup exploded")

        monkeypatch.setattr(aio_mod, "setup_github_credentials", boom)
        provider._setup_sandbox_session("sb1")  # must not raise


class TestCreateSandboxLifecycle:
    def _prepare_create(self, provider, monkeypatch):
        aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
        info = SandboxInfo(sandbox_id="sb-new", sandbox_url="http://localhost:1", container_name="c1")
        provider._backend.create.return_value = info
        monkeypatch.setattr(provider, "_get_extra_mounts", lambda thread_id, user_id=None: [])
        return aio_mod, info

    def test_creation_survives_failed_session_init(self, monkeypatch):
        provider = _make_provider(environment={"GITHUB_TOKEN": SENTINEL_TOKEN})
        aio_mod, _ = self._prepare_create(provider, monkeypatch)
        monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda url, timeout: True)

        def boom(sb, *, token_configured):
            raise RuntimeError("git setup failed")

        monkeypatch.setattr(aio_mod, "setup_github_credentials", boom)

        sandbox_id = provider._create_sandbox("thread-1", "sb-new", user_id="default")

        assert sandbox_id == "sb-new"
        assert "sb-new" in provider._sandboxes

    def test_readiness_timeout_raises_clear_error_and_destroys(self, monkeypatch):
        provider = _make_provider()
        aio_mod, info = self._prepare_create(provider, monkeypatch)
        monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda url, timeout: False)

        with pytest.raises(RuntimeError, match="failed to become ready within timeout"):
            provider._create_sandbox("thread-1", "sb-new", user_id="default")

        provider._backend.destroy.assert_called_once_with(info)
