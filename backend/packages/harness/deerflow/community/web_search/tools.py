"""Pluggable web_search dispatcher.

Selects a search backend at call time and (optionally) chains a fallback:

    tools:
      - name: web_search
        group: web
        use: deerflow.community.web_search.tools:web_search_tool
        backend: tavily          # shipped default: survives a blocked egress
        fallback: searxng        # used when Tavily errors, is rate-limited, or has no key
        base_url: http://localhost:8088

Backend resolution order: ``DEER_FLOW_WEB_SEARCH_BACKEND`` env var >
tool-config ``backend`` key > ``"searxng"``. The *code* default stays
``searxng`` so a config predating this dispatcher keeps working untouched; the
shipped ``config.example.yaml`` selects ``tavily`` explicitly, because a
scraping engine inherits the host IP's reputation and a VPN or datacenter exit
loses every consumer engine at once.

Availability is checked in **both** slots (``_backend_is_available``). A
key-bearing primary with no key is not an error: the fallback is promoted and
run as the only backend, so a fresh clone with no ``TAVILY_API_KEY`` searches
through SearXNG and never reports a credentials failure.

Each backend is an importable ``async (query, time_range) -> str`` callable
returning a JSON array of ``{title, url, snippet}``. A backend signals failure
by **raising**, not by returning an error string — which is what lets the
dispatcher tell a real failure from a legitimately empty result set.

**The invariant that matters here** (FORK.md §31): an empty result list is a
*successful* search that matched nothing, and must NOT trigger the fallback. Only
an exception does. Falling back on empty would spend a metered third-party
credit on every genuine no-match query and would silently route those queries
off the machine — the two things the local-first default exists to prevent.
"""

from __future__ import annotations

import json
import logging
import os

from langchain.tools import tool

from deerflow.community.search_time_range import SearchTimeRange
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "searxng"
_ENV_BACKEND = "DEER_FLOW_WEB_SEARCH_BACKEND"


def _load_backend(name: str):
    """Return the async search callable for a backend name, or None if unknown.

    Imports are lazy and per-branch: a provider's SDK (``tavily-python``) must
    not be import-time mandatory for a stack that only ever runs SearXNG. May
    raise ImportError when the named provider's SDK is absent — callers on the
    fallback path go through ``_load_backend_or_none`` instead, so a missing
    backup degrades to the primary's error rather than replacing it.
    """
    if name == "searxng":
        from deerflow.community.searxng.tools import search_via_searxng

        return search_via_searxng
    if name == "tavily":
        from deerflow.community.tavily.tools import search_via_tavily

        return search_via_tavily
    return None


def _load_backend_or_none(name: str):
    """``_load_backend`` that answers None instead of raising.

    The fallback is resolved *outside* the dispatcher's try block, so an
    ImportError here (a provider SDK trimmed from the install, or moved to an
    optional extra) would escape the tool as a traceback and replace the
    primary's real failure with a crash. A backup that cannot load is simply a
    backup that is not there.
    """
    try:
        return _load_backend(name)
    except Exception as exc:  # noqa: BLE001 - an unloadable backup is "absent", not fatal
        logger.warning(f"web_search backend '{name}' could not be loaded: {exc}")
        return None


def _backend_is_available(name: str) -> bool:
    """Whether a backend can actually run, in either slot.

    Used for the primary and the fallback, because "not set up" means different
    things in each and both need handling:

    * as the **fallback** — the user asked for a backup and has not configured
      it yet, so it is skipped and the *primary's* failure is reported verbatim
      rather than buried under a credentials error from the backup;
    * as the **primary** — the stack is configured for a provider whose key is
      absent, so the dispatcher uses the fallback as the effective primary
      instead of making every search fail on a missing key first. That is the
      "Tavily by default, SearXNG when Tavily is not available" shape: a fresh
      clone with no key searches locally and never errors.

    A provider with no credential requirement is always available.
    """
    if name == "tavily":
        try:
            from deerflow.community.tavily.tools import tavily_api_key_present

            return tavily_api_key_present()
        except Exception as exc:  # noqa: BLE001 - see _load_backend_or_none
            logger.warning(f"web_search could not check the '{name}' fallback's key: {exc}")
            return False
    return True


