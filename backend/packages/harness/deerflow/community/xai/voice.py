"""Grok voice on the connected subscription: read-aloud and a cloud transcription tier (fork feature).

Both send data to xAI — the answer's text for read-aloud, the recording for
transcription — so both exist only while the operator has switched the Grok
``voice`` feature on. They sit *beside* the local tiers, never in front of
them: a configured local STT service always wins, and a failing local service
is never silently retried against the cloud (``app/gateway/routers/voice.py``).

Errors follow the speech module's rule: status and endpoint only. A transcript
is speech, and an answer read aloud is the user's conversation.
"""

from __future__ import annotations

import httpx

from .client import XaiClient, XaiError

# xAI accepts far longer text; this keeps one read-aloud request to the length
# of an answer rather than a document, and bounds what one click spends.
MAX_SPEAK_CHARS = 12000
MAX_SPEECH_AUDIO_BYTES = 32 * 1024 * 1024
DEFAULT_VOICE = "eve"
TRANSCRIBE_MODEL = "grok-voice-transcribe-2.0"


def _language(language: str | None) -> str | None:
    # voice.stt.language is a BCP-47 hint ("en-US"); xAI takes the base code.
    return language.split("-")[0].lower() if isinstance(language, str) and language.strip() else None


async def synthesize(text: str, *, language: str | None = None, voice: str = DEFAULT_VOICE, transport: httpx.AsyncBaseTransport | None = None) -> tuple[bytes, str]:
    """Speak *text* with Grok's TTS. Returns the audio and its media type."""
    if not text.strip():
        raise XaiError("Nothing to read aloud")
    if len(text) > MAX_SPEAK_CHARS:
        raise XaiError(f"Read-aloud text is limited to {MAX_SPEAK_CHARS} characters")
    payload: dict[str, str] = {"text": text, "voice_id": voice}
    if code := _language(language):
        payload["language"] = code
    audio, content_type = await XaiClient("voice", timeout=90.0, transport=transport).request_bytes("POST", "/tts", json=payload, max_bytes=MAX_SPEECH_AUDIO_BYTES)
    if not audio:
        raise XaiError("Grok returned no audio")
    media_type = content_type.split(";")[0].strip().lower()
    return audio, media_type if media_type.startswith("audio/") else "audio/mpeg"


async def transcribe(audio: bytes, *, filename: str, content_type: str, language: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """Transcribe one recording with Grok's speech-to-text."""
    data = {"model": TRANSCRIBE_MODEL}
    if code := _language(language):
        data["language"] = code
    # httpx writes form fields before files, which is the order xAI requires:
    # the file part must come last in the multipart body.
    payload = await XaiClient("voice", timeout=90.0, transport=transport).request_json("POST", "/stt", data=data, files={"file": (filename, audio, content_type)})
    text = payload.get("text")
    if not isinstance(text, str):
        raise XaiError("Grok returned no transcript")
    return text.strip()
