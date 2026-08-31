"""Tests for context-aware tool-output limits (fork feature).

`ToolOutputBudgetMiddleware` is the only place in the agent loop that holds both
the serving model and the tool results it produces, so it is where the fork
resolves the model's context window and lowers the character budgets to fit.
The sandbox tools have no model reference at all, so the middleware publishes
the resolved budget for the duration of each tool call and the tools read it
from there.

The properties under test:
- a small window lowers the thresholds; a large or unknown one changes nothing;
- an explicit "disabled" (0) is never turned back on by the scaling;
- the budget follows the model that actually serves the call, so a fallback or
  a routed subagent is budgeted against its own window;
- the sandbox tools' caps move with it, and a tool called outside the agent
  loop keeps its configured value.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_output_budget_middleware import (
    ToolOutputBudgetMiddleware,
    _scale_config_to_context,
)
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.sandbox.tools import _context_clamped
from deerflow.utils.context_budget import (
    COMMAND_OUTPUT_SHARE,
    READ_FILE_SHARE,
    ContextBudget,
    use_context_budget,
)

# A synced Ollama entry: 32768 total, 8192 reserved for the completion.
LOCAL = ContextBudget(context_window=32_768, reserved_output=8_192)
CLOUD = ContextBudget(context_window=200_000, reserved_output=32_000)


def _make_request(tool_name: str = "some_tool", tool_call_id: str = "tc-1", run_id: str | None = None) -> SimpleNamespace:
    context = {"run_id": run_id} if run_id else {}
    return SimpleNamespace(tool_call={"name": tool_name, "id": tool_call_id}, runtime=SimpleNamespace(state={}, context=context))


def _model_request(model, run_id: str | None = None) -> ModelRequest:
    request = ModelRequest(model=model, messages=[], tools=[], state={})
    context = {"run_id": run_id} if run_id else {}
    return request.override(runtime=SimpleNamespace(state={}, context=context))


class TestScaleConfigToContext:
    def test_local_window_lowers_the_thresholds(self):
        config = ToolOutputConfig()
        scaled = _scale_config_to_context(config, LOCAL)
        assert scaled.externalize_min_chars < config.externalize_min_chars
        assert scaled.fallback_max_chars < config.fallback_max_chars

    def test_cloud_window_keeps_every_configured_value(self):
        config = ToolOutputConfig()
        assert _scale_config_to_context(config, CLOUD) is config

    def test_unknown_window_keeps_every_configured_value(self):
        config = ToolOutputConfig()
        assert _scale_config_to_context(config, None) is config

    def test_disabled_thresholds_stay_disabled(self):
        config = ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=0)
        scaled = _scale_config_to_context(config, LOCAL)
        assert scaled.externalize_min_chars == 0
        assert scaled.fallback_max_chars == 0

    def test_head_and_tail_are_pulled_inside_a_shrunken_window(self):
        # Shipped defaults are head 8000 + tail 3000 against a 30000 window; a
        # window smaller than 11000 would otherwise "truncate" to more than the
        # budget allows.
        config = ToolOutputConfig()
        scaled = _scale_config_to_context(config, ContextBudget(context_window=8_192, reserved_output=2_048))
        assert scaled.fallback_head_chars + scaled.fallback_tail_chars < scaled.fallback_max_chars

    def test_per_tool_overrides_are_scaled_too(self):
        config = ToolOutputConfig(tool_overrides={"web_search": 40_000, "muted": 0})
        scaled = _scale_config_to_context(config, LOCAL)
        assert scaled.tool_overrides["web_search"] < 40_000
        assert scaled.tool_overrides["muted"] == 0


class TestMiddlewareObservesTheServingModel:
    def test_model_call_records_the_window(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig())
        model = SimpleNamespace(num_ctx=32_768, num_predict=8_192)
        request = _model_request(model)
        mw.wrap_model_call(request, lambda req: [])
        assert mw._budget_for(request) == LOCAL

    def test_a_model_without_a_declared_window_leaves_the_budget_unset(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig())
        request = _model_request(None)
        mw.wrap_model_call(request, lambda req: [])
        assert mw._budget_for(request) is None

    def test_the_budget_follows_a_switch_of_serving_model(self):
        # A fallback chain or a routed subagent changes the model mid-run; the
        # budget must describe the model that is actually about to be called.
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig())
        mw.wrap_model_call(_model_request(SimpleNamespace(num_ctx=32_768, num_predict=8_192)), lambda req: [])
        request = _model_request(SimpleNamespace(context_window=200_000, max_tokens=32_000))
        mw.wrap_model_call(request, lambda req: [])
        assert mw._budget_for(request) == CLOUD

    def test_tool_call_publishes_the_budget_to_the_tool(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig())
        mw.wrap_model_call(_model_request(SimpleNamespace(num_ctx=32_768, num_predict=8_192)), lambda req: [])
        seen: dict[str, int] = {}

        def handler(_request):
            seen["cap"] = _context_clamped(50_000, READ_FILE_SHARE)
            return ToolMessage(content="ok", tool_call_id="tc-1", name="some_tool")

        mw.wrap_tool_call(_make_request(), handler)
        assert seen["cap"] == LOCAL.chars(READ_FILE_SHARE)

    @pytest.mark.anyio
    async def test_async_tool_call_publishes_the_budget_too(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig())
        await mw.awrap_model_call(_model_request(SimpleNamespace(num_ctx=32_768, num_predict=8_192)), _noop_model_handler)
        seen: dict[str, int] = {}

        async def handler(_request):
            seen["cap"] = _context_clamped(50_000, READ_FILE_SHARE)
            return ToolMessage(content="ok", tool_call_id="tc-1", name="some_tool")

        await mw.awrap_tool_call(_make_request(), handler)
        assert seen["cap"] == LOCAL.chars(READ_FILE_SHARE)

    def test_the_published_budget_does_not_leak_past_the_tool_call(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig())
        mw.wrap_model_call(_model_request(SimpleNamespace(num_ctx=8_192)), lambda req: [])
        mw.wrap_tool_call(_make_request(), lambda _r: ToolMessage(content="ok", tool_call_id="tc-1", name="some_tool"))
        assert _context_clamped(50_000, READ_FILE_SHARE) == 50_000

    def test_concurrent_runs_do_not_budget_each_other(self):
        # One middleware instance serves concurrent runs on the lead agent. A
        # 200K cloud run must not lift a 32K local run's caps, or vice versa —
        # the failure is silent, and only shows up as a run that overflows.
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig())
        mw.wrap_model_call(_model_request(SimpleNamespace(num_ctx=32_768, num_predict=8_192), run_id="run-local"), lambda req: [])
        mw.wrap_model_call(_model_request(SimpleNamespace(context_window=200_000, max_tokens=32_000), run_id="run-cloud"), lambda req: [])

        seen: dict[str, int] = {}

        def handler(request):
            seen[request.runtime.context["run_id"]] = _context_clamped(50_000, READ_FILE_SHARE)
            return ToolMessage(content="ok", tool_call_id="tc-1", name="some_tool")

        mw.wrap_tool_call(_make_request(run_id="run-local"), handler)
        mw.wrap_tool_call(_make_request(run_id="run-cloud"), handler)
        assert seen["run-local"] == LOCAL.chars(READ_FILE_SHARE)
        assert seen["run-cloud"] == 50_000


async def _noop_model_handler(_request):
    return []


class TestSandboxCapsFollowTheBudget:
    def test_read_file_cap_shrinks_on_a_local_window(self):
        with use_context_budget(LOCAL):
            assert _context_clamped(50_000, READ_FILE_SHARE) == 24_576

    def test_bash_cap_shrinks_on_a_local_window(self):
        with use_context_budget(LOCAL):
            assert _context_clamped(20_000, COMMAND_OUTPUT_SHARE) == 14_745

    def test_cloud_window_keeps_the_configured_cap(self):
        with use_context_budget(CLOUD):
            assert _context_clamped(50_000, READ_FILE_SHARE) == 50_000

    def test_no_active_budget_keeps_the_configured_cap(self):
        assert _context_clamped(50_000, READ_FILE_SHARE) == 50_000

    def test_an_explicit_no_limit_is_preserved(self):
        with use_context_budget(LOCAL):
            assert _context_clamped(0, READ_FILE_SHARE) == 0
