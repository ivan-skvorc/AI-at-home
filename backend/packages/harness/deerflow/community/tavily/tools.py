import json
import os

from langchain.tools import tool
from tavily import AsyncTavilyClient

from deerflow.community.search_time_range import SearchTimeRange
from deerflow.config import get_app_config

# Tavily's own SDK reads this when constructed without an explicit key. It is
# named here as well so the web_search dispatcher can ask "is the backup set
# up?" without constructing a client (which raises when the key is missing).
API_KEY_ENV_VAR = "TAVILY_API_KEY"


def _web_search_extras() -> dict:
    """The web_search tool-config extras, or {} when absent.

    ``model_extra`` is None for an entry with no extra keys, so it is coerced
    here: when Tavily runs as a *fallback*, the configured web_search entry
    belongs to the primary provider and carries no Tavily keys at all.
    """
    try:
        config = get_app_config().get_tool_config("web_search")
    except Exception:  # noqa: BLE001 - see below
        # The web_search dispatcher consults this to decide whether the Tavily
        # fallback is usable, on a path that is NOT inside its try block. A
        # config-resolution error must therefore degrade to "no config keys"
        # and let the env var answer, rather than take down web_search itself.
        return {}
    if config is None:
        return {}
    return getattr(config, "model_extra", None) or {}


def resolve_tavily_api_key() -> str | None:
    """Tavily's API key from tool config, else the environment, else None.

    Config wins so an operator can point one stack at a specific key, but the
    ordinary path is the env var loaded from the repo-root ``.env``.
    """
    extras = _web_search_extras()
    for key in ("api_key", "fallback_api_key"):
        value = extras.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    env_value = os.getenv(API_KEY_ENV_VAR, "").strip()
    return env_value or None


def tavily_api_key_present() -> bool:
    """Whether Tavily is actually usable. Used to gate the dispatcher fallback."""
    return resolve_tavily_api_key() is not None


def _get_tavily_client(tool_name: str = "web_search") -> AsyncTavilyClient:
    """Tavily client for ``tool_name``: its own key, else the environment.

    Each tool carries its own credential so ``web_fetch`` can be pointed at a
    separate key from ``web_search``. The fork adds only the env-var tail, so a
    stack that sets ``TAVILY_API_KEY`` in the repo-root ``.env`` and configures
    no key at all still works. Deliberately *not* the shared
    ``resolve_tavily_api_key`` chain: that reads the ``web_search`` entry, which
    belongs to whichever provider is configured there — borrowing it here would
    hand Serper's key to Tavily.
    """
    api_key = None
    config = get_app_config().get_tool_config(tool_name)
    if config is not None and "api_key" in config.model_extra:
        value = config.model_extra.get("api_key")
        if isinstance(value, str) and value.strip():
            api_key = value.strip()
    return AsyncTavilyClient(api_key=api_key or os.getenv(API_KEY_ENV_VAR, "").strip() or None)


async def _search_tavily(query: str, time_range: SearchTimeRange | None = None) -> str:
    """Tavily search returning a JSON array of {title, url, snippet}."""
    extras = _web_search_extras()
    max_results = extras.get("max_results", 5)

    search_kwargs: dict[str, object] = {"max_results": max_results}
    for key in ("include_domains", "exclude_domains"):
        if key in extras:
            search_kwargs[key] = extras[key]
    if search_kwargs.get("include_domains"):
        search_kwargs["include_domains_mode"] = "filter"
    if time_range is not None:
        search_kwargs["time_range"] = time_range
    client = _get_tavily_client()
    try:
        res = await client.search(query, **search_kwargs)
    finally:
        await client.close()
    normalized_results = [
        {
            "title": result["title"],
            "url": result["url"],
            "snippet": result["content"],
        }
        for result in res["results"]
    ]
    return json.dumps(normalized_results, indent=2, ensure_ascii=False)


async def search_via_tavily(query: str, time_range: SearchTimeRange | None = None) -> str:
    """Tavily search for the web_search dispatcher.

    Native async since the SDK moved to ``AsyncTavilyClient``: nothing here
    blocks the event loop, so it is awaited directly rather than offloaded.
    """
    return await _search_tavily(query, time_range)


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, time_range: SearchTimeRange | None = None) -> str:
    """Search the web.

    Args:
        query: The query to search for.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    return await _search_tavily(query, time_range)


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
    client = _get_tavily_client("web_fetch")
    try:
        res = await client.extract([url])
    finally:
        await client.close()
    if "failed_results" in res and len(res["failed_results"]) > 0:
        return f"Error: {res['failed_results'][0]['error']}"
    elif "results" in res and len(res["results"]) > 0:
        result = res["results"][0]
        # Extract results guarantee a URL and content, but not a page title.
        title = result.get("title") or result.get("url") or url
        return f"# {title}\n\n{result['raw_content'][:4096]}"
    else:
        return "Error: No results found"
