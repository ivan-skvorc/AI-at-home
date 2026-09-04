"""Tests for SearXNG community tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.searxng import tools
from deerflow.community.searxng.searxng_client import SearxngClient, SearxngEnginesUnavailableError


class AsyncMock(MagicMock):
    """Mock that supports async call."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.mark.asyncio
class TestSearxngClient:
    """Tests for the SearxngClient class."""

    async def test_search_success(self):
        """Search returns normalized results."""
        results_data = {
            "results": [
                {"title": "Page 1", "url": "https://example.com/1", "content": "Snippet 1"},
                {"title": "Page 2", "url": "https://example.com/2", "content": "Snippet 2"},
            ]
        }

        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = results_data
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=5)

            assert len(result) == 2
            assert result[0]["title"] == "Page 1"
            assert result[1]["url"] == "https://example.com/2"

    async def test_search_empty_results(self):
        """Search returns empty list when no results."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("empty query")
            assert result == []

    async def test_search_http_error(self):
        """Search raises on HTTP error."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            import httpx

            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=MagicMock())
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(httpx.HTTPStatusError):
                await client.search("blocked query")

    async def test_search_request_error(self):
        """Search raises on request error."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            import httpx

            mock_ctx.get = AsyncMock(side_effect=httpx.RequestError("Connection refused"))

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(httpx.RequestError):
                await client.search("unreachable query")

    async def test_search_with_categories(self):
        """Search passes categories parameter."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("test", categories=["news", "science"])

            call_kwargs = mock_ctx.get.call_args.kwargs
            assert call_kwargs["params"]["categories"] == "news,science"

    async def test_search_with_time_range(self):
        """Search passes a native relative time range."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("latest release", time_range="month")

            params = mock_ctx.get.call_args.kwargs["params"]
            assert params["time_range"] == "month"

    async def test_search_without_time_range_omits_parameter(self):
        """The default request shape remains unchanged."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("stable documentation")

            params = mock_ctx.get.call_args.kwargs["params"]
            assert "time_range" not in params


