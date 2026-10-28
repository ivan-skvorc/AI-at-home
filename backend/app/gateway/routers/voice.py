"""Voice input: capability reporting and server-side transcription (fork feature).

Two routes, and the split between them is the feature.

``GET /api/voice/config`` tells the browser which tiers this install permits, so
the composer can decide *before* it opens a microphone. The browser can see for
itself whether it does on-device recognition, but only the server knows whether
a local transcription service is configured and whether the cloud tier is
allowed at all.

``POST /api/voice/transcribe`` is the second tier: recorded audio in, transcript
out, transcribed by a service on this machine. It exists so that a browser
without on-device recognition still does not have to send its audio to Google.
When no local service is configured and the operator switched the Grok
``voice`` feature on, the same route transcribes through xAI instead, and the
config response says so (``local_service: false``, ``transcription_provider:
"xai"``) so the composer can name the destination. A configured local service
always wins, and its failures are never retried against the cloud.

``POST /api/voice/speak`` is read-aloud: an answer's text in, Grok's speech
out. It exists only while the Grok ``voice`` feature is on (FORK.md §43).

The audio is streamed to a bounded in-memory buffer and forwarded; it is never
written to disk and never logged. A transcript is speech, and speech that lands
in a log file outlives the conversation it belonged to.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from deerflow.community.speech import SpeechToTextError, SpeechToTextUnavailableError, build_client, is_local_endpoint, resolve_base_url
from deerflow.community.xai import voice as grok_voice
from deerflow.community.xai.client import XaiError
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

# Read in chunks rather than calling `.read()` unbounded: the cap has to be
# enforced while consuming the stream, not after a client already made the
# process hold an arbitrary body in memory.
_CHUNK_BYTES = 64 * 1024


class VoiceConfigResponse(BaseModel):
    """Which voice-input tiers this install permits."""

    prefer_on_device: bool = Field(description="Ask the browser to recognize speech on-device when it can.")
    server_transcription: bool = Field(description="Whether POST /api/voice/transcribe is backed by a configured local service.")
    allow_cloud_fallback: bool = Field(description="Whether the browser's cloud recognition may be used as a last resort. False means voice reports itself unavailable instead.")
    local_service: bool = Field(
        default=True, description="Whether the configured transcription endpoint resolves to this machine or its private network. False means the server tier still sends audio off this host, and the composer says so."
    )
    transcription_provider: str | None = Field(default=None, description="'xai' when the server tier is Grok's cloud transcription on the connected Grok subscription; null for an operator-configured service.")
    read_aloud: bool = Field(default=False, description="Whether POST /api/voice/speak reads answers aloud through Grok. Requires the Grok voice feature switched on in Settings.")
    read_aloud_max_chars: int = Field(default=grok_voice.MAX_SPEAK_CHARS, description="Longest text one read-aloud request accepts.")


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=grok_voice.MAX_SPEAK_CHARS, description="Plain text to read aloud.")


class TranscriptionResponse(BaseModel):
    text: str = Field(description="The recognized transcript. Empty when the service heard nothing.")


@router.get("/config", response_model=VoiceConfigResponse)
async def get_voice_config() -> VoiceConfigResponse:
    """Report the permitted tiers so the composer can pick one up front."""
    voice = get_app_config().voice
    grok = await _grok_voice_ready()
    local_service = True
    provider = None
    if voice.stt.enabled:
        local_service = is_local_endpoint(resolve_base_url(voice.stt.base_url))
    elif grok:
        local_service, provider = False, "xai"
    return VoiceConfigResponse(
        prefer_on_device=voice.prefer_on_device,
        server_transcription=voice.stt.enabled or grok,
        allow_cloud_fallback=voice.allow_cloud_fallback,
        local_service=local_service,
        transcription_provider=provider,
        read_aloud=grok,
    )


async def _grok_voice_ready() -> bool:
    """Whether the operator switched Grok voice on; storage problems read as off."""
    from deerflow.models.subscriptions import SubscriptionError, grok_feature_ready

    try:
        return await asyncio.to_thread(grok_feature_ready, "voice")
    except SubscriptionError:
        logger.warning("voice: subscription storage is unavailable; Grok voice is off")
        return False


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(file: UploadFile = File(...)) -> TranscriptionResponse:
    """Transcribe recorded audio on this machine.

    A 503 here means "not configured", which the composer treats as "fall back
    to the next tier". A 413 means the recording was too long. Both are
    deliberately distinguishable from a 502, which means the configured service
    exists but did not answer.
    """
    voice = get_app_config().voice
    if not voice.stt.enabled:
        if not await _grok_voice_ready():
            raise HTTPException(status_code=503, detail="Server-side transcription is not enabled. Set voice.stt.enabled: true and point voice.stt.base_url at a local transcription service.")
        audio = await _read_bounded(file, voice.stt.max_audio_bytes)
        try:
            text = await grok_voice.transcribe(audio, filename=file.filename or "speech.webm", content_type=file.content_type or "audio/webm", language=voice.stt.language)
        except XaiError as exc:
            logger.warning("voice: Grok transcription failed (HTTP %s)", exc.status)
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return TranscriptionResponse(text=text)

    audio = await _read_bounded(file, voice.stt.max_audio_bytes)

    try:
        client = build_client(voice.stt)
    except SpeechToTextError as exc:
        # A misconfigured endpoint is an operator problem, not a transient one.
        logger.warning("voice: speech-to-text endpoint rejected: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        text = await client.transcribe(audio, filename=file.filename or "speech.webm", content_type=file.content_type or "audio/webm")
    except SpeechToTextUnavailableError as exc:
        logger.warning("voice: speech-to-text service unreachable: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SpeechToTextError as exc:
        logger.warning("voice: transcription failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return TranscriptionResponse(text=text)


@router.post("/speak", response_class=Response, responses={200: {"content": {"audio/mpeg": {}}}})
async def speak(body: SpeakRequest) -> Response:
    """Read text aloud through Grok's text-to-speech on the connected subscription.

    503 means Grok voice is not switched on; 502 means Grok did not answer.
    The text is never logged, and errors never echo it or the service's body.
    """
    if not await _grok_voice_ready():
        raise HTTPException(status_code=503, detail="Read-aloud needs the Grok voice feature switched on in Settings → Models → Subscriptions.")
    try:
        audio, media_type = await grok_voice.synthesize(body.text, language=get_app_config().voice.stt.language)
    except XaiError as exc:
        logger.warning("voice: Grok read-aloud failed (HTTP %s)", exc.status)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "no-store"})


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """Read the upload, refusing anything past ``limit`` while still reading."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=f"The recording is larger than the configured limit of {limit} bytes (voice.stt.max_audio_bytes).")
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="No audio was uploaded.")
    return b"".join(chunks)
