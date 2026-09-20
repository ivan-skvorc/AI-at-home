"""Shared headless Camoufox browser manager.

Camoufox is an optional dependency (the ``camoufox`` uv extra). It is imported
LAZILY inside functions here so this module always imports cleanly even when the
package — or its browser binaries — are absent; the failure is surfaced as an
actionable tool result instead of an ImportError at load time.

One ``AsyncCamoufox`` instance is launched on first use and reused across
requests (cold-starting a browser per fetch is far too slow). Each request gets
a fresh page that is always closed. ``shutdown()`` closes the browser cleanly at
process exit.

The browser is launched with Camoufox's anti-detection options on (see
``_stealth_launch_options``). They were previously all left at their defaults —
``AsyncCamoufox(headless=True)`` and nothing else — which ran a stealth browser
with its stealth switched off. ``geoip`` is the one that matters most behind a
VPN: without it the browser reports the host's timezone and locale while the
connection exits in another country, and that mismatch is itself a detection
signal. Every option is overridable from ``config.yaml`` and a launch that
fails with them retries bare, so a bad or unsupported option degrades the
fetch's stealth rather than removing web_fetch.
"""

from __future__ import annotations

import asyncio
import atexit
import logging

logger = logging.getLogger(__name__)


class CamoufoxNotInstalledError(RuntimeError):
    """The ``camoufox`` package is not importable."""


class CamoufoxBrowserMissingError(RuntimeError):
    """The camoufox browser binaries have not been downloaded."""


# Substrings Camoufox/Playwright use when the browser binary is missing.
_BROWSER_MISSING_MARKERS = (
    "executable doesn't exist",
    "no such file or directory",
    "camoufox fetch",
    "please run",
    "download",
    "browserfetcherror",
    "not been downloaded",
)


# Anti-detection defaults. All are Camoufox launch options; see
# `_stealth_launch_options` for why these values and how to override them.
_STEALTH_DEFAULTS: dict[str, object] = {
    # Align timezone/locale/geolocation with the *exit* IP. This is the option
    # that matters behind a VPN: the mismatch it removes is a stronger signal
    # than any fingerprint it could fix.
    "geoip": True,
    # Human-like cursor motion. Cheap, and defeats naive movement heuristics.
    "humanize": True,
    # Stop WebRTC revealing the real address behind the proxy/VPN.
    "block_webrtc": True,
}

# Options accepted from config. `proxy` is deliberately NOT read from the
# web_fetch entry's top-level `proxy:` key — that one is documented for the
# jina backend, and quietly giving it a second meaning would repoint a user's
# jina proxy at the browser.
_STEALTH_CONFIG_KEYS = ("geoip", "humanize", "block_webrtc", "locale", "proxy", "os")


def _stealth_launch_options() -> dict:
    """Camoufox launch options, from the web_fetch tool config's `camoufox:` block.

    Shape in config.yaml::

        - name: web_fetch
          backend: camoufox
          camoufox:
            geoip: true
            humanize: true
            block_webrtc: true
            # locale: en-US
            # proxy: socks5://127.0.0.1:1080

    An absent block means the defaults above. A key set to null removes that
    option entirely, so an operator can hand the decision back to Camoufox.
    Config resolution is guarded: this runs on the launch path, and a config
    error must not be the reason the browser will not start.
    """
    options = dict(_STEALTH_DEFAULTS)
    try:
        from deerflow.config import get_app_config

        config = get_app_config().get_tool_config("web_fetch")
        extras = (getattr(config, "model_extra", None) or {}) if config is not None else {}
    except Exception as exc:  # noqa: BLE001 - defaults are a working browser
        logger.debug(f"Camoufox stealth options: falling back to defaults ({exc})")
        return options

    block = extras.get("camoufox")
    if not isinstance(block, dict):
        return options

    for key in _STEALTH_CONFIG_KEYS:
        if key not in block:
            continue
        value = block[key]
        if value is None:
            options.pop(key, None)
        else:
            options[key] = value
    return options


