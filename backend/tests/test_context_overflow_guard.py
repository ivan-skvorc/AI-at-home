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
- on a small window tool schemas always go out in short form (same names and
  parameters, shorter text), and on a large one only as the last step before a
  refusal (FORK.md §47);
- a request that still cannot fit is never sent: the run ends with a visible
  error naming the model, the room it really has, and — when the system prompt
  and tools are what fills it — the fix that applies, not "start a new chat";
- compaction's token trigger follows the run model's window, as a ceiling, and
  on a small window leaves room for the fixed part of the request.
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
# 24,576 tokens of prompt space, of which the guard fills 90%.
LOCAL = SimpleNamespace(model="qwen3:8b", num_ctx=32_768, num_predict=8_192)
PROMPT_TOKENS = 24_576
LIMIT = int(PROMPT_TOKENS * 0.9)
# Above the small-window line: full tool guidance until it would not fit.
LARGE = SimpleNamespace(model="qwen3:32b", num_ctx=131_072, num_predict=8_192)
LARGE_LIMIT = int((131_072 - 8_192) * 0.9)
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
    # ~75K tokens of tool schema leave too little room for two reads that
    # would fit comfortably without them.
    tools = [_schema_tool(i, 30_000) for i in range(10)]
    request = _request([HumanMessage("q"), *_read(1, 160_000), *_read(2, 16_000)], model=LARGE, tools=tools)
    assert estimate_request_tokens(_request(request.messages, model=LARGE)) < LARGE_LIMIT
    assert estimate_request_tokens(request) > LARGE_LIMIT

    sent, _ = await _send(request, asynchronous)

    assert estimate_request_tokens(sent) <= LARGE_LIMIT
    assert sent.messages[2].content.startswith(ELIDED_TOOL_RESULT_PREFIX)
    # analyze_document is not bound here, so the note must not send the model after it.
    assert "analyze_document" not in sent.messages[2].content
    # A large window keeps its full tool guidance while the request fits with it.
    assert sent.tools == tools


def _long_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file to the workspace. " + "Worked example with caveats. " * 200,
            "parameters": {
                "type": "object",
                "title": "WriteFileArgs",
                "properties": {
                    "path": {"type": "string", "title": "Path", "description": "Where to write it. " + "More detail. " * 60},
                    # A parameter that happens to be called "title" is a parameter, not a schema title.
                    "title": {"type": "string", "description": "Document title."},
                    "mode": {"anyOf": [{"type": "string", "enum": ["w", "a"], "title": "Mode"}, {"type": "null"}], "default": "w"},
                },
                "required": ["path", "title"],
            },
        },
    }


@pytest.mark.anyio
@ASYNC
async def test_a_small_window_always_sends_tool_schemas_in_short_form(asynchronous):
    # The reported case was a brand-new chat: ~8K tokens of full tool schemas
    # is a third of a synced 32K entry before the user has typed anything.
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    class LookupArgs(BaseModel):
        city: str = Field(description="The city to look up. " + "Background the model does not need. " * 10)
        units: str = Field(default="metric", description="metric or imperial.")

    lookup = StructuredTool.from_function(
        func=lambda city, units="metric": city,
        name="lookup",
        description="Look up the weather for a city. " + "This paragraph is long background the model does not need every turn. " * 20,
        args_schema=LookupArgs,
    )

    original = _long_tool()
    request = _request([HumanMessage("hi")], tools=[original, lookup])
    assert estimate_request_tokens(request) < LIMIT, "it fits either way; small windows shorten anyway"

    sent, _ = await _send(request, asynchronous)

    short, short_lookup = sent.tools
    function = short["function"]
    assert function["name"] == "write_file"
    assert function["description"].startswith("Write a file to the workspace.") and len(function["description"]) <= 280
    params = function["parameters"]
    assert set(params["properties"]) == {"path", "title", "mode"} and params["required"] == ["path", "title"]
    assert "title" not in params and "title" not in params["properties"]["path"]
    # An optional argument keeps its type, enum and a real default; the null branch goes.
    assert params["properties"]["mode"] == {"type": "string", "enum": ["w", "a"], "default": "w"}
    assert len(params["properties"]["path"]["description"]) <= 120
    # A LangChain tool is rendered the same way, under its own name.
    assert short_lookup["function"]["name"] == "lookup" and set(short_lookup["function"]["parameters"]["properties"]) == {"city", "units"}
    assert len(short_lookup["function"]["description"]) <= 280
    assert estimate_request_tokens(sent) < estimate_request_tokens(request)
    # Request view only: the bound tools are untouched.
    assert original == _long_tool() and lookup.name == "lookup" and len(lookup.description) > 280


@pytest.mark.anyio
@ASYNC
async def test_a_large_window_shortens_tool_schemas_before_refusing(asynchronous):
    tools = [_schema_tool(i, 50_000) for i in range(10)]  # ~125K tokens in full
    request = _request([HumanMessage("q")], model=LARGE, tools=tools)

    sent, _ = await _send(request, asynchronous)

    assert sent is not None, "short form fits, so the request goes out"
    assert estimate_request_tokens(sent) <= LARGE_LIMIT
    assert [tool["function"]["name"] for tool in sent.tools] == [f"tool_{i}" for i in range(10)]


@pytest.mark.anyio
@ASYNC
async def test_a_request_whose_setup_fills_the_window_names_the_real_limit_and_cause(asynchronous):
    # The reported message said "needs about 22,910 tokens, and the window leaves
    # 24,576" — a refusal that read as a bug, because the limit enforced is 90%
    # of that. And it told the user to start a new chat, which would be just as
    # large: the system prompt and tool schemas were what filled the window.
    request = _request([HumanMessage("hi")], system="s" * 100_000)

    sent, result = await _send(request, asynchronous)

    assert sent is None
    assert f"{LIMIT:,}" in result.content and f"{PROMPT_TOKENS:,}" in result.content
    assert "32,768" in result.content and "8,192" in result.content
    assert "system prompt and 0 tool definitions" in result.content
    assert "num_ctx" in result.content
    assert "new chat" not in result.content and "new one" not in result.content


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
    assert f"{PROMPT_TOKENS:,}" in result.content and f"{LIMIT:,}" in result.content
    # The conversation is what outgrew the window here, so compaction is the fix.
    assert "/compact" in result.content
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
        # Half the prompt space (12,288) was above what the guard leaves for
        # messages once the system prompt and tool schemas ride along, so a long
        # text-only chat was refused before compaction ever fired: 90% of 24,576
        # less the 12,000-token allowance for the fixed part of the request.
        model = MagicMock(num_ctx=32_768, num_predict=8_192)
        assert self._trigger(monkeypatch, model) == ("tokens", 10_118)

    def test_a_mid_sized_local_window_keeps_half_its_prompt_space(self, monkeypatch):
        model = MagicMock(num_ctx=65_536, num_predict=8_192)
        assert self._trigger(monkeypatch, model) == ("tokens", 28_672)

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
