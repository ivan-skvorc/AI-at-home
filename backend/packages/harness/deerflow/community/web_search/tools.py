"""Pluggable web_search dispatcher.

Selects a search backend at call time and (optionally) chains a fallback:

    tools:
      - name: web_search
        group: web
        use: deerflow.community.web_search.tools:web_search_tool
        backend: searxng         # default; the self-hosted, local-first engine
        fallback: tavily         # optional: used only when the primary ERRORS
        base_url: http://localhost:8088

Backend resolution order: ``DEER_FLOW_WEB_SEARCH_BACKEND`` env var >
tool-config ``backend`` key > ``"searxng"``. SearXNG stays the default
everywhere: it is self-hosted, key-less, and keeps a query on the machine that
asked it. The fallback is opt-in and, for key-bearing providers, **silently
inactive until the key exists** (see ``_fallback_is_available``), so a stack
with no ``TAVILY_API_KEY`` behaves exactly as it did before this dispatcher.

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


def _fallback_is_available(name: str) -> bool:
    """Whether a configured fallback backend can actually run.

    A key-bearing provider named as the fallback without its key is treated as
    "not configured" rather than as an error: the user asked for a backup, the
    backup is not set up yet, and the primary's own failure is the useful thing
    to report. Returning False here keeps that failure verbatim instead of
    burying it under a credentials error from the backup.
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
    if not _fallback_is_available(fallback_name):
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
