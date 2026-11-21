"""Patched ChatOpenAI adapter for Xiaomi MiMo reasoning_content replay.

MiMo's OpenAI-compatible API returns ``reasoning_content`` in thinking mode and
requires that value to be replayed on historical assistant messages in
multi-turn agent conversations. Standard ``langchain_openai.ChatOpenAI`` drops
that provider-specific field, which can cause HTTP 400 errors once tool calls
enter the conversation history.
"""

from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.language_models import LanguageModelInput

from deerflow.models.assistant_payload_replay import restore_assistant_payloads, restore_reasoning_content
from deerflow.models.reasoning_capture import ReasoningCaptureChatOpenAI


class PatchedChatMiMo(ReasoningCaptureChatOpenAI):
    """ChatOpenAI with ``reasoning_content`` preservation for MiMo thinking mode.

    Streaming and non-streaming capture come from ``ReasoningCaptureChatOpenAI``;
    this class replays the captured value on outgoing assistant messages.
    """

    reasoning_fields: ClassVar[tuple[str, ...]] = ("reasoning_content",)

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"api_key": "MIMO_API_KEY", "openai_api_key": "MIMO_API_KEY"}

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        restore_assistant_payloads(
            payload.get("messages", []),
            original_messages,
            restore_reasoning_content,
        )

        return payload
