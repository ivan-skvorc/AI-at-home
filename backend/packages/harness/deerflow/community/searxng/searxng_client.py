import logging
from typing import Any

import httpx

from deerflow.community.search_time_range import SearchTimeRange

logger = logging.getLogger(__name__)


class SearxngEnginesUnavailableError(RuntimeError):
    """Every engine that could have answered was blocked, suspended or timed out.

    SearXNG reports this as HTTP 200 with an empty ``results`` array and the
    failures named in ``unresponsive_engines``; it then benches each blocked
    engine for ~180 seconds. Reporting that as a successful empty search makes
    the agent re-query immediately, which re-triggers the block and extends the
    suspension — a search tool that works for the first few calls of a run and
    then returns nothing for the rest. Raising instead lets the agent back off
    or change strategy.
    """


def _format_unresponsive(unresponsive: Any) -> str:
    """Render SearXNG's ``unresponsive_engines`` for a human and an agent.

    The field is upstream-shaped (normally a list of ``[engine, reason]`` pairs),
    so every branch here tolerates a shape it did not expect: failing to parse a
    diagnostic must never become the failure being diagnosed.
    """
    if not isinstance(unresponsive, (list, tuple)):
        return str(unresponsive)
    rendered = []
    for entry in unresponsive:
        if isinstance(entry, (list, tuple)) and entry:
            name = str(entry[0])
            reason = str(entry[1]) if len(entry) > 1 else "unavailable"
            rendered.append(f"{name} ({reason})")
        else:
            rendered.append(str(entry))
    return ", ".join(rendered)


class SearxngClient:
    """Client for SearXNG meta search engine API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def search(
        self,
        query: str,
        max_results: int = 5,
        categories: list[str] | None = None,
        time_range: SearchTimeRange | None = None,
    ) -> list[dict[str, Any]]:
        """Search the web using SearXNG.

        Args:
            query: The search query.
            max_results: Maximum number of results to return.
            categories: Search categories to use.
            time_range: Optional relative publication/update window.

        Returns:
            List of search result dictionaries.
        """
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": "auto",
            "pageno": 1,
        }
        if max_results:
            params["limit"] = max_results
        if categories:
            params["categories"] = ",".join(categories)
        if time_range is not None:
            params["time_range"] = time_range

        logger.debug(f"Searching SearXNG at {self.base_url} with query: {query}")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base_url}/search",
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; DeerFlow/1.0)",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                # An empty result set is ambiguous: either nothing matched, or
                # every engine was blocked. Only `unresponsive_engines` tells
                # the two apart, and only the second one is an error.
                unresponsive = data.get("unresponsive_engines")
                if not results and unresponsive:
                    detail = _format_unresponsive(unresponsive)
                    logger.warning(f"SearXNG returned no results; every engine was unavailable: {detail}")
                    raise SearxngEnginesUnavailableError(
                        f"SearXNG returned no results because its engines were unavailable: {detail}. "
                        f"A blocked engine is suspended for about 180 seconds, so retrying the same query "
                        f"immediately will keep failing and can extend the suspension — wait, rephrase for a "
                        f"different engine mix, or use another tool."
                    )
                return results[:max_results] if max_results else results
        except SearxngEnginesUnavailableError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"SearXNG search returned error status: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"SearXNG search request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred during SearXNG search: {e}")
            raise