class TestSearxngBaseUrlResolution:
    """Tests for base_url resolution in _get_searxng_client.

    Precedence: DEER_FLOW_SEARXNG_BASE_URL env var > config base_url > default.
    The env override lets the Docker stack point the same config.yaml at the
    in-network service (http://searxng:8080) while host-run dev keeps
    http://localhost:8088 (mirrors DEER_FLOW_CHANNELS_* URL overrides).
    """

    def test_default_base_url(self, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_SEARXNG_BASE_URL", raising=False)
        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            client = tools._get_searxng_client()
        assert client.base_url == "http://localhost:8088"

    def test_config_base_url(self, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_SEARXNG_BASE_URL", raising=False)
        with patch("deerflow.community.searxng.tools._get_tool_config", return_value={"base_url": "http://my-searxng:9999"}):
            client = tools._get_searxng_client()
        assert client.base_url == "http://my-searxng:9999"

    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_SEARXNG_BASE_URL", "http://searxng:8080")
        with patch("deerflow.community.searxng.tools._get_tool_config", return_value={"base_url": "http://localhost:8088"}):
            client = tools._get_searxng_client()
        assert client.base_url == "http://searxng:8080"

    def test_env_used_without_config(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_SEARXNG_BASE_URL", "http://searxng:8080")
        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            client = tools._get_searxng_client()
        assert client.base_url == "http://searxng:8080"

    def test_blank_env_ignored(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_SEARXNG_BASE_URL", "   ")
        with patch("deerflow.community.searxng.tools._get_tool_config", return_value={"base_url": "http://my-searxng:9999"}):
            client = tools._get_searxng_client()
        assert client.base_url == "http://my-searxng:9999"


@pytest.mark.asyncio
class TestSearxngTools:
    """Tests for the SearXNG tool functions."""

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_success(self, mock_get_client):
        """web_search_tool returns JSON results."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(
            return_value=[
                {"title": "Result 1", "url": "https://example.com/1", "content": "Desc 1"},
            ]
        )
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Result 1"

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_error(self, mock_get_client):
        """web_search_tool handles errors gracefully."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(side_effect=Exception("API error"))
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert "error" in data

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_with_max_results(self, mock_get_client):
        """web_search_tool respects max_results config."""
        mock_client = MagicMock()
        # Return 10 results; the tool should slice to max_results=3
        mock_client.search = AsyncMock(return_value=[{"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Desc {i}"} for i in range(10)])
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value={"max_results": "3"}):
            await tools.web_search_tool.ainvoke("test query")

        # Verify that search was called with max_results=3 (coerced from string)
        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["max_results"] == 3

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_forwards_time_range(self, mock_get_client):
        """web_search_tool forwards the requested relative time range."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(return_value=[])
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            await tools.web_search_tool.ainvoke({"query": "latest release", "time_range": "week"})

        mock_client.search.assert_called_once_with("latest release", max_results=5, time_range="week")


@pytest.mark.asyncio
class TestUnresponsiveEngines:
    """SearXNG answers 200 with an empty `results` when its engines are blocked.

    It names the failures in `unresponsive_engines` and benches each blocked
    engine for ~180s. Discarding that field turns a total engine outage into a
    successful empty search, so the agent immediately re-queries — which
    re-triggers the block and extends the suspension. The observable symptom is
    a search tool that works for the first few calls of a run and then returns
    nothing for the rest.
    """

    @staticmethod
    def _patched(payload):
        patcher = patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient")
        mock_cls = patcher.start()
        mock_ctx = MagicMock()
        mock_cls.return_value.__aenter__.return_value = mock_ctx
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        mock_ctx.get = AsyncMock(return_value=mock_resp)
        return patcher

    async def test_all_engines_blocked_raises_rather_than_returning_empty(self):
        patcher = self._patched(
            {
                "results": [],
                "unresponsive_engines": [
                    ["brave", "too many requests"],
                    ["duckduckgo", "access denied"],
                    ["startpage", "CAPTCHA"],
                ],
            }
        )
        try:
            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(SearxngEnginesUnavailableError) as excinfo:
                await client.search("blocked query")
            message = str(excinfo.value)
            assert "brave" in message
            assert "duckduckgo" in message
            assert "too many requests" in message
        finally:
            patcher.stop()

    async def test_a_genuinely_empty_result_set_is_still_a_success(self):
        # No engine failed; the query simply matched nothing. This must stay an
        # empty success, not an error.
        patcher = self._patched({"results": [], "unresponsive_engines": []})
        try:
            client = SearxngClient(base_url="http://searxng:8080")
            assert await client.search("nothing matches this") == []
        finally:
            patcher.stop()

    async def test_partial_engine_failure_with_results_is_not_an_error(self):
        # Degraded but usable: some engines answered. Returning what we have
        # beats failing the whole call.
        patcher = self._patched(
            {
                "results": [{"title": "Page", "url": "https://example.com", "content": "Snippet"}],
                "unresponsive_engines": [["wikipedia", "timeout"]],
            }
        )
        try:
            client = SearxngClient(base_url="http://searxng:8080")
            results = await client.search("partial")
            assert len(results) == 1
        finally:
            patcher.stop()

    async def test_malformed_unresponsive_engines_does_not_crash_the_client(self):
        # The field is upstream-shaped; never let parsing it become the failure.
        patcher = self._patched({"results": [], "unresponsive_engines": "brave"})
        try:
            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(SearxngEnginesUnavailableError):
                await client.search("odd payload")
        finally:
            patcher.stop()

    async def test_the_tool_reports_the_engine_failure_as_an_error(self):
        # tools.web_search_tool serializes exceptions into {"error": ...}, which
        # is what actually reaches the agent.
        with patch.object(tools, "_get_tool_config", return_value=None), patch.object(tools, "_get_searxng_client") as get_client:
            client = MagicMock()
            client.search = AsyncMock(side_effect=SearxngEnginesUnavailableError("every engine is suspended: brave (too many requests)"))
            get_client.return_value = client
            payload = json.loads(await tools.web_search_tool.ainvoke({"query": "blocked"}))
        assert "error" in payload
        assert "brave" in payload["error"]
