"""Tests for Camoufox's anti-detection launch options.

Camoufox is a stealth browser that was being launched with its stealth off —
``AsyncCamoufox(headless=True)`` and nothing more. These cover the options it
now gets, where they come from, and the one property that protects the tool:
**a launch that fails with them retries without them.**

That retry is why this feature cannot repeat FORK.md §31. There, a browser that
was present but unrunnable made every fetch fail while every presence check
passed. An option Camoufox rejects — an unsupported key on an older build, a
geoip database that was never downloaded, a proxy that is refusing connections —
is exactly that shape of problem, and it must cost stealth rather than web_fetch.
"""

from __future__ import annotations

import sys
import types

import pytest

import deerflow.community.camoufox_fetch.browser as browser_mod


class _FakeToolConfig:
    def __init__(self, extra):
        self.model_extra = extra


@pytest.fixture
def set_web_fetch_config(monkeypatch):
    """Install a fake web_fetch tool config that browser.py will read."""

    def _install(extra):
        cfg = _FakeToolConfig(extra) if extra is not None else None

        class _AppConfig:
            def get_tool_config(self, name):
                assert name == "web_fetch"
                return cfg

        fake = types.ModuleType("deerflow.config")
        fake.get_app_config = lambda: _AppConfig()
        monkeypatch.setitem(sys.modules, "deerflow.config", fake)

    return _install


class TestOptionResolution:
    def test_the_defaults_turn_the_stealth_on(self, set_web_fetch_config):
        """geoip is the one that matters behind a VPN; all three ship on."""
        set_web_fetch_config(None)
        options = browser_mod._stealth_launch_options()
        assert options["geoip"] is True
        assert options["humanize"] is True
        assert options["block_webrtc"] is True

    def test_an_entry_without_a_camoufox_block_gets_the_defaults(self, set_web_fetch_config):
        """A config.yaml predating this feature must not lose the browser."""
        set_web_fetch_config({"backend": "camoufox", "timeout": 30})
        assert browser_mod._stealth_launch_options() == dict(browser_mod._STEALTH_DEFAULTS)

    def test_config_overrides_a_default(self, set_web_fetch_config):
        set_web_fetch_config({"camoufox": {"humanize": 2.5, "locale": "en-GB"}})
        options = browser_mod._stealth_launch_options()
        assert options["humanize"] == 2.5
        assert options["locale"] == "en-GB"
        assert options["geoip"] is True, "unset keys keep their default"

    def test_null_removes_an_option_entirely(self, set_web_fetch_config):
        """`geoip: null` hands the decision back to Camoufox, not `geoip=False`.

        The two differ: False asserts a choice, absent lets Camoufox choose.
        """
        set_web_fetch_config({"camoufox": {"geoip": None}})
        assert "geoip" not in browser_mod._stealth_launch_options()

    def test_an_unknown_key_in_the_block_is_ignored(self, set_web_fetch_config):
        """Only the documented keys reach Camoufox; a typo must not be forwarded."""
        set_web_fetch_config({"camoufox": {"geiop": True, "nonsense": 1}})
        options = browser_mod._stealth_launch_options()
        assert "geiop" not in options and "nonsense" not in options

    def test_the_jina_proxy_key_does_not_reach_the_browser(self, set_web_fetch_config):
        """web_fetch's top-level `proxy:` is documented for the jina backend.

        Reading it here would silently repoint a user's jina proxy at the
        browser — a different process, a different network path, and a setting
        they never made for it. Camoufox's proxy lives inside `camoufox:`.
        """
        set_web_fetch_config({"proxy": "http://jina-proxy:8080", "camoufox": {}})
        assert "proxy" not in browser_mod._stealth_launch_options()

    def test_a_camoufox_proxy_does_reach_the_browser(self, set_web_fetch_config):
        set_web_fetch_config({"camoufox": {"proxy": "socks5://127.0.0.1:1080"}})
        assert browser_mod._stealth_launch_options()["proxy"] == "socks5://127.0.0.1:1080"

    def test_a_non_dict_camoufox_block_falls_back_to_defaults(self, set_web_fetch_config):
        set_web_fetch_config({"camoufox": "yes please"})
        assert browser_mod._stealth_launch_options() == dict(browser_mod._STEALTH_DEFAULTS)

    def test_an_unresolvable_config_yields_defaults_rather_than_raising(self, monkeypatch):
        """This runs on the launch path; a config error must not stop the browser."""
        fake = types.ModuleType("deerflow.config")

        def _boom():
            raise FileNotFoundError("config.yaml not found")

        fake.get_app_config = _boom
        monkeypatch.setitem(sys.modules, "deerflow.config", fake)
        assert browser_mod._stealth_launch_options() == dict(browser_mod._STEALTH_DEFAULTS)


