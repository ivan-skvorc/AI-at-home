"""Tests for the Camoufox web_fetch backend and its shared browser manager.

The browser is fully mocked — no real Camoufox launch, no network. Verifies
instance reuse across requests, page cleanup, clean shutdown, the actionable
failure messages, and that readability extraction is offloaded off the loop.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import deerflow.community.camoufox_fetch.browser as browser_mod
import deerflow.community.camoufox_fetch.tools as camoufox_tools


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeToolConfig:
    def __init__(self, extra: dict):
        self.model_extra = extra


@pytest.fixture(autouse=True)
def _default_config(monkeypatch):
    """Default web_fetch tool config (empty extras)."""

    class _AppConfig:
        def get_tool_config(self, name):
            return _FakeToolConfig({})

    monkeypatch.setattr(camoufox_tools, "get_app_config", lambda: _AppConfig())


def _make_fake_browser(html="<html><body><article>Hello world body</article></body></html>", title="Example", status=200):
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=status))
    page.wait_for_load_state = AsyncMock()
    page.title = AsyncMock(return_value=title)
    page.content = AsyncMock(return_value=html)
    page.inner_text = AsyncMock(return_value="fallback body text")
    page.close = AsyncMock()

    browser = MagicMock()
    browser.new_page = AsyncMock(return_value=page)
    return browser, page


@pytest.fixture
def fresh_manager(monkeypatch):
    """Install a fresh _BrowserManager so instance-reuse assertions are isolated."""
    mgr = browser_mod._BrowserManager()
    monkeypatch.setattr(browser_mod, "_manager", mgr)
    return mgr


class TestBrowserReuse:
    @pytest.mark.anyio
    async def test_two_fetches_launch_browser_once(self, fresh_manager, monkeypatch):
        browser, _ = _make_fake_browser()
        launch = AsyncMock(return_value=browser)
        monkeypatch.setattr(fresh_manager, "_launch", launch)

        b1 = await browser_mod.get_shared_browser()
        b2 = await browser_mod.get_shared_browser()
        assert b1 is b2 is browser
        launch.assert_awaited_once()

    @pytest.mark.anyio
    async def test_live_browser_is_not_relaunched(self, fresh_manager, monkeypatch):
        # A browser that reports connected must be reused, not relaunched.
        browser, _ = _make_fake_browser()
        browser.is_connected = MagicMock(return_value=True)
        launch = AsyncMock(return_value=browser)
        monkeypatch.setattr(fresh_manager, "_launch", launch)

        await browser_mod.get_shared_browser()
        await browser_mod.get_shared_browser()
        launch.assert_awaited_once()

    @pytest.mark.anyio
    async def test_dead_browser_is_torn_down_and_relaunched(self, fresh_manager, monkeypatch):
        # A cached browser whose subprocess has died (is_connected() -> False)
        # must be discarded and relaunched, not reused into failing fetches.
        dead_browser, _ = _make_fake_browser()
        dead_browser.is_connected = MagicMock(return_value=False)
        dead_cm = MagicMock()
        dead_cm.__aexit__ = AsyncMock()

        live_browser, _ = _make_fake_browser()
        live_browser.is_connected = MagicMock(return_value=True)

        to_launch = [(dead_browser, dead_cm), (live_browser, MagicMock(__aexit__=AsyncMock()))]

        async def _fake_launch():
            browser, cm = to_launch.pop(0)
            fresh_manager._cm = cm
            return browser

        monkeypatch.setattr(fresh_manager, "_launch", _fake_launch)

        first = await browser_mod.get_shared_browser()
        assert first is dead_browser

        second = await browser_mod.get_shared_browser()
        assert second is live_browser  # relaunched, not the dead handle
        dead_cm.__aexit__.assert_awaited_once()  # dead browser's cm was closed
        assert not to_launch  # exactly two launches happened

    @pytest.mark.anyio
    async def test_shutdown_closes_browser(self, fresh_manager):
        cm = MagicMock()
        cm.__aexit__ = AsyncMock()
        fresh_manager._cm = cm
        fresh_manager._browser = MagicMock()
        await fresh_manager.shutdown()
        cm.__aexit__.assert_awaited_once()
        assert fresh_manager._browser is None


class TestFetch:
    @pytest.mark.anyio
    async def test_successful_fetch_returns_structured_result(self, monkeypatch):
        browser, page = _make_fake_browser()
        monkeypatch.setattr(camoufox_tools, "get_shared_browser", AsyncMock(return_value=browser))

        result = await camoufox_tools.fetch_url_via_camoufox("https://example.com")
        assert "Title: Example" in result
        assert "URL: https://example.com" in result
        assert "Hello world body" in result
        page.close.assert_awaited_once()  # page always closed

    @pytest.mark.anyio
    async def test_readability_extraction_is_offloaded(self, monkeypatch):
        browser, _ = _make_fake_browser()
        monkeypatch.setattr(camoufox_tools, "get_shared_browser", AsyncMock(return_value=browser))

        called = {"to_thread": False}
        real_to_thread = camoufox_tools.asyncio.to_thread

        async def _tracking_to_thread(fn, *a, **k):
            called["to_thread"] = True
            return await real_to_thread(fn, *a, **k)

        monkeypatch.setattr(camoufox_tools.asyncio, "to_thread", _tracking_to_thread)
        await camoufox_tools.fetch_url_via_camoufox("https://example.com")
        assert called["to_thread"] is True

    @pytest.mark.anyio
    async def test_empty_readability_falls_back_to_body_text(self, monkeypatch):
        # Page with no article content → readability yields title-only → body_text used.
        browser, page = _make_fake_browser(html="<html><body></body></html>", title="Empty")
        page.inner_text = AsyncMock(return_value="the real visible text")
        monkeypatch.setattr(camoufox_tools, "get_shared_browser", AsyncMock(return_value=browser))

        result = await camoufox_tools.fetch_url_via_camoufox("https://example.com")
        assert "the real visible text" in result

    @pytest.mark.anyio
    async def test_max_content_length_caps_output(self, monkeypatch):
        long_html = "<html><body><article>" + ("x" * 9000) + "</article></body></html>"
        browser, _ = _make_fake_browser(html=long_html)
        monkeypatch.setattr(camoufox_tools, "get_shared_browser", AsyncMock(return_value=browser))

        class _AppConfig:
            def get_tool_config(self, name):
                return _FakeToolConfig({"max_content_length": 100})

        monkeypatch.setattr(camoufox_tools, "get_app_config", lambda: _AppConfig())
        result = await camoufox_tools.fetch_url_via_camoufox("https://example.com")
        # header + up to 100 chars of content
        body = result.split("\n\n", 1)[1]
        assert len(body) <= 100


class TestFailureMessages:
    @pytest.mark.anyio
    async def test_not_installed_message(self, monkeypatch):
        monkeypatch.setattr(
            camoufox_tools,
            "get_shared_browser",
            AsyncMock(side_effect=browser_mod.CamoufoxNotInstalledError("no module")),
        )
        result = await camoufox_tools.fetch_url_via_camoufox("https://example.com")
        assert result == camoufox_tools.NOT_INSTALLED_MESSAGE
        assert "uv sync --extra camoufox" in result
        assert "make fetch-browser" in result

    @pytest.mark.anyio
    async def test_browser_missing_message(self, monkeypatch):
        monkeypatch.setattr(
            camoufox_tools,
            "get_shared_browser",
            AsyncMock(side_effect=browser_mod.CamoufoxBrowserMissingError("no binaries")),
        )
        result = await camoufox_tools.fetch_url_via_camoufox("https://example.com")
        assert result == "Error: camoufox browser not installed - run make fetch-browser"

    @pytest.mark.anyio
    async def test_timeout_message_names_url(self, monkeypatch):
        browser, page = _make_fake_browser()
        page.goto = AsyncMock(side_effect=RuntimeError("Timeout 30000ms exceeded"))
        monkeypatch.setattr(camoufox_tools, "get_shared_browser", AsyncMock(return_value=browser))

        result = await camoufox_tools.fetch_url_via_camoufox("https://slow.example.com")
        assert result.startswith("Error: camoufox timed out loading https://slow.example.com")
        page.close.assert_awaited_once()  # page still closed on error


class TestBrowserMissingDetection:
    def test_missing_marker_classification(self):
        assert browser_mod._looks_like_missing_browser(FileNotFoundError("Please run `camoufox fetch` to install"))
        assert browser_mod._looks_like_missing_browser(RuntimeError("Executable doesn't exist at /x"))
        assert not browser_mod._looks_like_missing_browser(RuntimeError("some unrelated failure"))
