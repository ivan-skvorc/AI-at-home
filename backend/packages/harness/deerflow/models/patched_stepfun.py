"""Patched ChatOpenAI adapter for StepFun reasoning models.

StepFun returns ``reasoning`` (or ``reasoning_content`` with deepseek-style) in
both streaming deltas and non-streaming responses. Standard ``ChatOpenAI``
ignores these non-standard fields, so reasoning content is silently dropped.
This adapter captures reasoning from all response paths and replays it on
historical assistant messages for multi-turn tool-call conversations.
"""

from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.language_models import LanguageModelInput

from deerflow.models.assistant_payload_replay import (
    restore_assistant_payloads,
    restore_reasoning_content,
)
from deerflow.models.reasoning_capture import ReasoningCaptureChatOpenAI


class PatchedChatStepFun(ReasoningCaptureChatOpenAI):
    """ChatOpenAI with full reasoning support for StepFun models.

    Captures ``reasoning`` / ``reasoning_content`` from both streaming and
    non-streaming responses (through ``ReasoningCaptureChatOpenAI``) and replays
    it on historical assistant messages in multi-turn tool-call conversations.
    """

    # reasoning_content first (deepseek-style), then reasoning (StepFun default).
    reasoning_fields: ClassVar[tuple[str, ...]] = ("reasoning_content", "reasoning")

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"api_key": "STEPFUN_API_KEY", "openai_api_key": "STEPFUN_API_KEY"}

    # --- Request payload replay ---

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Restore ``reasoning_content`` on historical assistant messages."""
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # StepFun documents max_tokens; ChatOpenAI emits the newer OpenAI name.
        # Preserve the configured output bound on probes and ordinary chat calls.
        if "max_completion_tokens" in payload:
            payload["max_tokens"] = payload.pop("max_completion_tokens")

        restore_assistant_payloads(
            payload.get("messages", []),
            original_messages,
            restore_reasoning_content,
        )

        return payload