def _install_fake_camoufox(monkeypatch, behaviour):
    """Stub camoufox.async_api.AsyncCamoufox; record the kwargs of each attempt."""
    attempts: list[dict] = []

    class _FakeCM:
        def __init__(self, **kwargs):
            attempts.append(kwargs)
            self._kwargs = kwargs

        async def __aenter__(self):
            outcome = behaviour(self._kwargs)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        async def __aexit__(self, *exc):
            return False

    module = types.ModuleType("camoufox.async_api")
    module.AsyncCamoufox = _FakeCM
    monkeypatch.setitem(sys.modules, "camoufox.async_api", module)
    monkeypatch.setattr(browser_mod, "_camoufox_browser_present", lambda: True)
    return attempts


class TestLaunchDegradesRatherThanFailing:
    @pytest.mark.asyncio
    async def test_a_rejected_stealth_option_retries_bare(self, set_web_fetch_config, monkeypatch):
        """The load-bearing property: stealth is optional, web_fetch is not."""
        set_web_fetch_config(None)
        attempts = _install_fake_camoufox(
            monkeypatch,
            lambda kw: TypeError("unexpected keyword argument 'geoip'") if len(kw) > 1 else "BROWSER",
        )

        manager = browser_mod._BrowserManager()
        browser = await manager._launch()

        assert browser == "BROWSER"
        assert len(attempts) == 2, "one attempt with stealth, one without"
        assert "geoip" in attempts[0]
        assert attempts[1] == {"headless": True}, "the retry is the pre-feature launch, exactly"

    @pytest.mark.asyncio
    async def test_a_successful_stealth_launch_does_not_retry(self, set_web_fetch_config, monkeypatch):
        set_web_fetch_config(None)
        attempts = _install_fake_camoufox(monkeypatch, lambda kw: "BROWSER")

        manager = browser_mod._BrowserManager()
        assert await manager._launch() == "BROWSER"
        assert len(attempts) == 1
        assert attempts[0]["geoip"] is True

    @pytest.mark.asyncio
    async def test_a_missing_browser_still_raises_and_is_not_retried(self, set_web_fetch_config, monkeypatch):
        """A missing binary is not a stealth problem, and the retry must not mask it.

        Swallowing it into a bare relaunch would turn the actionable "run
        make fetch-browser" message into a second, identical failure.
        """
        set_web_fetch_config(None)
        attempts = _install_fake_camoufox(monkeypatch, lambda kw: RuntimeError("Executable doesn't exist; please run camoufox fetch"))

        manager = browser_mod._BrowserManager()
        with pytest.raises(browser_mod.CamoufoxBrowserMissingError):
            await manager._launch()
        assert len(attempts) == 1, "a missing browser must not be retried"

    @pytest.mark.asyncio
    async def test_with_stealth_disabled_a_failure_propagates(self, set_web_fetch_config, monkeypatch):
        """No options means nothing to degrade to, so the error is the answer."""
        set_web_fetch_config({"camoufox": {"geoip": None, "humanize": None, "block_webrtc": None}})
        attempts = _install_fake_camoufox(monkeypatch, lambda kw: RuntimeError("some launch failure"))

        manager = browser_mod._BrowserManager()
        with pytest.raises(RuntimeError, match="some launch failure"):
            await manager._launch()
        assert len(attempts) == 1
