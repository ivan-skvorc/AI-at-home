"""Server-side speech-to-text and the voice capability contract (fork feature).

The feature exists to stop the composer's microphone from shipping audio to a
model vendor, so the asserts that matter are the refusals: an unconfigured
install must not pretend it can transcribe, an oversized recording must be
rejected while it is still being read, and a public `base_url` must be refused
unless the operator said in writing that it is theirs.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import voice as voice_router
from deerflow.community.speech import SpeechToTextError, SpeechToTextUnavailableError, build_client, is_local_endpoint, resolve_base_url
from deerflow.community.speech.stt_client import BASE_URL_ENV_VAR, SpeechToTextClient
from deerflow.config.voice_config import SpeechToTextConfig, VoiceConfig


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(voice_router.router)
    return app


def _config(**overrides) -> VoiceConfig:
    stt = SpeechToTextConfig(**overrides.pop("stt", {}))
    return VoiceConfig(stt=stt, **overrides)


class _AppConfigStub:
    def __init__(self, voice: VoiceConfig):
        self.voice = voice


def _with_config(voice: VoiceConfig):
    return patch.object(voice_router, "get_app_config", lambda: _AppConfigStub(voice))


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# --- capability reporting ----------------------------------------------------


def test_voice_config_reports_the_permitted_tiers():
    voice = _config(stt={"enabled": True}, prefer_on_device=True, allow_cloud_fallback=False)
    with _with_config(voice), TestClient(_app()) as client:
        body = client.get("/api/voice/config").json()

    assert body == {"prefer_on_device": True, "server_transcription": True, "allow_cloud_fallback": False, "local_service": True}


def test_cloud_fallback_is_off_by_default():
    """The whole point of the feature: no silent vendor fallback."""
    assert VoiceConfig().allow_cloud_fallback is False
    assert VoiceConfig().prefer_on_device is True
    assert VoiceConfig().stt.enabled is False


# --- the transcribe endpoint -------------------------------------------------


def test_transcribe_returns_503_when_server_transcription_is_disabled():
    """503 is the composer's signal to try the next tier, not an error to show."""
    with _with_config(_config(stt={"enabled": False})), TestClient(_app()) as client:
        response = client.post("/api/voice/transcribe", files={"file": ("speech.webm", b"audio", "audio/webm")})

    assert response.status_code == 503
    assert "voice.stt.enabled" in response.json()["detail"]


def test_transcribe_rejects_audio_over_the_cap_without_calling_the_service():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        nonlocal called
        called = True
        return httpx.Response(200, json={"text": "should never happen"})

    voice = _config(stt={"enabled": True, "max_audio_bytes": 16})
    with _with_config(voice), patch.object(voice_router, "build_client", lambda cfg: SpeechToTextClient("http://stt", model="m", transport=_transport(handler))):
        with TestClient(_app()) as client:
            response = client.post("/api/voice/transcribe", files={"file": ("speech.webm", b"x" * 64, "audio/webm")})

    assert response.status_code == 413
    assert "max_audio_bytes" in response.json()["detail"]
    assert called is False, "the size cap must be enforced before the service is called"


def test_transcribe_rejects_an_empty_upload():
    with _with_config(_config(stt={"enabled": True})), TestClient(_app()) as client:
        response = client.post("/api/voice/transcribe", files={"file": ("speech.webm", b"", "audio/webm")})

    assert response.status_code == 400


def test_transcribe_returns_the_transcript_from_the_local_service():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "  hello from the local box  "})

    voice = _config(stt={"enabled": True})
    client_stub = SpeechToTextClient("http://stt.local", model="tiny", transport=_transport(handler))
    with _with_config(voice), patch.object(voice_router, "build_client", lambda cfg: client_stub):
        with TestClient(_app()) as client:
            response = client.post("/api/voice/transcribe", files={"file": ("speech.webm", b"audio-bytes", "audio/webm")})

    assert response.status_code == 200
    assert response.json() == {"text": "hello from the local box"}
    assert seen["url"] == "http://stt.local/v1/audio/transcriptions"
    assert b"audio-bytes" in seen["body"]


def test_transcribe_maps_an_unreachable_service_to_502():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    voice = _config(stt={"enabled": True})
    client_stub = SpeechToTextClient("http://stt.local", model="tiny", transport=_transport(handler))
    with _with_config(voice), patch.object(voice_router, "build_client", lambda cfg: client_stub):
        with TestClient(_app()) as client:
            response = client.post("/api/voice/transcribe", files={"file": ("speech.webm", b"audio", "audio/webm")})

    assert response.status_code == 502