def _resolve_backends() -> tuple[str, str | None]:
    """Return (primary_backend, fallback_backend_or_None) from env + config."""
    primary = os.getenv(_ENV_BACKEND, "").strip() or None
    fallback = None
    config = get_app_config().get_tool_config("web_search")
    extras = getattr(config, "model_extra", None) if config is not None else None
    if extras:
        if primary is None:
            configured = extras.get("backend")
            if isinstance(configured, str) and configured.strip():
                primary = configured.strip()
        fb = extras.get("fallback")
        if isinstance(fb, str) and fb.strip():
            fallback = fb.strip()
    return (primary or DEFAULT_BACKEND), fallback


def _error_payload(query: str, message: str) -> str:
    """The failure shape callers already parse (matches the searxng provider)."""
    return json.dumps({"error": message, "query": query}, ensure_ascii=False)


async def dispatch_web_search(query: str, time_range: SearchTimeRange | None = None) -> str:
    """Run the configured primary backend, then the fallback if it RAISED.

    An empty-but-successful result is returned as-is; see the module docstring.
    """
    primary_name, fallback_name = _resolve_backends()

    # A primary that is configured but not set up (a key-bearing provider with
    # no key) is not an error when a usable fallback exists: promote the
    # fallback and run it as the only backend. Attempting the primary first
    # would make every search pay a guaranteed failure, and reporting one would
    # break a stack that is working exactly as configured.
    if fallback_name and fallback_name != primary_name and not _backend_is_available(primary_name):
        if _backend_is_available(fallback_name):
            logger.info(f"web_search primary '{primary_name}' is not configured; using '{fallback_name}' instead.")
            primary_name, fallback_name = fallback_name, None
        else:
            return _error_payload(
                query,
                f"neither web_search backend is configured: '{primary_name}' has no API key and fallback '{fallback_name}' is unavailable.",
            )

    primary = _load_backend_or_none(primary_name)
    if primary is None:
        return _error_payload(query, f"unknown or unloadable web_search backend '{primary_name}' (expected 'searxng' or 'tavily').")

    try:
        return await primary(query, time_range)
    except Exception as primary_error:  # noqa: BLE001 - classified below, then reported
        logger.warning(f"web_search backend '{primary_name}' failed for {query!r}: {primary_error}")
        primary_message = str(primary_error)

    if not fallback_name or fallback_name == primary_name:
        return _error_payload(query, primary_message)

    # Availability first, then the import: a keyless backup is the common case on
    # a blocked connection, and there is no reason to pull in its SDK to learn
    # that it is not set up.
    if not _backend_is_available(fallback_name):
        logger.info(f"web_search fallback '{fallback_name}' is configured but not usable (no API key); reporting the primary failure.")
        return _error_payload(query, primary_message)

    fallback = _load_backend_or_none(fallback_name)
    if fallback is None:
        return _error_payload(query, f"{primary_message} (also: unknown or unloadable fallback backend '{fallback_name}')")

    logger.info(f"web_search falling back to '{fallback_name}' after '{primary_name}' failed.")
    try:
        return await fallback(query, time_range)
    except Exception as fallback_error:  # noqa: BLE001 - both failed; report both
        logger.error(f"web_search fallback '{fallback_name}' also failed for {query!r}: {fallback_error}")
        return _error_payload(
            query,
            f"web_search failed on both backends. Primary ({primary_name}): {primary_message} | Fallback ({fallback_name}): {fallback_error}",
        )


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, time_range: SearchTimeRange | None = None) -> str:
    """Search the web.

    Args:
        query: The query to search for.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    return await dispatch_web_search(query, time_range)
