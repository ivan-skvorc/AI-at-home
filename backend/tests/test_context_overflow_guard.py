"""Tests for the context-window guard (fork feature, roadmap item 34).

Ollama does not reject a prompt longer than ``num_ctx``: it truncates it and
keeps the most recent tokens, so the system prompt, the tool rules and the
user's question are the first things lost. Every protection the fork had was per
value (each tool result clamped to a share of the window) or late (compaction at
32,000 tokens, the whole window of a synced Ollama entry); none bounded the
*sum* of what one request carries. A local model asked about a cookbook read on
until the window was gone and ended the run by creating a GitHub repository.

The properties under test:
- a request that fits is sent untouched, and an unknown window is a no-op;
- a request that does not fit loses its *oldest* tool results first, in the
  request view only — the system prompt, the question and the result the model
  is waiting for always survive, and stored history is never modified;
- tool schemas count against the window, because they ride along on every call;
- a request that still cannot fit is never sent: the run ends with a visible
  error naming the model and its window;
- compaction's token trigger follows the run model's window, as a ceiling.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.agents.middlewares.context_window_guard_middleware import (
    ELIDED_TOOL_RESULT_PREFIX,
    ContextWindowGuardMiddleware,
    estimate_request_tokens,
)
from deerflow.utils.context_budget import estimate_tokens

# A synced Ollama entry: 32,768 total with 8,192 reserved for the answer leaves
# 24,576 tokens of prompt space.
LOCAL = SimpleNamespace(model="qwen3:8b", num_ctx=32_768, num_predict=8_192)
PROMPT_TOKENS = 24_576
NO_CONFIG = SimpleNamespace(models=[])
ANALYZE_DOCUMENT = {"type": "function", "function": {"name": "analyze_document", "description": "Read a long document in parts.", "parameters": {"type": "object", "properties": {}}}}


def _guard() -> ContextWindowGuardMiddleware:
    return ContextWindowGuardMiddleware(app_config=NO_CONFIG)


def _request(messages, *, model=LOCAL, tools=(), system="You are DeerFlow.") -> ModelRequest:
    return ModelRequest(model=model, messages=list(messages), system_message=SystemMessage(content=system), tools=list(tools), state={})


def _read(index: int, chars: int) -> list:
    call = AIMessage(content="", tool_calls=[{"id": f"c{index}", "name": "read_file", "args": {"path": "/mnt/user-data/uploads/book.html", "start_line": index}}])
    return [call, ToolMessage(content="x" * chars, tool_call_id=f"c{index}", name="read_file")]


def _schema_tool(index: int, description_chars: int) -> dict:
    return {"type": "function", "function": {"name": f"tool_{index}", "description": "d" * description_chars, "parameters": {"type": "object", "properties": {}}}}


async def _send(request: ModelRequest, asynchronous: bool):
    """Run the guard and return (what reached the model, what came back)."""
    sent: list[ModelRequest] = []

    def handler(req):
        sent.append(req)
        return AIMessage(content="ok")

    async def ahandler(req):
        return handler(req)

    if asynchronous:
        result = await _guard().awrap_model_call(request, ahandler)
    else:
        result = await asyncio.to_thread(_guard().wrap_model_call, request, handler)
    return (sent[0] if sent else None), result


ASYNC = pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])


@pytest.mark.anyio
@ASYNC
async def test_a_request_that_fits_is_sent_untouched(asynchronous):
    request = _request([HumanMessage("find easy recipes"), *_read(1, 4_000)])
    sent, _ = await _send(request, asynchronous)
    assert sent is request


@pytest.mark.anyio
@ASYNC
async def test_an_unknown_window_changes_nothing_however_large(asynchronous):
    request = _request([HumanMessage("z" * 400_000)], model=SimpleNamespace(model="mystery-model"))
    sent, _ = await _send(request, asynchronous)
    assert sent is request


@pytest.mark.anyio
@ASYNC
async def test_old_tool_results_are_elided_until_the_request_fits(asynchronous):
    question = HumanMessage("find a few recipes a beginner could manage")
    messages = [question, *_read(1, 40_000), *_read(2, 40_000), *_read(3, 20_000)]
    request = _request(messages, tools=[ANALYZE_DOCUMENT])
    assert estimate_request_tokens(request) > PROMPT_TOKENS

    sent, _ = await _send(request, asynchronous)

    assert estimate_request_tokens(sent) <= PROMPT_TOKENS
    assert sent.system_message.content == "You are DeerFlow."
    assert sent.messages[0] is question
    assert sent.messages[-1].content == "x" * 20_000, "the result the model is waiting for must survive"
    elided = [m for m in sent.messages if isinstance(m, ToolMessage) and m.content.startswith(ELIDED_TOOL_RESULT_PREFIX)]
    assert [m.tool_call_id for m in elided] == ["c1"], "only the oldest result needed to go"
    assert "analyze_document" in elided[0].content
    # Request view only: the conversation's stored messages keep their content.
    assert messages[2].content == "x" * 40_000


@pytest.mark.anyio
@ASYNC
async def test_tool_schemas_count_against_the_window(asynchronous):
    # ~20K tokens of tool schema leave too little room for two reads that
    # would fit comfortably without them.
    tools = [_schema_tool(i, 8_000) for i in range(10)]
    request = _request([HumanMessage("q"), *_read(1, 20_000), *_read(2, 4_000)], tools=tools)
    assert estimate_request_tokens(_request(request.messages)) < PROMPT_TOKENS

    sent, _ = await _send(request, asynchronous)

    assert estimate_request_tokens(sent) <= PROMPT_TOKENS
    assert sent.messages[2].content.startswith(ELIDED_TOOL_RESULT_PREFIX)
    # analyze_document is not bound here, so the note must not send the model after it.
    assert "analyze_document" not in sent.messages[2].content
    assert sent.tools == tools


@pytest.mark.anyio
@ASYNC
async def test_a_request_that_cannot_fit_is_never_sent(asynchronous):
    request = _request([HumanMessage("summarise this: " + "y" * 120_000)])

    sent, result = await _send(request, asynchronous)

    assert sent is None
    assert isinstance(result, AIMessage)
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_type"] == "context_window_exceeded"
    assert "qwen3:8b" in result.content
    assert f"{PROMPT_TOKENS:,}" in result.content
    assert result.additional_kwargs["error_detail"] == result.content


def test_cjk_text_is_not_undercounted():
    # Four characters per token is right for English prose and four times too
    # optimistic for Chinese, where a character is about a token.
    assert estimate_tokens("食谱" * 500) >= 1_000
    assert estimate_tokens("a" * 1_000) == 250
    assert estimate_tokens("") == 0


class TestCompactionTrigger:
    """Compaction must fire before the window is full, not after."""

    def _trigger(self, monkeypatch, model) -> object:
        from deerflow.agents.middlewares.summarization_middleware import create_summarization_middleware
        from deerflow.config.memory_config import MemoryConfig
        from deerflow.config.summarization_config import ContextSize, SummarizationConfig

        model.with_config.return_value = model
        monkeypatch.setattr("deerflow.agents.middlewares.summarization_middleware.create_chat_model", lambda **kw: model)
        # The shipped config.example.yaml trigger.
        summarization = SummarizationConfig(enabled=True, trigger=ContextSize(type="tokens", value=32_000))
        app_config = SimpleNamespace(summarization=summarization, memory=MemoryConfig(enabled=False), models=[])
        return create_summarization_middleware(app_config=app_config).trigger

    def test_a_small_window_lowers_the_token_trigger(self, monkeypatch):
        model = MagicMock(num_ctx=32_768, num_predict=8_192)
        assert self._trigger(monkeypatch, model) == ("tokens", 12_288)

    def test_a_large_window_keeps_the_configured_trigger(self, monkeypatch):
        model = MagicMock(num_ctx=200_000, num_predict=8_192)
        assert self._trigger(monkeypatch, model) == ("tokens", 32_000)

    def test_an_unknown_window_keeps_the_configured_trigger(self, monkeypatch):
        model = MagicMock()  # every attribute is a Mock, never a usable window
        assert self._trigger(monkeypatch, model) == ("tokens", 32_000)


class TestWiring:
    def _sandbox_config(self):
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        return AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))

    def test_the_lead_chain_guards_right_after_the_last_built_in_request_transform(self):
        from deerflow.agents.lead_agent.agent import build_middlewares
        from deerflow.agents.middlewares.model_content_compatibility_middleware import ModelContentCompatibilityMiddleware

        stack = build_middlewares(config={"configurable": {}}, model_name="gpt-4o", app_config=self._sandbox_config())
        guard = next(i for i, m in enumerate(stack) if isinstance(m, ContextWindowGuardMiddleware))
        assert isinstance(stack[guard - 1], ModelContentCompatibilityMiddleware)

    def test_the_subagent_chain_is_guarded_too(self):
        from deerflow.agents.middlewares.model_content_compatibility_middleware import ModelContentCompatibilityMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        stack = build_subagent_runtime_middlewares(app_config=self._sandbox_config(), model_name="gpt-4o")
        guard = next(i for i, m in enumerate(stack) if isinstance(m, ContextWindowGuardMiddleware))
        assert isinstance(stack[guard - 1], ModelContentCompatibilityMiddleware)
