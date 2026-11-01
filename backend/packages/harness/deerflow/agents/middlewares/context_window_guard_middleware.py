"""Never send a request the serving model's context window cannot hold.

Fork feature (roadmap item 34). Ollama does not reject a prompt longer than
``num_ctx``: it truncates it, logs ``truncating input prompt`` and keeps the most
recent tokens — so the system prompt, the tool rules and the user's question are
the first things lost, and a model left holding a tool list and a page of a
cookbook still does *something*. Every other protection in the loop is per value
(each tool result is clamped to a share of the window by
``ToolOutputBudgetMiddleware``) or late (compaction's trigger); nothing bounded
the *sum* of one request.

This guard estimates the whole request — system prompt, bound tool schemas and
messages — against the usable window of the model actually serving the call
(``deerflow.utils.context_budget``) and, when it does not fit:

1. replaces the **oldest** tool results with a short placeholder, in the request
   view only (stored history, checkpoints and the run journal keep the original),
   until it fits. The results the model is about to read — everything after the
   last assistant message — are never touched, nor is any non-tool message, so
   the system prompt and the user's question always survive;
2. and when even that cannot make it fit, does not send it: the run ends with a
   visible error naming the model and its window, carried by the same
   ``deerflow_error_fallback`` marker the LLM error handler uses, so the run is
   recorded as failed rather than as a confident answer to a truncated prompt.

An unknown window keeps the guard a no-op, as every other budget helper is.

Placement: right after ``ModelContentCompatibilityMiddleware`` in both the lead
and subagent chains — inner of every built-in request transform, so it measures
the near-final request, and outer of the ``MODEL_PHYSICAL`` extension anchor, so
extensions placed there still see the final request.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from deerflow.utils.context_budget import ContextBudget, estimate_tokens, resolve_context_budget

logger = logging.getLogger(__name__)

ELIDED_TOOL_RESULT_PREFIX = "[Earlier tool result removed from this request"
# Role, separators and framing each message costs on top of its text.
_PER_MESSAGE_TOKENS = 4
# What a provider charges for one image is not its base64 length; a typical
# vision encoder spends on the order of a thousand tokens per image.
_IMAGE_TOKENS = 1_600
_MODEL_LABEL_ATTRS = ("model_name", "model", "name", "deployment_name")
# The estimate counts four characters per token, which is right for prose and
# ~25% low for JSON and code (closer to three) — and the tool schemas riding on
# every request are JSON. Aim inside the window by this share to cover the mix.
_SAFETY_MARGIN = 0.9


def _content_tokens(content: Any) -> int:
    if isinstance(content, str):
        return estimate_tokens(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, str):
                total += estimate_tokens(block)
            elif isinstance(block, dict):
                kind = block.get("type")
                if kind in ("image", "image_url", "input_image"):
                    total += _IMAGE_TOKENS
                elif isinstance(block.get("text"), str):
                    total += estimate_tokens(block["text"])
                else:
                    total += estimate_tokens(json.dumps(block, ensure_ascii=False, default=str))
        return total
    return 0


def _message_tokens(message: BaseMessage) -> int:
    tokens = _PER_MESSAGE_TOKENS + _content_tokens(message.content)
    if isinstance(message, AIMessage) and message.tool_calls:
        tokens += estimate_tokens(json.dumps([{"name": call.get("name"), "args": call.get("args")} for call in message.tool_calls], ensure_ascii=False, default=str))
    return tokens


def _tool_tokens(tool: Any) -> int:
    try:
        if isinstance(tool, dict):
            return estimate_tokens(json.dumps(tool, ensure_ascii=False, default=str))
        from langchain_core.utils.function_calling import convert_to_openai_tool

        return estimate_tokens(json.dumps(convert_to_openai_tool(tool), ensure_ascii=False, default=str))
    except Exception:  # a schema that cannot be rendered still costs its description
        return estimate_tokens(str(getattr(tool, "description", "")))


def estimate_request_tokens(request: ModelRequest) -> int:
    """Estimate everything one model call sends: system prompt, tool schemas and messages."""
    total = sum(_message_tokens(message) for message in request.messages)
    if request.system_message is not None:
        total += _message_tokens(request.system_message)
    return total + sum(_tool_tokens(tool) for tool in request.tools or ())


def _model_label(model: Any) -> str:
    for attr in _MODEL_LABEL_ATTRS:
        value = getattr(model, attr, None)
        if isinstance(value, str) and value:
            return value
    return "the selected model"


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        function = tool.get("function")
        return function.get("name") if isinstance(function, dict) else tool.get("name")
    return getattr(tool, "name", None)


def _placeholder(message: ToolMessage, window: int, *, can_analyze: bool) -> str:
    name = message.name or "tool"
    size = len(message.content) if isinstance(message.content, str) else _content_tokens(message.content) * 4
    # Only point at analyze_document when this request can call it: naming a
    # tool the model does not have costs a failed call and a wasted turn.
    advice = "; to cover a long document, call `analyze_document`, which reads it in parts that each fit." if can_analyze else "."
    return f"{ELIDED_TOOL_RESULT_PREFIX} to fit the model's {window:,}-token context window: `{name}` returned about {size:,} characters here.] Do not re-read it in full. Work from what you have already concluded{advice}"


class ContextWindowGuardMiddleware(AgentMiddleware):
    """Shrink an oversized request by its oldest tool results, or refuse to send it."""

    def __init__(self, app_config: Any | None = None) -> None:
        super().__init__()
        self._app_config = app_config

    def _resolved_app_config(self) -> Any | None:
        if self._app_config is not None:
            return self._app_config
        try:
            from deerflow.config.app_config import get_app_config

            return get_app_config()
        except Exception:
            return None

    def _guard(self, request: ModelRequest) -> ModelRequest | AIMessage:
        budget: ContextBudget | None = resolve_context_budget(request.model, self._resolved_app_config())
        if budget is None:
            return request
        window = budget.prompt_tokens
        limit = int(window * _SAFETY_MARGIN)
        messages = list(request.messages)
        costs = [_message_tokens(message) for message in messages]
        fixed = estimate_request_tokens(request.override(messages=[]))
        total = fixed + sum(costs)
        if total <= limit:
            return request

        # Everything after the last assistant message is what the model is about
        # to read; only tool results before it may go, oldest first.
        last_ai = max((i for i, message in enumerate(messages) if isinstance(message, AIMessage)), default=-1)
        can_analyze = any(_tool_name(tool) == "analyze_document" for tool in request.tools or ())
        elided = 0
        for index in range(last_ai):
            message = messages[index]
            if total <= limit:
                break
            if not isinstance(message, ToolMessage) or (isinstance(message.content, str) and message.content.startswith(ELIDED_TOOL_RESULT_PREFIX)):
                continue
            replacement = message.model_copy(update={"content": _placeholder(message, budget.context_window, can_analyze=can_analyze)})
            saved = costs[index] - _message_tokens(replacement)
            if saved <= 0:
                continue
            messages[index] = replacement
            costs[index] -= saved
            total -= saved
            elided += 1

        model = _model_label(request.model)
        if total <= limit:
            logger.info("Context guard: removed %d earlier tool result(s) so a request to %s fits its %d-token prompt space", elided, model, window)
            return request.override(messages=messages)

        content = (
            f"This conversation no longer fits {model}'s context window: the next request needs about {total:,} tokens, "
            f"and the window leaves {window:,} for the prompt. It was not sent, because the model would have silently lost "
            "the start of it — the instructions and your question. Start a new chat, compact this one with /compact, "
            "or switch to a model with a larger context window."
        )
        logger.warning("Context guard: refused a request to %s (~%d tokens; %d-token prompt space)", model, total, window)
        return AIMessage(
            content=content,
            additional_kwargs={
                "deerflow_error_fallback": True,
                "error_type": "context_window_exceeded",
                "error_reason": "context_window_exceeded",
                "error_detail": content,
            },
        )

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        guarded = self._guard(request)
        return guarded if isinstance(guarded, AIMessage) else handler(guarded)

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        guarded = self._guard(request)
        return guarded if isinstance(guarded, AIMessage) else await handler(guarded)
