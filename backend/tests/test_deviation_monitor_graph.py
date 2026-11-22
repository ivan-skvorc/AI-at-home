"""The deviation monitor inside a real agent graph and in the lead chain.

Unit tests drive the hooks one by one; this file checks what only the graph
shows: a stop really keeps the drifting tool from running and ends the run, a
retry really sends the model back with the hidden reminder, and the monitor
sits where its ordering promises hold (outer of the completion review and the
context-window guard, so the guard measures the reminder and the review's and
the to-do list's reverse-order ``after_model`` run first).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.middlewares.deviation_monitor_middleware import ACTION_MARKER_KEY, REMINDER_MESSAGE_NAME, STATE_CHANNEL, DeviationMonitorMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.deviation_monitor_config import DeviationMonitorConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.token_usage_config import TokenUsageConfig

REQUEST = "Find the Q3 revenue figure for the EMEA region in the attached annual report."
MONITOR = "judge-small"
READS: list[str] = []


@tool
def read_pages(path: str) -> str:
    """Read pages of a document."""
    READS.append(path)
    return "pages 1-400"


class _ScriptedModel(BaseChatModel):
    """The lead's model: scripted responses, every request recorded."""

    responses: list[AIMessage]
    seen: list[list[Any]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


class _Judge:
    def __init__(self, *verdicts: str) -> None:
        self.verdicts = list(verdicts)

    async def ainvoke(self, messages, config=None):
        verdict = self.verdicts.pop(0)
        reason = "It is reading the whole report page by page instead of finding one figure." if verdict == "drifting" else "It answers the request."
        return AIMessage(content=json.dumps({"verdict": verdict, "drift_kind": "goal_substitution" if verdict == "drifting" else "none", "reason": reason, "restated_task": "Find the EMEA Q3 revenue."}))


def _app_config(**overrides) -> AppConfig:
    return AppConfig(
        models=[ModelConfig(name="lead", model="lead", use="langchain_openai:ChatOpenAI"), ModelConfig(name=MONITOR, model=MONITOR, use="langchain_openai:ChatOpenAI", context_window=32_768)],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        token_usage=TokenUsageConfig(enabled=False),
        **overrides,
    )


def _graph(model: _ScriptedModel, judge: _Judge):
    monitor = DeviationMonitorMiddleware(DeviationMonitorConfig(), app_config=_app_config(), model_factory=lambda name: judge)
    return create_agent(model=model, tools=[read_pages], middleware=[monitor])


def _context(**extra) -> dict:
    return {"thread_id": "t1", "run_id": "r1", "deviation_monitor": {"enabled": True, "model": MONITOR, "cadence": {"mode": "steps", "every": 1}}, **extra}


def _read_call(call_id: str) -> AIMessage:
    return AIMessage(content="I'll read all 400 pages myself.", tool_calls=[{"name": "read_pages", "args": {"path": "/mnt/user-data/uploads/report.pdf"}, "id": call_id, "type": "tool_call"}])


def test_a_confirmed_drift_ends_the_run_before_the_drifting_tool_runs() -> None:
    READS.clear()
    model = _ScriptedModel(responses=[_read_call("c1")], seen=[])
    result = asyncio.run(_graph(model, _Judge("drifting", "drifting")).ainvoke({"messages": [HumanMessage(content=REQUEST)]}, context=_context()))

    assert READS == [] and len(model.seen) == 1
    final = result["messages"][-1]
    assert isinstance(final, AIMessage) and final.tool_calls == []
    assert "Deviation monitor stopped this run" in final.content and final.additional_kwargs[ACTION_MARKER_KEY]["action"] == "stopped"
    assert result[STATE_CHANNEL]["status"] == "stopped" and result[STATE_CHANNEL]["last_checked_step"] == 1


def test_a_subagent_mode_retries_once_with_the_hidden_reminder() -> None:
    READS.clear()
    model = _ScriptedModel(responses=[_read_call("c1"), AIMessage(content="EMEA Q3 revenue was 4.2M (found by a subagent).")], seen=[])
    result = asyncio.run(_graph(model, _Judge("drifting", "drifting", "on_task")).ainvoke({"messages": [HumanMessage(content=REQUEST)]}, context=_context(subagent_enabled=True)))

    assert READS == [] and len(model.seen) == 2
    reminder = model.seen[1][-1]
    assert isinstance(reminder, HumanMessage) and reminder.name == REMINDER_MESSAGE_NAME and reminder.additional_kwargs == {"hide_from_ui": True}
    # The reminder is request-only: it never enters the thread state.
    assert not any(getattr(message, "name", None) == REMINDER_MESSAGE_NAME for message in result["messages"])
    held = next(message for message in result["messages"] if isinstance(message, AIMessage) and ACTION_MARKER_KEY in message.additional_kwargs)
    assert held.tool_calls == [] and held.additional_kwargs[ACTION_MARKER_KEY]["action"] == "retrying"
    assert result["messages"][-1].content.startswith("EMEA Q3 revenue was 4.2M")
    assert result[STATE_CHANNEL]["status"] == "on_track" and result[STATE_CHANNEL]["checks"] == 2


class TestLeadChain:
    def _stack(self, app_config: AppConfig):
        from deerflow.agents.lead_agent.agent import build_middlewares

        return build_middlewares(config={"configurable": {}}, model_name="lead", app_config=app_config)

    def test_it_sits_right_outer_of_the_completion_review_and_outer_of_the_guard(self) -> None:
        from deerflow.agents.middlewares.completion_review_middleware import CompletionReviewMiddleware
        from deerflow.agents.middlewares.context_window_guard_middleware import ContextWindowGuardMiddleware

        stack = self._stack(_app_config())
        monitor = next(i for i, m in enumerate(stack) if isinstance(m, DeviationMonitorMiddleware))
        review = next(i for i, m in enumerate(stack) if isinstance(m, CompletionReviewMiddleware))
        guard = next(i for i, m in enumerate(stack) if isinstance(m, ContextWindowGuardMiddleware))
        assert monitor == review - 1 and monitor < guard

    def test_without_the_review_it_still_precedes_the_todo_list_and_the_guard(self) -> None:
        from deerflow.agents.lead_agent.agent import build_middlewares
        from deerflow.agents.middlewares.context_window_guard_middleware import ContextWindowGuardMiddleware
        from deerflow.agents.middlewares.todo_middleware import TodoMiddleware
        from deerflow.config.harness_guard_config import HarnessGuardConfig

        stack = build_middlewares(config={"configurable": {"is_plan_mode": True}}, model_name="lead", app_config=_app_config(harness_guard=HarnessGuardConfig(verify_before_finish=False)))
        monitor = next(i for i, m in enumerate(stack) if isinstance(m, DeviationMonitorMiddleware))
        todo = next(i for i, m in enumerate(stack) if isinstance(m, TodoMiddleware))
        guard = next(i for i, m in enumerate(stack) if isinstance(m, ContextWindowGuardMiddleware))
        assert monitor == todo - 1 and monitor < guard

    def test_the_operator_switch_leaves_it_out(self) -> None:
        stack = self._stack(_app_config(deviation_monitor=DeviationMonitorConfig(enabled=False)))
        assert not any(isinstance(m, DeviationMonitorMiddleware) for m in stack)

    def test_subagents_never_get_it(self) -> None:
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        stack = build_subagent_runtime_middlewares(app_config=_app_config(), model_name="lead")
        assert not any(isinstance(m, DeviationMonitorMiddleware) for m in stack)