class _BrowserManager:
    """Lazily launches and reuses a single headless Camoufox browser."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cm = None  # the AsyncCamoufox context manager
        self._browser = None

    async def get_browser(self):
        """Return the shared browser, launching it on first use.

        The launched browser is reused across requests, but a long-lived
        headless browser can die mid-session — an OOM kill, a crash, a wedged
        navigation, the subprocess reaped by the OS. A cached-but-dead handle
        would make *every* subsequent fetch fail identically until the Gateway
        restarts (the "web_fetch worked, then stopped" symptom). So the cached
        browser is liveness-checked on every call and relaunched when it has
        gone away, rather than trusted forever after the first launch.

        Raises:
            CamoufoxNotInstalledError: the package is not imported.
            CamoufoxBrowserMissingError: the browser binaries are absent.
        """
        browser = self._browser
        if browser is not None and _browser_is_alive(browser):
            return browser
        async with self._lock:
            browser = self._browser
            if browser is not None and _browser_is_alive(browser):
                return browser
            if self._browser is not None:
                # Cached browser died since the last call. Tear the dead handle
                # and its context manager down before relaunching so we don't
                # leak the old subprocess or reuse a closed Playwright object.
                await self._discard_dead_locked()
            self._browser = await self._launch()
            return self._browser

    async def _discard_dead_locked(self) -> None:
        """Drop the current (dead) browser + cm. Caller must hold ``self._lock``."""
        cm = self._cm
        self._cm = None
        self._browser = None
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001 - dead-browser cleanup is best-effort
                logger.debug(f"Camoufox dead-browser cleanup error (ignored): {exc}")

    async def _launch(self):
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as exc:
            raise CamoufoxNotInstalledError(str(exc)) from exc

        # If the browser binaries were never fetched, fail fast with the
        # actionable message rather than letting camoufox attempt a network
        # release lookup (which surfaces as an opaque HTTPError in restricted
        # environments).
        if not _camoufox_browser_present():
            raise CamoufoxBrowserMissingError("camoufox browser binaries are not installed")

        options = _stealth_launch_options()
        try:
            # AsyncCamoufox is an async context manager wrapping Playwright.
            # Enter it manually so the browser outlives a single request.
            self._cm = AsyncCamoufox(headless=True, **options)
            browser = await self._cm.__aenter__()
        except Exception as exc:  # noqa: BLE001 - classify, degrade, or re-raise
            self._cm = None
            if _looks_like_missing_browser(exc):
                raise CamoufoxBrowserMissingError(str(exc)) from exc
            if not options:
                raise
            # A stealth option Camoufox rejected (an unsupported key on an older
            # version, a geoip database that is not installed, an unreachable
            # proxy) must cost stealth, not the tool. Retry bare — which is
            # exactly how this launched before these options existed — and say
            # so loudly enough to be fixable.
            logger.warning(f"Camoufox launch failed with stealth options {sorted(options)}; retrying without them. Cause: {exc}")
            self._cm = AsyncCamoufox(headless=True)
            browser = await self._cm.__aenter__()
            logger.info("Camoufox browser launched (shared, headless, stealth options disabled)")
            return browser
        logger.info(f"Camoufox browser launched (shared, headless, stealth: {sorted(options) or 'none'})")
        return browser

    async def shutdown(self) -> None:
        """Close the shared browser. Safe to call multiple times."""
        async with self._lock:
            cm = self._cm
            self._cm = None
            self._browser = None
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
                logger.info("Camoufox browser shut down")
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                logger.debug(f"Camoufox shutdown error (ignored): {exc}")


def _camoufox_browser_present() -> bool:
    """Whether camoufox's browser binaries have been fetched.

    Checks camoufox's own install dir for the ``version.json`` it writes on
    ``camoufox fetch``. Best-effort: if the layout can't be resolved we return
    True so a genuine launch is still attempted (and classified on failure).
    """
    try:
        from camoufox import pkgman

        install_dir = getattr(pkgman, "INSTALL_DIR", None)
        if install_dir is None:
            return True
        from pathlib import Path

        return (Path(install_dir) / "version.json").exists()
    except Exception:  # noqa: BLE001 - never let the probe block a launch
        return True


def _browser_is_alive(browser) -> bool:
    """Best-effort liveness check for the shared browser.

    Playwright's ``Browser`` exposes a synchronous ``is_connected()`` that goes
    False once the underlying subprocess is gone. When the object exposes no
    such method we assume alive — the fork treats an unresolvable probe as
    "launch anyway and classify on failure" (same philosophy as
    ``_camoufox_browser_present``), never as a reason to block a fetch.
    """
    is_connected = getattr(browser, "is_connected", None)
    if not callable(is_connected):
        return True
    try:
        return bool(is_connected())
    except Exception:  # noqa: BLE001 - a throwing probe means the handle is unusable
        return False


def _looks_like_missing_browser(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _BROWSER_MISSING_MARKERS)


# Module-level singleton reused across all web_fetch calls.
_manager = _BrowserManager()


async def get_shared_browser():
    return await _manager.get_browser()


async def shutdown() -> None:
    await _manager.shutdown()


def _atexit_shutdown() -> None:
    """Best-effort browser cleanup at interpreter exit.

    The event loop is usually gone by atexit, so run the async shutdown on a
    fresh loop; if that is impossible (loop already closed / no browser), skip
    silently — the OS reaps the subprocess anyway.
    """
    if _manager._browser is None and _manager._cm is None:
        return
    try:
        asyncio.run(_manager.shutdown())
    except Exception:  # noqa: BLE001 - interpreter is shutting down
        pass


atexit.register(_atexit_shutdown)
