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

The audio is streamed to a bounded in-memory buffer and forwarded; it is never
written to disk and never logged. A transcript is speech, and speech that lands
in a log file outlives the conversation it belonged to.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from deerflow.community.speech import SpeechToTextError, SpeechToTextUnavailableError, build_client, is_local_endpoint, resolve_base_url
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


class TranscriptionResponse(BaseModel):
    text: str = Field(description="The recognized transcript. Empty when the service heard nothing.")


@router.get("/config", response_model=VoiceConfigResponse)
async def get_voice_config() -> VoiceConfigResponse:
    """Report the permitted tiers so the composer can pick one up front."""
    voice = get_app_config().voice
    local_service = True
    if voice.stt.enabled:
        local_service = is_local_endpoint(resolve_base_url(voice.stt.base_url))
    return VoiceConfigResponse(
        prefer_on_device=voice.prefer_on_device,
        server_transcription=voice.stt.enabled,
        allow_cloud_fallback=voice.allow_cloud_fallback,
        local_service=local_service,
    )


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
        raise HTTPException(status_code=503, detail="Server-side transcription is not enabled. Set voice.stt.enabled: true and point voice.stt.base_url at a local transcription service.")

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
