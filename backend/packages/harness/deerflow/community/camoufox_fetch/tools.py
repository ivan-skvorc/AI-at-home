"""Camoufox web-fetch backend — local, key-less, JS-capable page fetching.

Renders a page in a shared headless Camoufox (Firefox) browser, extracts
readable markdown from the rendered DOM, and returns a structured string. Unlike
the Jina backend it needs no API key and executes page JavaScript, so it handles
JS-heavy sites. It is exposed as an importable async callable
(``fetch_url_via_camoufox``) that the web_fetch dispatcher selects via config.

Failure results are actionable strings (``"Error: ..."``) telling the agent
exactly how to fix the environment rather than a bare stack trace.
"""

from __future__ import annotations

import asyncio
import logging

from deerflow.community.camoufox_fetch.browser import (
    CamoufoxBrowserMissingError,
    CamoufoxNotInstalledError,
    get_shared_browser,
)
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

logger = logging.getLogger(__name__)

_readability_extractor = ReadabilityExtractor()

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_CONTENT_LENGTH = 4096

# Actionable, fish-compatible failure messages (no `export`/bash-isms).
NOT_INSTALLED_MESSAGE = "Error: web_fetch backend 'camoufox' is not installed. Run: cd backend; uv sync --extra camoufox — then download the browser: make fetch-browser"
BROWSER_MISSING_MESSAGE = "Error: camoufox browser not installed - run make fetch-browser"


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _tool_options() -> tuple[int, int]:
    """Return (timeout_seconds, max_content_length) from web_fetch tool config."""
    timeout = DEFAULT_TIMEOUT_SECONDS
    max_len = DEFAULT_MAX_CONTENT_LENGTH
    config = get_app_config().get_tool_config("web_fetch")
    if config is not None and config.model_extra:
        timeout = _coerce_int(config.model_extra.get("timeout"), timeout)
        max_len = _coerce_int(config.model_extra.get("max_content_length"), max_len)
    return timeout, max_len


def _extract_markdown(html: str) -> str:
    article = _readability_extractor.extract_article(html)
    return article.to_markdown()


async def fetch_url_via_camoufox(url: str) -> str:
    """Fetch and render ``url`` in headless Camoufox, returning readable text.

    Returns a structured string (title, url, content). On any failure returns an
    ``"Error: ..."``-prefixed string with an actionable next step, matching the
    web_fetch tool contract so the dispatcher can chain a fallback.
    """
    timeout_seconds, max_len = _tool_options()

    try:
        browser = await get_shared_browser()
    except CamoufoxNotInstalledError:
        return NOT_INSTALLED_MESSAGE
    except CamoufoxBrowserMissingError:
        return BROWSER_MISSING_MESSAGE
    except Exception as exc:  # noqa: BLE001 - surface launch failures actionably
        logger.warning(f"Camoufox launch failed: {exc}")
        return f"Error: camoufox browser failed to start: {type(exc).__name__}: {exc}"

    page = None
    try:
        page = await browser.new_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        # Give client-rendered pages a brief settle window for late DOM writes.
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:  # noqa: BLE001 - networkidle is best-effort
            pass

        status = response.status if response is not None else None
        title = await page.title()
        html = await page.content()

        markdown = await asyncio.to_thread(_extract_markdown, html)
        if _readability_empty(markdown, title):
            # Readability found nothing useful — fall back to rendered text.
            body_text = await page.inner_text("body")
            if body_text and body_text.strip():
                markdown = body_text

        content = (markdown or "").strip()[:max_len]
        return _format_result(url=url, title=title, status=status, content=content)
    except Exception as exc:  # noqa: BLE001 - navigation/timeout etc.
        name = type(exc).__name__
        if "timeout" in f"{name} {exc}".lower():
            return f"Error: camoufox timed out loading {url} after {timeout_seconds}s"
        return f"Error: camoufox failed to fetch {url}: {name}: {exc}"
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:  # noqa: BLE001 - best-effort
                pass


def _readability_empty(markdown: str, title: str) -> bool:
    """Whether readability produced no usable content (→ fall back to body text)."""
    if not markdown:
        return True
    stripped = markdown.strip()
    if stripped in ("", "*No content available*", f"# {title}"):
        return True
    # readabilipy's empty-document markers.
    lowered = stripped.lower()
    if "no content available" in lowered or "no content could be extracted" in lowered:
        return True
    return False


def _format_result(*, url: str, title: str, status: int | None, content: str) -> str:
    header = f"Title: {title or '(untitled)'}\nURL: {url}"
    if status is not None:
        header += f"\nStatus: {status}"
    body = content or "*No content available*"
    return f"{header}\n\n{body}"
