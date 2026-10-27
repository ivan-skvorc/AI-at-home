"""Async transport for xAI's public API on the connected Grok subscription (fork feature).

Every request resolves the token for *one* operator-enabled feature through
:func:`deerflow.models.subscriptions.grok_api_access` — the same lock and
refresh rotation Grok chat uses — and drops it when the request ends. Nothing
here stores a token, retries a plan-quota refusal, or copies a response body
into an error: bodies can echo prompts, and prompts are the user's.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from urllib.parse import urlsplit

import httpx

XAI_API = "https://api.x.ai/v1"
USER_AGENT = "DeerFlow/2 grok-features"
# Base64 images make JSON bodies large; four 2K images fit well inside this.
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_MEDIA_BYTES = 200 * 1024 * 1024


class XaiError(Exception):
    """A sanitized failure, safe to show the model and the user."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def _refusal(status: int, path: str) -> XaiError:
    if status in (401, 403):
        return XaiError(f"Grok refused {path} for the connected plan (HTTP {status}); this feature may not be included. Check Settings → Models → Subscriptions.", status=status)
    if status == 429:
        return XaiError("Grok's plan limit for this feature has been reached. DeerFlow does not retry plan-quota refusals; try again later.", status=status)
    return XaiError(f"Grok returned HTTP {status} for {path}.", status=status)


async def resolve_access(feature: str) -> tuple[str, list[str]]:
    """Token plus listed model IDs for *feature*, checked against the switch now."""
    from deerflow.models.subscriptions import SubscriptionError, grok_api_access

    try:
        return await asyncio.to_thread(grok_api_access, feature)
    except SubscriptionError as exc:
        raise XaiError(str(exc)) from None


def pick_model(configured: object, listed: list[str], default: str) -> str:
    """Operator's choice, else the documented default if listed, else the first listed."""
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    if default in listed or not listed:
        return default
    return listed[0]


def _allowed_download_host(host: str, allowed: tuple[str, ...]) -> bool:
    host = host.rstrip(".").lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in allowed)


class XaiClient:
    """One feature's view of the API. Construct per tool call; it holds no secrets."""

    def __init__(self, feature: str, *, timeout: float = 120.0, transport: httpx.AsyncBaseTransport | None = None):
        self.feature = feature
        self.timeout = timeout
        self._transport = transport

    async def _send(self, method: str, path: str, *, max_bytes: int, **kwargs) -> tuple[bytes, str]:
        token, _ = await resolve_access(self.feature)
        headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False, transport=self._transport) as client:
                async with client.stream(method, f"{XAI_API}{path}", headers=headers, **kwargs) as response:
                    if not response.is_success:
                        raise _refusal(response.status_code, path)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise XaiError(f"Grok's response to {path} was larger than {max_bytes} bytes.")
                    return bytes(body), response.headers.get("content-type", "")
        except httpx.TimeoutException:
            raise XaiError(f"Grok did not answer {path} within {self.timeout:.0f} seconds.") from None
        except httpx.HTTPError:
            raise XaiError(f"Grok could not be reached for {path}.") from None

    async def request_json(self, method: str, path: str, **kwargs) -> dict:
        body, _ = await self._send(method, path, max_bytes=MAX_JSON_BYTES, **kwargs)
        try:
            payload = json.loads(body)
        except ValueError:
            raise XaiError(f"Grok returned an unreadable response for {path}.") from None
        if not isinstance(payload, dict):
            raise XaiError(f"Grok returned an unexpected response for {path}.")
        return payload

    async def request_bytes(self, method: str, path: str, *, max_bytes: int, **kwargs) -> tuple[bytes, str]:
        return await self._send(method, path, max_bytes=max_bytes, **kwargs)

    async def download(self, url: object, *, allowed_hosts: tuple[str, ...], max_bytes: int = MAX_MEDIA_BYTES) -> bytes:
        """Fetch a generated file from xAI's temporary URL, without credentials.

        The URL comes from xAI's own response, but it is still pinned: HTTPS,
        a host under ``allowed_hosts`` (``x.ai`` by default, extendable per
        tool entry), a public address, and no redirects. The token is never
        sent here — a media URL is a bearer link of its own.
        """
        from deerflow.community.url_safety import validate_public_http_url

        if not isinstance(url, str) or len(url) > 4096:
            raise XaiError("Grok returned no usable file URL.")
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        # Source selection, not configuration: a link off the pinned hosts is
        # declined (userinfo rules belong to community/provider_credentials).
        if parsed.scheme != "https" or not _allowed_download_host(host, allowed_hosts):
            raise XaiError(f"Grok returned a file on an unexpected host ({host or 'none'}); add it to this tool's download_hosts in config.yaml if it is xAI's.")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            raise XaiError("Grok returned a file URL with a bare IP address; refusing to fetch it.")
        problem = await asyncio.to_thread(validate_public_http_url, url, action="download from")
        if problem:
            raise XaiError(problem.removeprefix("Error: "))
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False, transport=self._transport) as client:
                async with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as response:
                    if not response.is_success:
                        raise XaiError(f"Downloading Grok's file failed (HTTP {response.status_code}); its temporary link may have expired.")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise XaiError(f"Grok's file was larger than {max_bytes} bytes.")
                    return bytes(body)
        except httpx.TimeoutException:
            raise XaiError("Downloading Grok's file timed out.") from None
        except httpx.HTTPError:
            raise XaiError("Grok's file could not be downloaded.") from None
