"""Server-side speech-to-text against a local service (fork feature)."""

from deerflow.community.speech.stt_client import (
    SpeechToTextClient,
    SpeechToTextError,
    SpeechToTextUnavailableError,
    build_client,
    is_local_endpoint,
    resolve_base_url,
)

__all__ = [
    "SpeechToTextClient",
    "SpeechToTextError",
    "SpeechToTextUnavailableError",
    "build_client",
    "is_local_endpoint",
    "resolve_base_url",
]
