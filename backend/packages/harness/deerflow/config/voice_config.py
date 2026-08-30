"""Local speech-to-text configuration — fork feature.

The composer's microphone button used to be the one place this fork's privacy
claim quietly failed. It wraps the browser ``SpeechRecognition`` API, whose
default implementation streams the audio to the vendor's servers — Google in
Chrome, Apple in Safari. That traffic goes from the browser straight to the
vendor over the public internet: it never passes through the Gateway, so none
of the tailnet work protects it, and nothing in the UI said so.

This section configures the replacement's second tier. The first tier is the
browser's own on-device recognition (Chrome's ``processLocally``), which needs
no server at all. When the browser cannot do that, the recorded audio is posted
to the Gateway and transcribed **on this machine** instead of the vendor's.

The service is reached over HTTP the way ComfyUI is, rather than loading
weights in-process: the Gateway is a long-lived API server, and a transcription
model is large stateful data with its own lifecycle. Any server speaking the
OpenAI ``/v1/audio/transcriptions`` shape works (faster-whisper-server,
speaches, whisper.cpp's ``server``, LocalAI), which is why no specific engine
is named here.

``allow_cloud_fallback`` is the deliberate part. Leaving it false means a
browser with neither tier available reports that voice input is unavailable
rather than silently reaching for the vendor's cloud. That is the whole point
of the feature, so the default is false and turning it on is a choice the
operator makes in writing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# One minute of 16 kHz mono Opus is well under a megabyte; 25 MiB is generous
# for a composer utterance while still bounding what an unauthenticated-ish
# local caller can push through the transcription service.
DEFAULT_MAX_AUDIO_BYTES = 25 * 1024 * 1024


class SpeechToTextConfig(BaseModel):
    """How the Gateway reaches a local speech-to-text service."""

    enabled: bool = Field(default=False, description="Whether the Gateway offers server-side transcription at all. Off by default: without a reachable local STT service the endpoint has nothing to call.")
    base_url: str = Field(default="http://localhost:8000", description="Base URL of an OpenAI-compatible transcription service. DEER_FLOW_STT_BASE_URL overrides it (set in-network by the Docker stacks).")
    model: str = Field(default="Systran/faster-whisper-small", description="Model name passed through to the service. Whatever that service reports; DeerFlow does not validate it against a list it cannot know.")
    language: str | None = Field(default=None, description="BCP-47 language hint sent with each request. Null lets the service auto-detect, which is right for a multilingual household.")
    allow_private_addresses: bool = Field(
        default=True,
        description=(
            "SSRF opt-out for the shared URL guard. A loopback / LAN transcription service is the intentional-internal-target case, so this defaults to true here (unlike web tools). Set false when base_url points at a public host."
        ),
    )
    request_timeout: float = Field(default=60.0, gt=0, description="Wall-clock cap (seconds) for one transcription call. Generous on purpose: a CPU-only whisper backend is slow, and a truncated request wastes the recording entirely.")
    max_audio_bytes: int = Field(default=DEFAULT_MAX_AUDIO_BYTES, gt=0, description="Largest upload the transcribe endpoint accepts, in bytes. Rejected before any byte reaches the STT service.")


class VoiceConfig(BaseModel):
    """Voice input: which tiers are permitted, and how to reach the local one."""

    stt: SpeechToTextConfig = Field(default_factory=SpeechToTextConfig, description="Server-side transcription on this machine — the fallback used when the browser cannot recognize speech on-device.")
    prefer_on_device: bool = Field(
        default=True,
        description="Ask the browser to recognize speech on-device when it can. Setting this false skips straight to server-side transcription, which is occasionally useful when the local STT model is better than the browser's.",
    )
    allow_cloud_fallback: bool = Field(
        default=False,
        description=(
            "Permit the browser's cloud speech recognition (Google in Chrome, Apple in Safari) when neither "
            "on-device nor server-side transcription is available. False means voice input reports itself "
            "unavailable instead of sending audio off this machine. The UI labels this tier when it is in use."
        ),
    )
