"""Shared helper for one-shot, non-graph LLM text requests.

Several Gateway routes (input polishing, follow-up suggestions, and title-style
rewrites) do the same thing: build a chat model from config, attach Langfuse
trace metadata, invoke it once with a system + user message pair, and pull the
plain text back out of the response. Centralizing that sequence here keeps the
tracing-metadata fields and invocation shape from drifting between routers — a
fix to one (e.g. a new Langfuse field) now applies to all callers instead of
silently regressing in whichever copy was forgotten.

Response-text *cleaning* (think-block / code-fence stripping, JSON parsing) is
intentionally left to each caller because their post-processing differs; this
helper stops at the extracted raw text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.config.app_config import AppConfig
from deerflow.model_ids import normalize_reported_model_name
from deerflow.models import create_chat_model
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tracing import inject_langfuse_metadata
from deerflow.utils.llm_text import extract_response_text


def _resolve_environment() -> str | None:
    return os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT")


@dataclass(frozen=True)
class OneshotResult:
    """Result of a one-shot LLM turn: extracted text plus usage for accounting."""

    text: str
    # Raw ``usage_metadata`` dict from the response (input/output/total tokens,
    # optional ``input_token_details.cache_read``), or ``None`` when the
    # provider reported no usage.
    usage: dict[str, Any] | None
    # Best model identity for pricing lookup: the provider-reported model id
    # when present, else the requested override name.
    model_name: str | None


def _response_model_name(response: Any, requested: str | None) -> str | None:
    """The model that served this call, normalized for pricing.

    A model configured with ``streaming: true`` assembles even an ``ainvoke``
    from chunks, which can report the id twice over (see
    ``deerflow.model_ids``); the aux counters this feeds are priced by that id.
    """
    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        for key in ("model_name", "model"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return normalize_reported_model_name(value)
    return requested


async def run_oneshot_llm_with_usage(
    *,
    system_instruction: str,
    user_content: str,
    run_name: str,
    app_config: AppConfig,
    model_name: str | None = None,
    thread_id: str | None = None,
) -> OneshotResult:
    """Run a single non-graph system+user LLM turn, returning text and usage.

    Same request shape as :func:`run_oneshot_llm`, but also surfaces the
    response's token usage so callers that want to bill the call (e.g. the
    follow-up-suggestions cost counter) can record it.
    """
    model = create_chat_model(name=model_name, thinking_enabled=False, app_config=app_config)
    invoke_config: dict = {"run_name": run_name}
    inject_langfuse_metadata(
        invoke_config,
        thread_id=thread_id,
        user_id=get_effective_user_id(),
        assistant_id=run_name,
        model_name=model_name,
        environment=_resolve_environment(),
    )
    response = await model.ainvoke(
        [
            SystemMessage(content=system_instruction),
            HumanMessage(content=user_content),
        ],
        config=invoke_config,
    )
    usage = getattr(response, "usage_metadata", None)
    return OneshotResult(
        text=extract_response_text(response.content),
        usage=usage if isinstance(usage, dict) else None,
        model_name=_response_model_name(response, model_name),
    )


async def run_oneshot_llm(
    *,
    system_instruction: str,
    user_content: str,
    run_name: str,
    app_config: AppConfig,
    model_name: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Run a single non-graph system+user LLM turn and return the raw text.

    Args:
        system_instruction: System message content.
        user_content: Human message content.
        run_name: LangChain ``run_name`` and Langfuse ``assistant_id`` for the call.
        app_config: Application config used to build the model.
        model_name: Optional model override; ``None`` uses the default model.
        thread_id: Optional thread id, forwarded to Langfuse for tracing only.

    Returns:
        The extracted plain-text content of the model response (uncleaned).
    """
    result = await run_oneshot_llm_with_usage(
        system_instruction=system_instruction,
        user_content=user_content,
        run_name=run_name,
        app_config=app_config,
        model_name=model_name,
        thread_id=thread_id,
    )
    return result.text
