"""Tests for in-container GitHub credential setup (aio_sandbox.git_credentials).

Covers:
- the credential helper script never embeds a token (it reads the container
  env at git-invocation time),
- setup never writes/executes/logs the token value,
- setup failure paths degrade gracefully (no raise, sandbox still usable),
- provider env resolution injects GITHUB_TOKEN from the host environment,
- sandbox creation succeeds even when session init fails.
"""

from __future__ import annotations

import importlib
import threading
from unittest.mock import MagicMock

import pytest

from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
from deerflow.community.aio_sandbox.git_credentials import (
    CREDENTIAL_HELPER_PATH,
    CREDENTIAL_HELPER_SCRIPT,
    TOKEN_ENV_VAR,
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


class TestSetupGithubCredentials:
    def test_installs_helper_and_configures_git(self):
        sandbox = _make_sandbox()

        assert setup_github_credentials(sandbox, token_configured=True) is True

        assert sandbox.written == [(CREDENTIAL_HELPER_PATH, CREDENTIAL_HELPER_SCRIPT)]
        assert len(sandbox.commands) == 1
        command = sandbox.commands[0]
        assert f"chmod 755 {CREDENTIAL_HELPER_PATH}" in command
        assert "git config --global --replace-all credential.https://github.com.helper" in command

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

    def test_write_failure_returns_false_without_raising(self):
        sandbox = _make_sandbox(write_error=RuntimeError("read-only fs"))
        assert setup_github_credentials(sandbox, token_configured=True) is False
        assert sandbox.commands == []  # no point configuring git without the helper


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
