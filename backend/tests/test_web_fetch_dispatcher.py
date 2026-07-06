"""Tests for the pluggable web_fetch dispatcher.

Covers backend selection (env > config > default jina), the fallback chain, the
both-failed report, and the private-GitHub 404 hint. Backends are stubbed — no
network, no browser.
"""

from __future__ import annotations

import pytest

import deerflow.community.web_fetch.tools as dispatcher


class _FakeToolConfig:
    def __init__(self, extra: dict):
        self.model_extra = extra


@pytest.fixture
def set_config(monkeypatch):
    """Install a fake web_fetch tool config (model_extra dict)."""

    def _install(extra: dict | None):
        cfg = _FakeToolConfig(extra) if extra is not None else None

        class _AppConfig:
            def get_tool_config(self, name):
                return cfg

        monkeypatch.setattr(dispatcher, "get_app_config", lambda: _AppConfig())

    return _install


@pytest.fixture
def stub_backends(monkeypatch):
    """Replace _load_backend with stub callables keyed by name."""
    calls: list[str] = []

    def _install(results: dict[str, str]):
        def _fake_load(name):
            if name not in results:
                return None

            async def _fetch(url):
                calls.append(name)
                value = results[name]
                return value(url) if callable(value) else value

            return _fetch

        monkeypatch.setattr(dispatcher, "_load_backend", _fake_load)
        return calls

    return _install


async def _run(url="https://example.com"):
    return await dispatcher.dispatch_web_fetch(url)


class TestBackendSelection:
    @pytest.mark.anyio
    async def test_default_is_jina(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config(None)
        calls = stub_backends({"jina": "JINA-OK"})
        assert await _run() == "JINA-OK"
        assert calls == ["jina"]

    @pytest.mark.anyio
    async def test_config_selects_camoufox(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config({"backend": "camoufox"})
        calls = stub_backends({"camoufox": "CAMO-OK", "jina": "JINA-OK"})
        assert await _run() == "CAMO-OK"
        assert calls == ["camoufox"]

    @pytest.mark.anyio
    async def test_env_overrides_config(self, set_config, stub_backends, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_WEB_FETCH_BACKEND", "jina")
        set_config({"backend": "camoufox"})
        calls = stub_backends({"camoufox": "CAMO-OK", "jina": "JINA-OK"})
        assert await _run() == "JINA-OK"
        assert calls == ["jina"]

    @pytest.mark.anyio
    async def test_unknown_backend_errors(self, set_config, stub_backends, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_WEB_FETCH_BACKEND", "bogus")
        set_config(None)
        stub_backends({"jina": "JINA-OK"})
        result = await _run()
        assert result.startswith("Error: unknown web_fetch backend 'bogus'")


class TestFallbackChain:
    @pytest.mark.anyio
    async def test_fallback_fires_on_primary_error(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config({"backend": "camoufox", "fallback": "jina"})
        calls = stub_backends({"camoufox": "Error: boom", "jina": "JINA-OK"})
        assert await _run() == "JINA-OK"
        assert calls == ["camoufox", "jina"]

    @pytest.mark.anyio
    async def test_no_fallback_when_primary_succeeds(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config({"backend": "camoufox", "fallback": "jina"})
        calls = stub_backends({"camoufox": "CAMO-OK", "jina": "JINA-OK"})
        assert await _run() == "CAMO-OK"
        assert calls == ["camoufox"]

    @pytest.mark.anyio
    async def test_both_fail_reports_both(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config({"backend": "camoufox", "fallback": "jina"})
        stub_backends({"camoufox": "Error: camo-bad", "jina": "Error: jina-bad"})
        result = await _run()
        assert "both backends" in result
        assert "camo-bad" in result
        assert "jina-bad" in result

    @pytest.mark.anyio
    async def test_fallback_equal_to_primary_is_ignored(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config({"backend": "jina", "fallback": "jina"})
        calls = stub_backends({"jina": "Error: nope"})
        result = await _run()
        assert calls == ["jina"]  # not called twice
        assert result == "Error: nope"


class TestGithubHint:
    @pytest.mark.anyio
    async def test_github_404_gets_private_repo_hint(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config(None)
        stub_backends({"jina": "Error: Jina API returned status 404: Not Found"})
        result = await dispatcher.dispatch_web_fetch("https://github.com/acme/secret")
        assert "private GitHub repository" in result
        assert "git clone https://github.com/OWNER/REPO.git" in result

    @pytest.mark.anyio
    async def test_non_github_404_gets_no_hint(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config(None)
        stub_backends({"jina": "Error: 404 Not Found"})
        result = await dispatcher.dispatch_web_fetch("https://example.com/missing")
        assert "private GitHub repository" not in result

    @pytest.mark.anyio
    async def test_github_success_gets_no_hint(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config(None)
        stub_backends({"jina": "# Public repo README\n\ncontent"})
        result = await dispatcher.dispatch_web_fetch("https://github.com/acme/public")
        assert "private GitHub repository" not in result

    @pytest.mark.anyio
    async def test_github_hint_after_both_backends_fail(self, set_config, stub_backends, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_WEB_FETCH_BACKEND", raising=False)
        set_config({"backend": "camoufox", "fallback": "jina"})
        stub_backends({"camoufox": "Error: 404", "jina": "Error: Not Found"})
        result = await dispatcher.dispatch_web_fetch("https://github.com/acme/secret")
        assert "private GitHub repository" in result


@pytest.fixture
def anyio_backend():
    return "asyncio"
