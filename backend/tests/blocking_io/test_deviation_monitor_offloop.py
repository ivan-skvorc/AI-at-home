"""Regression anchor: a deviation-monitor check keeps blocking work off the event loop.

The check runs inside the lead's ``after_model`` on the loop that serves the
run. Authorizing the monitor model (provider resolution can read files) and
building it (provider construction can read local credentials) both go through
``run_assembly``; measuring the evidence is pure computation.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.deviation_monitor_middleware import STATE_CHANNEL, DeviationMonitorMiddleware
from deerflow.authz.provider import AuthzDecision, AuthzReason
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig

pytestmark = pytest.mark.asyncio


class _AllowAll:
    def authorize(self, request):
        return AuthzDecision(allow=True, reasons=[AuthzReason(code="authz.allowed")])


async def test_a_check_authorizes_builds_and_asks_off_the_loop(monkeypatch) -> None:
    monkeypatch.setattr("deerflow.authz.runtime.resolve_authorization_provider", lambda config: _AllowAll())
    verdict = json.dumps({"verdict": "on_task", "drift_kind": "none", "reason": "It reads the report for the figure.", "restated_task": "Find the figure."})
    app_config = AppConfig(
        models=[ModelConfig(name="judge", model="judge", use="langchain_core.language_models.fake_chat_models:FakeListChatModel", responses=[verdict], context_window=8_192)],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(enabled=True),
    )
    monitor = DeviationMonitorMiddleware.from_app_config(app_config)
    runtime = type("Runtime", (), {})()
    runtime.context = {"thread_id": "t1", "run_id": "r1", "user_id": "u1", "deviation_monitor": {"enabled": True, "model": "judge", "cadence": {"mode": "steps", "every": 1}}}
    state = {"messages": [HumanMessage(content="Find the Q3 EMEA revenue in the report.")]}

    assert (await monitor.abefore_agent(state, runtime))[STATE_CHANNEL]["status"] == "on_track"
    await monitor.abefore_model(state, runtime)
    state["messages"].append(AIMessage(content="Reading the report.", tool_calls=[{"name": "read_file", "args": {"path": "/r.pdf"}, "id": "c1", "type": "tool_call"}]))
    update = await monitor.aafter_model(state, runtime)
    assert update[STATE_CHANNEL]["status"] == "on_track" and update[STATE_CHANNEL]["reason"] == "It reads the report for the figure."