# --- the client --------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_accepts_a_bare_text_body():
    """Several local servers answer response_format=text with a bare string."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="  plain text transcript ")

    client = SpeechToTextClient("http://stt", model="m", transport=_transport(handler))
    assert await client.transcribe(b"audio") == "plain text transcript"


@pytest.mark.asyncio
async def test_client_sends_the_configured_model_and_language():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", "replace")
        seen["body"] = body
        return httpx.Response(200, json={"text": "ok"})

    client = SpeechToTextClient("http://stt", model="faster-whisper-small", language="de", transport=_transport(handler))
    await client.transcribe(b"audio")

    assert "faster-whisper-small" in seen["body"]
    assert "de" in seen["body"]


@pytest.mark.asyncio
async def test_client_refuses_empty_audio_without_a_request():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        nonlocal called
        called = True
        return httpx.Response(200, json={"text": ""})

    client = SpeechToTextClient("http://stt", model="m", transport=_transport(handler))
    with pytest.raises(SpeechToTextError):
        await client.transcribe(b"")
    assert called is False


@pytest.mark.asyncio
async def test_client_error_text_never_echoes_the_service_body():
    """A transcript is speech; an error that quotes the body can leak it into logs."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error: transcript was 'my bank password is hunter2'")

    client = SpeechToTextClient("http://stt", model="m", transport=_transport(handler))
    with pytest.raises(SpeechToTextError) as exc_info:
        await client.transcribe(b"audio")

    assert "hunter2" not in str(exc_info.value)
    assert "500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_client_raises_unavailable_for_transport_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    client = SpeechToTextClient("http://stt", model="m", transport=_transport(handler))
    with pytest.raises(SpeechToTextUnavailableError):
        await client.transcribe(b"audio")


# --- endpoint screening ------------------------------------------------------


def test_build_client_refuses_a_loopback_host_when_private_addresses_are_disallowed():
    """The shared SSRF guard still applies: opting out of it must actually bite."""
    cfg = SpeechToTextConfig(enabled=True, base_url="http://127.0.0.1:8000", allow_private_addresses=False)
    with pytest.raises(SpeechToTextError) as exc_info:
        build_client(cfg)
    assert "allow_private_addresses" in str(exc_info.value)


def test_a_public_endpoint_is_reported_as_not_local():
    """The feature's own risk runs the other way from SSRF: audio leaving the box.

    The shared guard cannot catch this — a public host is exactly what it
    permits — so `is_local_endpoint` is what lets the operator be warned and the
    composer label the tier.
    """
    assert is_local_endpoint("http://127.0.0.1:8000") is True
    assert is_local_endpoint("http://localhost:8000") is True
    assert is_local_endpoint("http://192.168.1.50:8000") is True
    assert is_local_endpoint("http://8.8.8.8:8000") is False
    assert is_local_endpoint("not a url") is False


def test_a_tailnet_endpoint_counts_as_local():
    """CGNAT is not `is_private` on CPython, so this needs its own rule.

    Reaching the stack over Tailscale is this fork's documented access path
    (FORK.md), which makes 100.64.0.0/10 a machine the household owns. Without
    this the composer would label a tailnet STT service as sending audio off
    the host, which is the opposite of true.
    """
    assert is_local_endpoint("http://100.101.102.103:8000") is True
    assert is_local_endpoint("http://100.64.0.1:8000") is True
    assert is_local_endpoint("http://100.127.255.254:8000") is True
    # Just outside the /10 — 100.128.x is public space.
    assert is_local_endpoint("http://100.128.0.1:8000") is False


def test_the_config_endpoint_flags_a_non_local_transcription_service():
    voice = _config(stt={"enabled": True, "base_url": "http://8.8.8.8:8000"})
    with _with_config(voice), TestClient(_app()) as client:
        body = client.get("/api/voice/config").json()

    assert body["server_transcription"] is True
    assert body["local_service"] is False


def test_build_client_warns_when_the_endpoint_is_not_local(caplog):
    cfg = SpeechToTextConfig(enabled=True, base_url="http://8.8.8.8:8000")
    with caplog.at_level("WARNING"):
        build_client(cfg)
    assert "will leave this host" in caplog.text


def test_build_client_stays_quiet_for_a_local_endpoint(caplog):
    with caplog.at_level("WARNING"):
        build_client(SpeechToTextConfig(enabled=True, base_url="http://127.0.0.1:8000"))
    assert "will leave this host" not in caplog.text


def test_build_client_allows_loopback_by_default():
    """A local STT service is the intentional-internal-target case."""
    cfg = SpeechToTextConfig(enabled=True, base_url="http://localhost:8000")
    assert build_client(cfg).base_url == "http://localhost:8000"


def test_env_var_overrides_the_configured_base_url(monkeypatch):
    monkeypatch.setenv(BASE_URL_ENV_VAR, "http://stt:8000")
    assert resolve_base_url("http://localhost:8000") == "http://stt:8000"


def test_env_var_is_ignored_when_empty(monkeypatch):
    monkeypatch.setenv(BASE_URL_ENV_VAR, "   ")
    assert resolve_base_url("http://localhost:8000") == "http://localhost:8000"
