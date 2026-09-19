"""Tests for the pluggable web_search dispatcher.

Covers backend selection (env > config > default searxng), the fallback chain,
the API-key gate on a key-bearing fallback, and the both-failed report.
Backends are stubbed — no network, no SearXNG container, no Tavily credits.

The load-bearing test here is ``test_an_empty_result_set_does_not_trigger_the
_fallback``. SearXNG answers HTTP 200 with an empty array both when nothing
matched and when every engine was blocked, and only an exception separates the
two (FORK.md §31). A dispatcher that fell back on "no results" would spend a
metered third-party credit on every genuine no-match query and route those
queries off the machine — silently, with the suite still green.
"""

from __future__ import annotations

import json

import pytest

import deerflow.community.web_search.tools as dispatcher


class _FakeToolConfig:
    def __init__(self, extra: dict | None):
        self.model_extra = extra


@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch):
    """The dispatcher reads real env vars; keep the host's out of the tests."""
    monkeypatch.delenv(dispatcher._ENV_BACKEND, raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


@pytest.fixture
def set_config(monkeypatch):
    """Install a fake web_search tool config (model_extra dict)."""

    def _install(extra: dict | None):
        cfg = _FakeToolConfig(extra) if extra is not None else None

        class _AppConfig:
            def get_tool_config(self, name):
                return cfg

        monkeypatch.setattr(dispatcher, "get_app_config", lambda: _AppConfig())

    return _install


@pytest.fixture
def stub_backends(monkeypatch):
    """Replace _load_backend with stubs keyed by name; records call order.

    A stub value that is an Exception instance is raised, mirroring how a real
    backend signals failure.
    """
    calls: list[str] = []

    def _install(results: dict[str, object]):
        def _fake_load(name):
            if name not in results:
                return None

            async def _search(query, time_range=None):
                calls.append(name)
                value = results[name]
                if isinstance(value, Exception):
                    raise value
                return value

            return _search

        monkeypatch.setattr(dispatcher, "_load_backend", _fake_load)
        return calls

    return _install


@pytest.fixture
def set_fallback_available(monkeypatch):
    def _install(available: bool):
        monkeypatch.setattr(dispatcher, "_fallback_is_available", lambda name: available)

    return _install


# --------------------------------------------------------------------------
# Backend resolution
# --------------------------------------------------------------------------


class TestBackendResolution:
    def test_the_default_backend_is_searxng(self, set_config):
        """No env, no config -> the local-first engine, never a metered one."""
        set_config(None)
        assert dispatcher._resolve_backends() == ("searxng", None)

    def test_config_selects_the_backend_and_the_fallback(self, set_config):
        set_config({"backend": "searxng", "fallback": "tavily"})
        assert dispatcher._resolve_backends() == ("searxng", "tavily")

    def test_an_entry_without_a_backend_key_still_gets_searxng(self, set_config):
        """An existing config.yaml predating this dispatcher must not break."""
        set_config({"base_url": "http://localhost:8088", "max_results": 5})
        assert dispatcher._resolve_backends() == ("searxng", None)

    def test_the_env_var_overrides_the_configured_backend(self, set_config, monkeypatch):
        monkeypatch.setenv(dispatcher._ENV_BACKEND, "tavily")
        set_config({"backend": "searxng", "fallback": "tavily"})
        primary, fallback = dispatcher._resolve_backends()
        assert primary == "tavily"
        assert fallback == "tavily"


# --------------------------------------------------------------------------
# The empty-vs-error distinction (FORK.md §31)
# --------------------------------------------------------------------------


class TestEmptyIsNotAnError:
    @pytest.mark.asyncio
    async def test_an_empty_result_set_does_not_trigger_the_fallback(self, set_config, stub_backends, set_fallback_available):
        """A search that matched nothing is a SUCCESS, not a reason to fall back.

        This is the property a refactor quietly breaks by treating "no results"
        as failure. If it breaks, every zero-match query silently bills Tavily
        and leaves the machine, and nothing in the suite goes red but this.
        """
        set_config({"backend": "searxng", "fallback": "tavily"})
        set_fallback_available(True)
        calls = stub_backends({"searxng": "[]", "tavily": '[{"title": "nope"}]'})

        result = await dispatcher.dispatch_web_search("query with no matches")

        assert result == "[]"
        assert calls == ["searxng"], "the fallback must not run for an empty-but-successful search"

    @pytest.mark.asyncio
    async def test_a_raising_primary_does_trigger_the_fallback(self, set_config, stub_backends, set_fallback_available):
        set_config({"backend": "searxng", "fallback": "tavily"})
        set_fallback_available(True)
        calls = stub_backends(
            {
                "searxng": RuntimeError("every engine was unavailable"),
                "tavily": '[{"title": "from tavily"}]',
            }
        )

        result = await dispatcher.dispatch_web_search("anything")

        assert result == '[{"title": "from tavily"}]'
        assert calls == ["searxng", "tavily"]


# --------------------------------------------------------------------------
# The API-key gate
# --------------------------------------------------------------------------


class TestFallbackKeyGate:
    @pytest.mark.asyncio
    async def test_a_keyless_tavily_fallback_is_skipped_and_the_primary_error_stands(self, set_config, stub_backends, set_fallback_available):
        """No TAVILY_API_KEY -> behave exactly as before the fallback existed.

        The primary's message must survive verbatim; burying it under a Tavily
        credentials error would hide the failure the user actually needs.
        """
        set_config({"backend": "searxng", "fallback": "tavily"})
        set_fallback_available(False)
        calls = stub_backends({"searxng": RuntimeError("engines unavailable: brave, duckduckgo"), "tavily": "[]"})

        result = await dispatcher.dispatch_web_search("q")

        assert calls == ["searxng"], "a fallback with no key must not be invoked"
        payload = json.loads(result)
        assert payload["query"] == "q"
        assert "engines unavailable: brave, duckduckgo" in payload["error"]

    def test_the_key_gate_reads_the_environment(self, monkeypatch):
        """tavily_api_key_present() is what the gate consults; env is the .env path."""
        import deerflow.community.tavily.tools as tavily_tools

        class _AppConfig:
            def get_tool_config(self, name):
                return None

        monkeypatch.setattr(tavily_tools, "get_app_config", lambda: _AppConfig())
        assert tavily_tools.tavily_api_key_present() is False
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-something")
        assert tavily_tools.tavily_api_key_present() is True

    def test_the_key_gate_survives_an_unresolvable_config(self, monkeypatch):
        """A config error must not take down web_search via the fallback gate.

        The gate runs outside the dispatcher's try block, so a raise here would
        propagate out of the tool. It must degrade to the env var instead.
        """
        import deerflow.community.tavily.tools as tavily_tools

        def _boom():
            raise FileNotFoundError("config.yaml not found")

        monkeypatch.setattr(tavily_tools, "get_app_config", _boom)
        assert tavily_tools.tavily_api_key_present() is False
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-something")
        assert tavily_tools.tavily_api_key_present() is True

    def test_a_non_key_bearing_fallback_is_always_available(self):
        assert dispatcher._fallback_is_available("searxng") is True


# --------------------------------------------------------------------------
# Failure reporting
# --------------------------------------------------------------------------


class TestFailureReporting:
    @pytest.mark.asyncio
    async def test_both_backends_failing_reports_both(self, set_config, stub_backends, set_fallback_available):
        set_config({"backend": "searxng", "fallback": "tavily"})
        set_fallback_available(True)
        stub_backends({"searxng": RuntimeError("searxng down"), "tavily": RuntimeError("tavily 401")})

        payload = json.loads(await dispatcher.dispatch_web_search("q"))

        assert "searxng down" in payload["error"]
        assert "tavily 401" in payload["error"]

    @pytest.mark.asyncio
    async def test_no_fallback_configured_reports_the_primary_failure(self, set_config, stub_backends):
        set_config({"backend": "searxng"})
        stub_backends({"searxng": RuntimeError("searxng down")})

        payload = json.loads(await dispatcher.dispatch_web_search("q"))

        assert payload["error"] == "searxng down"
        assert payload["query"] == "q"

    @pytest.mark.asyncio
    async def test_an_unknown_primary_backend_is_named_in_the_error(self, set_config, stub_backends):
        set_config({"backend": "nope"})
        stub_backends({"searxng": "[]"})

        payload = json.loads(await dispatcher.dispatch_web_search("q"))

        assert "nope" in payload["error"]

    @pytest.mark.asyncio
    async def test_an_unknown_fallback_does_not_swallow_the_primary_failure(self, set_config, stub_backends, set_fallback_available):
        set_config({"backend": "searxng", "fallback": "nope"})
        set_fallback_available(True)
        stub_backends({"searxng": RuntimeError("searxng down")})

        payload = json.loads(await dispatcher.dispatch_web_search("q"))

        assert "searxng down" in payload["error"]
        assert "nope" in payload["error"]


# --------------------------------------------------------------------------
# The blocking-SDK boundary
# --------------------------------------------------------------------------


class TestTavilyIsNotCalledOnTheEventLoop:
    def test_search_via_tavily_is_a_coroutine_function(self):
        """The Tavily SDK is synchronous; the dispatcher path must be awaitable.

        If a refactor drops the asyncio.to_thread wrapper and exposes the sync
        call directly, the dispatcher's `await` fails loudly here rather than
        stalling the agent's event loop in production.
        """
        import inspect

        from deerflow.community.tavily.tools import search_via_tavily

        assert inspect.iscoroutinefunction(search_via_tavily)


class TestAnUnloadableBackendDegrades:
    """A backup that cannot import is a backup that is not there.

    The fallback is resolved outside the dispatcher's try block, so an
    ImportError there — a provider SDK trimmed from the install, or moved to an
    optional extra the way camoufox is — would escape the tool as a traceback
    and REPLACE the primary's real failure with a crash. The whole point of a
    fallback is to make failures better; it must never make them worse.
    """

    @pytest.mark.asyncio
    async def test_an_unimportable_fallback_leaves_the_primary_error_intact(self, set_config, monkeypatch, set_fallback_available):
        set_config({"backend": "searxng", "fallback": "tavily"})
        set_fallback_available(True)

        async def _searxng(query, time_range=None):
            raise RuntimeError("engines unavailable")

        def _fake_load(name):
            if name == "searxng":
                return _searxng
            raise ImportError("No module named 'tavily'")

        monkeypatch.setattr(dispatcher, "_load_backend", _fake_load)

        payload = json.loads(await dispatcher.dispatch_web_search("q"))

        assert "engines unavailable" in payload["error"]
        assert "tavily" in payload["error"]

    @pytest.mark.asyncio
    async def test_an_unimportable_primary_is_reported_not_raised(self, set_config, monkeypatch):
        set_config({"backend": "searxng"})

        def _fake_load(name):
            raise ImportError("boom")

        monkeypatch.setattr(dispatcher, "_load_backend", _fake_load)

        payload = json.loads(await dispatcher.dispatch_web_search("q"))

        assert "searxng" in payload["error"]

    def test_the_key_gate_reports_unavailable_when_the_provider_cannot_import(self, monkeypatch):
        """_fallback_is_available must not raise either — same call site, same rule."""
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if "tavily" in name:
                raise ImportError("No module named 'tavily'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        assert dispatcher._fallback_is_available("tavily") is False
