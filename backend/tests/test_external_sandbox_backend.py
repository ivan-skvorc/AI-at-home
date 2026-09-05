"""Tests for ExternalSandboxBackend and its wiring into AioSandboxProvider.

External mode binds to one pre-existing container (config `sandbox.base_url`)
that DeerFlow must never create or destroy. These tests mock HTTP only — no
Docker, no real container.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from deerflow.community.aio_sandbox.external_backend import ExternalSandboxBackend
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

BASE_URL = "http://localhost:8091"


def _ok_response():
    resp = MagicMock()
    resp.status_code = 200
    return resp


class TestExternalBackendBasics:
    def test_stable_sandbox_id_derived_from_url(self):
        backend = ExternalSandboxBackend(base_url=BASE_URL)
        assert backend.external_sandbox_id.startswith("external-")
        # Same URL → same id (cross-process convergence on one sandbox).
        assert ExternalSandboxBackend(base_url=BASE_URL).external_sandbox_id == backend.external_sandbox_id
        # Different URL → different id.
        assert ExternalSandboxBackend(base_url="http://localhost:9000").external_sandbox_id != backend.external_sandbox_id

    def test_trailing_slash_normalized(self):
        assert ExternalSandboxBackend(base_url=BASE_URL + "/").base_url == BASE_URL

    def test_session_init_on_discover_flag(self):
        # The provider re-runs git-credential init on discovery for external mode.
        assert ExternalSandboxBackend(base_url=BASE_URL).session_init_on_discover is True

    def test_create_returns_static_info_and_ignores_thread(self):
        backend = ExternalSandboxBackend(base_url=BASE_URL)
        info = backend.create("thread-a", "some-derived-id", extra_mounts=[("h", "c", False)])
        assert info.sandbox_url == BASE_URL
        assert info.sandbox_id == backend.external_sandbox_id
        # Different thread → same static sandbox.
        assert backend.create("thread-b", "other-id").sandbox_id == info.sandbox_id


class TestNeverTouchesContainer:
    def test_destroy_is_a_noop_and_makes_no_network_call(self):
        backend = ExternalSandboxBackend(base_url=BASE_URL)
        info = SandboxInfo(sandbox_id=backend.external_sandbox_id, sandbox_url=BASE_URL)
        with patch("deerflow.community.aio_sandbox.external_backend.requests") as req:
            backend.destroy(info)  # must not raise, must not call requests
            req.get.assert_not_called()
            req.post.assert_not_called()

    def test_no_docker_cli_invocation(self):
        # The module must never shell out (to docker or anything else); it only
        # talks to the external container over HTTP via requests.
        import deerflow.community.aio_sandbox.external_backend as mod

        with open(mod.__file__, encoding="utf-8") as f:
            text = f.read()
        for shell_api in ("import subprocess", "os.system", "Popen", "os.popen"):
            assert shell_api not in text


class TestHealthChecks:
    def test_is_alive_true_on_200(self):
        backend = ExternalSandboxBackend(base_url=BASE_URL)
        with patch("deerflow.community.aio_sandbox.external_backend.requests.get", return_value=_ok_response()) as get:
            assert backend.is_alive(SandboxInfo(sandbox_id="x", sandbox_url=BASE_URL)) is True
            get.assert_called_once()
            assert get.call_args[0][0] == f"{BASE_URL}/v1/sandbox"

    def test_is_alive_false_on_exception(self):
        backend = ExternalSandboxBackend(base_url=BASE_URL)
        with patch("deerflow.community.aio_sandbox.external_backend.requests.get", side_effect=requests.RequestException("boom")):
            assert backend.is_alive(SandboxInfo(sandbox_id="x", sandbox_url=BASE_URL)) is False

    def test_discover_returns_info_when_healthy_else_none(self):
        backend = ExternalSandboxBackend(base_url=BASE_URL)
        with patch("deerflow.community.aio_sandbox.external_backend.requests.get", return_value=_ok_response()):
            assert backend.discover("anything").sandbox_url == BASE_URL
        with patch("deerflow.community.aio_sandbox.external_backend.requests.get", side_effect=requests.RequestException):
            assert backend.discover("anything") is None

    def test_list_running_reflects_health(self):
        backend = ExternalSandboxBackend(base_url=BASE_URL)
        with patch("deerflow.community.aio_sandbox.external_backend.requests.get", return_value=_ok_response()):
            assert len(backend.list_running()) == 1
        with patch("deerflow.community.aio_sandbox.external_backend.requests.get", side_effect=requests.RequestException):
            assert backend.list_running() == []


# ── Provider backend selection & plumbing ────────────────────────────────────


def _make_provider_config(**overrides):
    base = {
        "image": "img",
        "port": 8080,
        "container_prefix": "p",
        "idle_timeout": 0,  # disable idle checker thread in tests
        "replicas": 3,
        "mounts": [],
        "environment": {"GIT_TERMINAL_PROMPT": "0"},
        "provisioner_url": "",
        "base_url": "",
        "request_timeout": None,
        # Upstream's controlled-egress mode reads this in _create_backend; the
        # open default is what SandboxNetworkConfig ships and what every test
        # here is about (local container selection, mounts warnings).
        "network": {"mode": "open"},
    }
    base.update(overrides)
    return base


class TestBackendSelection:
    @pytest.fixture
    def provider_cls(self):
        from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

        return AioSandboxProvider

    def _build_with_config(self, provider_cls, config):
        # Bypass __init__ (which spins threads / atexit) and drive _create_backend directly.
        provider = object.__new__(provider_cls)
        provider._config = config
        return provider

    def test_base_url_selects_external_backend(self, provider_cls):
        provider = self._build_with_config(provider_cls, _make_provider_config(base_url=BASE_URL))
        backend = provider._create_backend()
        assert isinstance(backend, ExternalSandboxBackend)
        assert backend.base_url == BASE_URL

    def test_provisioner_url_wins_over_base_url(self, provider_cls):
        from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend

        provider = self._build_with_config(
            provider_cls,
            _make_provider_config(base_url=BASE_URL, provisioner_url="http://provisioner:8002"),
        )
        assert isinstance(provider._create_backend(), RemoteSandboxBackend)

    def test_default_is_local_container_backend(self, provider_cls):
        from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend

        provider = self._build_with_config(provider_cls, _make_provider_config())
        assert isinstance(provider._create_backend(), LocalContainerBackend)


class TestMountsWarning:
    @pytest.fixture
    def provider_cls(self):
        from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

        return AioSandboxProvider

    def test_external_mode_warns_on_configured_mounts(self, provider_cls, caplog):
        import logging

        provider = object.__new__(provider_cls)
        provider._config = _make_provider_config(base_url=BASE_URL, mounts=[{"host_path": "/data", "container_path": "/mnt/data"}])
        with caplog.at_level(logging.WARNING):
            provider._create_backend()
        assert any("sandbox.mounts is ignored" in r.getMessage() and "/data" in r.getMessage() for r in caplog.records)

    def test_external_mode_no_mounts_no_warning(self, provider_cls, caplog):
        import logging

        provider = object.__new__(provider_cls)
        provider._config = _make_provider_config(base_url=BASE_URL)
        with caplog.at_level(logging.WARNING):
            provider._create_backend()
        assert not any("sandbox.mounts is ignored" in r.getMessage() for r in caplog.records)

    def test_external_mode_warns_on_user_environment(self, provider_cls, caplog):
        import logging

        provider = object.__new__(provider_cls)
        provider._config = _make_provider_config(base_url=BASE_URL, environment={"GIT_TERMINAL_PROMPT": "0", "API_KEY": "secret"})
        with caplog.at_level(logging.WARNING):
            provider._create_backend()
        messages = [r.getMessage() for r in caplog.records]
        assert any("sandbox.environment" in m and "API_KEY" in m for m in messages)
        # The token value must never be logged.
        assert not any("secret" in m for m in messages)


class TestRequestTimeoutPlumbing:
    def test_request_timeout_flows_into_aiosandbox_client(self):
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient") as client_cls:
            AioSandbox(id="s1", base_url=BASE_URL, request_timeout=120.0)
            assert client_cls.call_args.kwargs["timeout"] == 120.0

    def test_default_timeout_is_600_when_unset(self):
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient") as client_cls:
            AioSandbox(id="s1", base_url=BASE_URL)
            assert client_cls.call_args.kwargs["timeout"] == 600
