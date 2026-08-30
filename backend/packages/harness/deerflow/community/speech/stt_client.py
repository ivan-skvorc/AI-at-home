"""HTTP client for a local speech-to-text service.

One call: ``POST /v1/audio/transcriptions`` with multipart audio, the OpenAI
transcription shape. That shape is the reason no engine is named anywhere in
this module — faster-whisper-server, speaches, whisper.cpp's ``server`` and
LocalAI all speak it, so the operator picks the backend and DeerFlow stays out
of the argument.

Everything here is transport. Endpoint screening lives in :func:`build_client`
and the caller-facing contract in ``app.gateway.routers.voice``, so this module
can be exercised against a fake transport.

Two properties are load-bearing and a refactor must not "simplify" them away:

1. **The size cap is enforced before the request, not after.** The audio
   arrives from a browser, and handing an unbounded body to a transcription
   service turns a composer button into a way to pin the machine's CPU.
2. **Failures name the service, never the audio.** A transcript is speech; an
   error string that quotes what the service echoed back can put a fragment of
   that speech into a log. Errors here carry status codes and service URLs.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8000"
# Deployment-level override, mirroring DEER_FLOW_COMFYUI_BASE_URL: the same
# config.yaml then works host-run and inside the Docker stack. Deliberately
# free of KEY/TOKEN/SECRET so `env_policy.build_sandbox_env` does not scrub it
# from skill subprocesses.
BASE_URL_ENV_VAR = "DEER_FLOW_STT_BASE_URL"

TRANSCRIPTION_PATH = "/v1/audio/transcriptions"

# `localhost` is not an IP literal, so it never reaches the address check.
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}

# Tailscale's address space. `ipaddress` does not classify CGNAT as private
# (100.64.0.0/10 is neither `is_private` nor `is_global` on CPython), so the
# shared `is_blocked_address` predicate reports a tailnet peer as a public
# host. For this fork that is exactly backwards: FORK.md's whole access story
# is "reach the stack over Tailscale", so an STT service on a tailnet address
# is a machine the household owns, reached over an encrypted private network.
#
# This lives here rather than in `url_safety.is_blocked_address` on purpose:
# that predicate decides what the *web* tools may fetch, and widening it would
# newly refuse tailnet URLs to every one of them.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class SpeechToTextError(RuntimeError):
    """A transcription call failed in a way the caller should be told about."""


class SpeechToTextUnavailableError(SpeechToTextError):
    """The service could not be reached at all."""


class SpeechToTextClient:
    """Transcribe recorded audio through an OpenAI-compatible service."""

    def __init__(self, base_url: str, *, model: str, request_timeout: float = 60.0, language: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._request_timeout = request_timeout
        self._language = language
        self._transport = transport

    @property
    def base_url(self) -> str:
        return self._base_url

    async def transcribe(self, audio: bytes, *, filename: str = "speech.webm", content_type: str = "audio/webm", language: str | None = None) -> str:
        """Return the transcript for ``audio``, or raise a ``SpeechToTextError``."""
        if not audio:
            raise SpeechToTextError("No audio was recorded.")

        data: dict[str, str] = {"model": self._model}
        resolved_language = language or self._language
        if resolved_language:
            data["language"] = resolved_language

        url = f"{self._base_url}{TRANSCRIPTION_PATH}"
        try:
            async with httpx.AsyncClient(timeout=self._request_timeout, transport=self._transport) as client:
                response = await client.post(url, data=data, files={"file": (filename, audio, content_type)})
        except httpx.HTTPError as exc:
            # The exception's own text can carry the request body on some
            # transports; name the endpoint and the failure class instead.
            raise SpeechToTextUnavailableError(f"Could not reach the speech-to-text service at {self._base_url} ({type(exc).__name__}).") from exc

        if response.status_code >= 400:
            raise SpeechToTextError(f"The speech-to-text service at {self._base_url} returned HTTP {response.status_code}.")

        return _read_transcript(response, self._base_url)


def _read_transcript(response: httpx.Response, base_url: str) -> str:
    """Pull the transcript out of a response, tolerating both reply shapes.

    The OpenAI shape is ``{"text": "..."}``, but several local servers honour
    ``response_format=text`` by default and return a bare string body. Accept
    both rather than making the operator match a format flag DeerFlow never
    sends.
    """
    payload: Any
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()

    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text.strip()
        raise SpeechToTextError(f"The speech-to-text service at {base_url} returned JSON without a 'text' field.")
    if isinstance(payload, str):
        return payload.strip()
    raise SpeechToTextError(f"The speech-to-text service at {base_url} returned an unexpected response shape.")


def is_local_endpoint(base_url: str) -> bool:
    """Whether ``base_url`` resolves to this machine or its private network.

    The shared SSRF guard answers the opposite question — it stops a server-side
    tool from reaching *into* private space. This feature's risk runs the other
    way: an STT endpoint on a public host sends the household's audio off the
    machine, which is exactly what the microphone button was changed to stop.
    Nothing here refuses such an endpoint (a VPS you own is a legitimate, if
    unusual, choice); it is reported so the operator is warned and the composer
    can label the tier honestly.

    Unresolvable hosts are reported as **not** local: the claim being made is
    "this audio stays here", and a name that cannot be resolved does not
    support it.
    """
    from deerflow.community.url_safety import is_blocked_address, resolve_host_addresses

    hostname = urlparse(base_url).hostname
    if not hostname:
        return False

    normalized = hostname.strip().rstrip(".").lower()
    if normalized in _LOCAL_HOSTNAMES:
        return True

    try:
        addresses = [ipaddress.ip_address(normalized)]
    except ValueError:
        addresses = resolve_host_addresses(normalized)

    if not addresses:
        return False
    return all(_is_local_address(address, is_blocked_address) for address in addresses)


def _is_local_address(address: ipaddress._BaseAddress, is_blocked_address) -> bool:
    if address.version == 4 and address in _CGNAT_NETWORK:
        return True
    return bool(is_blocked_address(address))


def resolve_base_url(base_url: str) -> str:
    """Config base_url unless the deployment env var overrides it."""
    override = os.getenv(BASE_URL_ENV_VAR, "").strip()
    if override:
        return override
    return base_url


def build_client(config: Any, *, transport: httpx.AsyncBaseTransport | None = None) -> SpeechToTextClient:
    """Screen the endpoint, then build a client for it.

    ``config`` is a ``SpeechToTextConfig``; it is typed loosely so this module
    stays importable without pulling the config package into transport tests.
    """
    from deerflow.community.url_safety import validate_public_http_url

    base_url = resolve_base_url(config.base_url)
    guard = validate_public_http_url(
        base_url,
        allow_private_addresses=config.allow_private_addresses,
        action="reach",
    )
    if guard:
        raise SpeechToTextError(f"{guard} (voice.stt.base_url={base_url}). Set voice.stt.allow_private_addresses: true if this really is your own machine.")
    if not is_local_endpoint(base_url):
        logger.warning(
            "voice: the speech-to-text endpoint %s is not on this machine or its private network — recorded audio will leave this host. Point voice.stt.base_url at a local service if that is not what you intended.",
            base_url,
        )
    return SpeechToTextClient(
        base_url,
        model=config.model,
        request_timeout=config.request_timeout,
        language=config.language,
        transport=transport,
    )
