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
(``deerflow.utils.context_budget``).

On a **small** window (a local GPU's; ``ContextBudget.is_small``) the tool
schemas always go out in short form (FORK.md §47): the same names, parameters,
types, enums and required lists, with each description cut to its opening
sentences and an optional argument's ``anyOf [T, null]`` reduced to ``T``. A stock tool set costs ~8K tokens in full, a third of a synced 32K
Ollama entry's prompt space before the user has typed anything. Always, rather
than only when over, so the request prefix is stable for the server's KV cache.

When the request still does not fit, the guard:

1. replaces the **oldest** tool results with a short placeholder, in the request
   view only (stored history, checkpoints and the run journal keep the original),
   until it fits. The results the model is about to read — everything after the
   last assistant message — are never touched, nor is any non-tool message, so
   the system prompt and the user's question always survive;
2. on a larger window, sends the tool schemas in short form too;
3. and when even that cannot make it fit, does not send it: the run ends with a
   visible error naming the model, the room it really has and what is using it,
   carried by the same ``deerflow_error_fallback`` marker the LLM error handler
   uses, so the run is recorded as failed rather than as a confident answer to a
   truncated prompt.

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

from deerflow.utils.context_budget import REQUEST_FIT_SHARE, ContextBudget, estimate_tokens, resolve_context_budget

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
_SAFETY_MARGIN = REQUEST_FIT_SHARE
# Short-form tool schemas: a tool's description keeps its opening sentences up
# to this many characters, a parameter's up to the second. What a tool does and
# what each argument means survive; worked examples and long caveats do not.
_SHORT_TOOL_DESCRIPTION_CHARS = 280
_SHORT_PARAMETER_DESCRIPTION_CHARS = 120
# JSON-schema keywords whose values are schemas, so a short form recurses into
# them. Everything else (enum, default, const, examples, required) is data and
# is copied untouched — a parameter that happens to be named "title" or
# "description" lives under "properties" and is kept.
_SCHEMA_MAP_KEYWORDS = ("properties", "patternProperties", "$defs", "definitions")
_SCHEMA_LIST_KEYWORDS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SCHEMA_KEYWORDS = ("items", "additionalProperties", "not", "if", "then", "else", "contains")


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


def _shorten(text: str, limit: int) -> str:
    """The opening sentences of *text* within *limit* characters, whitespace collapsed."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sentence_end = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("; "))
    if sentence_end >= limit // 3:
        return cut[: sentence_end + 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(" ,;:") + "…"


def _without_null_option(node: dict[str, Any]) -> dict[str, Any]:
    """``anyOf: [T, {"type": "null"}]`` with ``default: null`` is how pydantic spells
    an optional argument. The model needs only ``T``: leaving the argument out
    means the same, and the call is still validated against the full schema."""
    for keyword in ("anyOf", "oneOf"):
        options = node.get(keyword)
        if isinstance(options, list) and len(options) == 2 and {"type": "null"} in options:
            other = next(option for option in options if option != {"type": "null"})
            if isinstance(other, dict):
                rest = {key: value for key, value in node.items() if key != keyword and not (key == "default" and value is None)}
                return {**other, **rest}
    return node


def _short_schema(node: Any) -> Any:
    """A JSON schema with its description text shortened, its titles dropped and
    nullable optionals reduced to their type."""
    if not isinstance(node, dict):
        return node
    node = _without_null_option(node)
    short: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue
        if key == "description" and isinstance(value, str):
            short[key] = _shorten(value, _SHORT_PARAMETER_DESCRIPTION_CHARS)
        elif key in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            short[key] = {name: _short_schema(schema) for name, schema in value.items()}
        elif key in _SCHEMA_LIST_KEYWORDS and isinstance(value, list):
            short[key] = [_short_schema(schema) for schema in value]
        elif key in _SCHEMA_KEYWORDS:
            short[key] = _short_schema(value)
        else:
            short[key] = value
    return short


def short_tool_schema(tool: Any) -> Any:
    """Return *tool* as a short-form OpenAI function schema, or unchanged.

    The name and the parameter structure are exactly the bound tool's, so a call
    the model makes against the short form validates against the real tool. A
    provider built-in tool (a dict that is not a ``function`` schema) and a tool
    whose schema cannot be rendered are returned as they are.
    """
    try:
        if isinstance(tool, dict):
            if tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
                return tool
            schema = tool
        else:
            from langchain_core.utils.function_calling import convert_to_openai_tool

            schema = convert_to_openai_tool(tool)
    except Exception:
        return tool
    function = dict(schema["function"])
    if isinstance(function.get("description"), str):
        function["description"] = _shorten(function["description"], _SHORT_TOOL_DESCRIPTION_CHARS)
    if isinstance(function.get("parameters"), dict):
        function["parameters"] = _short_schema(function["parameters"])
    return {**schema, "function": function}


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


def _refusal(model: str, budget: ContextBudget, *, limit: int, total: int, fixed: int, tool_count: int) -> str:
    """Say what the model really has room for, what is using it, and the fix that applies.

    The room is stated the way the guard computes it — window, reply
    reservation, estimating margin — because quoting the window alone reads as a
    bug when the request is smaller than it. When the system prompt and tool
    schemas take most of it, a new chat cannot help, so the advice says so.
    """
    if budget.reserved_output > 0:
        room = (
            f"{model} has room for about {limit:,} prompt tokens: its {budget.context_window:,}-token window leaves "
            f"{budget.prompt_tokens:,} after the {budget.reserved_output:,} kept for the reply, and 10% of that is held back "
            "because the count is an estimate."
        )
    else:
        room = f"{model} has room for about {limit:,} prompt tokens: 90% of its {budget.prompt_tokens:,}-token window, because the count is an estimate."
    setup = f"{fixed:,} of that is the system prompt and {tool_count} tool definition{'s' if tool_count != 1 else ''}"
    if fixed * 2 >= total:
        return (
            f"Not sent: this request needs about {total:,} tokens, and {setup}, before any of the conversation. {room} "
            "Sending it anyway would make the model silently drop the start of it: its instructions and your question. "
            "Give the model a larger window (num_ctx in its config.yaml entry, or ollama.vram_gb so the launch sync sizes it), "
            "switch off tools or MCP servers this chat does not need, or switch to a model with a larger window."
        )
    return (
        f"This conversation no longer fits {model}: the next request needs about {total:,} tokens ({setup}). {room} "
        "It was not sent, because the model would have silently lost the start of it: the instructions and your question. "
        "Compact this chat with /compact, start a new one, or switch to a model with a larger context window."
    )


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
        original_tools = list(request.tools or ())
        tools = original_tools
        if budget.is_small and tools:
            tools = [short_tool_schema(tool) for tool in tools]
        messages = list(request.messages)
        costs = [_message_tokens(message) for message in messages]
        fixed = estimate_request_tokens(request.override(messages=[], tools=tools))
        total = fixed + sum(costs)
        if total <= limit:
            return request.override(tools=tools) if tools is not original_tools else request

        # Everything after the last assistant message is what the model is about
        # to read; only tool results before it may go, oldest first.
        last_ai = max((i for i, message in enumerate(messages) if isinstance(message, AIMessage)), default=-1)
        can_analyze = any(_tool_name(tool) == "analyze_document" for tool in original_tools)
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

        # A larger window keeps full tool guidance while it can; short form is
        # the last thing tried before refusing.
        if total > limit and tools is original_tools and tools:
            tools = [short_tool_schema(tool) for tool in tools]
            fixed = estimate_request_tokens(request.override(messages=[], tools=tools))
            total = fixed + sum(costs)

        model = _model_label(request.model)
        if total <= limit:
            shortened = " and sent tool schemas in short form" if tools is not original_tools else ""
            logger.info("Context guard: removed %d earlier tool result(s)%s so a request to %s fits its %d-token prompt space", elided, shortened, model, window)
            return request.override(messages=messages, tools=tools)

        content = _refusal(model, budget, limit=limit, total=total, fixed=fixed, tool_count=len(tools))
        logger.warning("Context guard: refused a request to %s (~%d tokens, ~%d of them system prompt and tool schemas; room for %d)", model, total, fixed, limit)
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
