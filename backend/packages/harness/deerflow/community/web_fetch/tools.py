"""Pluggable web_fetch dispatcher.

Selects a fetch backend at call time and (optionally) chains a fallback:

    tools:
      - name: web_fetch
        group: web
        use: deerflow.community.web_fetch.tools:web_fetch_tool
        backend: camoufox        # or jina (default)
        fallback: jina           # optional: try this backend if the primary errors

Backend resolution order: ``DEER_FLOW_WEB_FETCH_BACKEND`` env var >
tool-config ``backend`` key > ``"jina"``. The default is ``jina`` so existing
installs behave identically.

Each backend is an importable ``async (url) -> str`` callable returning readable
text or an ``"Error: ..."``-prefixed string on failure. The dispatcher adds a
private-GitHub hint on 404s (applies to every backend), since agents otherwise
try to web-fetch private repos and get a bare 404 instead of using git.
"""

from __future__ import annotations

import logging
import os
import re

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "jina"
_ENV_BACKEND = "DEER_FLOW_WEB_FETCH_BACKEND"

_GITHUB_HOST_RE = re.compile(r"^https?://(www\.)?github\.com/", re.IGNORECASE)

PRIVATE_GITHUB_HINT = (
    "Note: if this is a private GitHub repository, web_fetch cannot authenticate to it. Use git inside the sandbox instead — `git clone https://github.com/OWNER/REPO.git` works with the configured GITHUB_TOKEN (containerized AIO sandbox)."
)


def _load_backend(name: str):
    """Return the async fetch callable for a backend name, or None if unknown."""
    if name == "jina":
        from deerflow.community.jina_ai.tools import fetch_url_via_jina

        return fetch_url_via_jina
    if name == "camoufox":
        from deerflow.community.camoufox_fetch.tools import fetch_url_via_camoufox

        return fetch_url_via_camoufox
    return None


def _resolve_backends() -> tuple[str, str | None]:
    """Return (primary_backend, fallback_backend_or_None) from env + config."""
    primary = os.getenv(_ENV_BACKEND, "").strip() or None
    fallback = None
    config = get_app_config().get_tool_config("web_fetch")
    if config is not None and config.model_extra:
        if primary is None:
            configured = config.model_extra.get("backend")
            if isinstance(configured, str) and configured.strip():
                primary = configured.strip()
        fb = config.model_extra.get("fallback")
        if isinstance(fb, str) and fb.strip():
            fallback = fb.strip()
    return (primary or DEFAULT_BACKEND), fallback


def _is_error(result: str) -> bool:
    return isinstance(result, str) and result.startswith("Error:")


def _looks_like_404(result: str) -> bool:
    lowered = result.lower()
    return "404" in lowered or "not found" in lowered


def _maybe_append_github_hint(url: str, result: str) -> str:
    if _GITHUB_HOST_RE.match(url) and _is_error(result) and _looks_like_404(result):
        return f"{result}\n\n{PRIVATE_GITHUB_HINT}"
    return result


async def dispatch_web_fetch(url: str) -> str:
    """Run the configured primary backend, then the fallback if it errored."""
    primary_name, fallback_name = _resolve_backends()

    primary = _load_backend(primary_name)
    if primary is None:
        return _maybe_append_github_hint(url, f"Error: unknown web_fetch backend '{primary_name}' (expected 'jina' or 'camoufox').")

    primary_result = await primary(url)
    if not _is_error(primary_result):
        return primary_result

    logger.warning(f"web_fetch backend '{primary_name}' failed for {url}: {primary_result}")

    if fallback_name and fallback_name != primary_name:
        fallback = _load_backend(fallback_name)
        if fallback is None:
            combined = f"{primary_result}\n(also: unknown fallback backend '{fallback_name}')"
            return _maybe_append_github_hint(url, combined)
        fallback_result = await fallback(url)
        if not _is_error(fallback_result):
            return fallback_result
        combined = f"Error: web_fetch failed on both backends.\nPrimary ({primary_name}): {primary_result}\nFallback ({fallback_name}): {fallback_result}"
        return _maybe_append_github_hint(url, combined)

    return _maybe_append_github_hint(url, primary_result)


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    return await dispatch_web_fetch(url)
