"""A design-page run, end to end, from the page's action to what the model receives (FORK.md §58).

Real: the Gateway app and its lifespan, registration with the session cookie and
CSRF, the ``plugins:`` records ``config.example.yaml`` ships (workflows, cad,
cad-preview, cad-design) loaded by the real loader, the plugin action route the
Designs page calls, the AgentRuns handle it hands the action, run admission, the
run worker, the lead agent with its whole middleware chain (contributed
middleware wrapped as the host injects it), the ``scad_draft`` tool and the
design store. Fake: only the chat model, which records the tools and the system
message of every call and calls ``scad_draft`` whenever it is offered.

An owner's design run built the part with ``cad_build`` and the page's preview
stayed empty. The host's isolation wrapper had dropped the request the
cad-design middleware hands on, so the drafting brief never reached the model,
and ``scad_draft`` stayed on every ordinary chat. The middleware's own tests
called it directly, past the wrapper, and passed.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

pytestmark = pytest.mark.no_auto_user

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL = "fake-test-model"
SCAD = "w = 30; // [10:1:60]\nd = 20;\nh = 10;\ndifference() {\n  cube([w, d, h]);\n  translate([w / 2, d / 2, h - 5]) cylinder(h = 5.01, r1 = 0, r2 = 2.5, $fn = 48);\n}\n"
CONFIG = f"""\
log_level: info
models:
  - name: {MODEL}
    display_name: Fake Test Model
    use: langchain_openai:ChatOpenAI
    model: gpt-4o-mini
    api_key: $OPENAI_API_KEY
    base_url: $OPENAI_API_BASE
    supports_thinking: true
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
title:
  enabled: false
memory:
  enabled: false
database:
  backend: sqlite
run_events:
  backend: memory
"""

#: Every model call of the test: the bound tool names and the system message's text.
CALLS: list[dict[str, Any]] = []


def _name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        function = tool.get("function")
        return function.get("name") if isinstance(function, dict) else tool.get("name")
    return getattr(tool, "name", None)


def _cad_build() -> str:
    from deerflow.extensions.plugin_tools import plugin_tool_name

    return plugin_tool_name("cad", "cad_build")


def _scad_draft() -> str:
    from deerflow.extensions.plugin_tools import plugin_tool_name

    return plugin_tool_name("cad-design", "scad_draft")


class RecordingModel(BaseChatModel):
    """Records each call; drafts once with scad_draft when it is offered, then answers."""

    bound: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any):  # type: ignore[override]
        return self.model_copy(update={"bound": [_name(tool) for tool in tools]})

    def _respond(self, messages: list[BaseMessage]) -> ChatResult:
        system = next((message.content for message in messages if isinstance(message, SystemMessage)), "")
        CALLS.append({"tools": list(self.bound), "system": system if isinstance(system, str) else str(system)})
        drafted = any(message.type == "tool" for message in messages)
        if not drafted and _scad_draft() in self.bound:
            call = {"name": _scad_draft(), "args": {"code": SCAD, "note": "Block with a cone"}, "id": "call_scad_1", "type": "tool_call"}
            answer = AIMessage(content="Drafting the block.", tool_calls=[call])
        else:
            answer = AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=answer)])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._respond(messages)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._respond(messages)


def _reset_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """The process caches a Gateway start reads; monkeypatch restores them afterwards."""
    from app.gateway import deps as deps_module
    from deerflow.config import (
        acp_config,
        agents_api_config,
        checkpointer_config,
        guardrails_config,
        memory_config,
        stream_bridge_config,
        subagents_config,
        summarization_config,
        title_config,
        tool_search_config,
    )
    from deerflow.config import app_config as app_config_module
    from deerflow.config import extensions_config as extensions_config_module
    from deerflow.config import paths as paths_module
    from deerflow.persistence import engine as engine_module

    for module, attr in (
        (title_config, "_title_config"),
        (summarization_config, "_summarization_config"),
        (memory_config, "_memory_config"),
        (agents_api_config, "_agents_api_config"),
        (subagents_config, "_subagents_config"),
        (tool_search_config, "_tool_search_config"),
        (guardrails_config, "_guardrails_config"),
        (checkpointer_config, "_checkpointer_config"),
        (stream_bridge_config, "_stream_bridge_config"),
        (acp_config, "_acp_agents"),
    ):
        monkeypatch.setattr(module, attr, getattr(module, attr), raising=False)
    for module, attr, value in (
        (app_config_module, "_app_config", None),
        (app_config_module, "_app_config_path", None),
        (app_config_module, "_app_config_mtime", None),
        (app_config_module, "_app_config_is_custom", False),
        (extensions_config_module, "_extensions_config", None),
        (paths_module, "_paths_singleton", None),
        (paths_module, "_paths", None),
        (engine_module, "_engine", None),
        (engine_module, "_session_factory", None),
        (deps_module, "_cached_local_provider", None),
        (deps_module, "_cached_repo", None),
    ):
        monkeypatch.setattr(module, attr, value, raising=False)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A started Gateway with the shipped plugin records, signed in, and its CSRF token."""
    from starlette.testclient import TestClient

    from deerflow.extensions import reset_loaded_extensions, reset_runtime_diagnostics

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key-not-used")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")
    plugins = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))["plugins"]
    assert {record["name"] for record in plugins} >= {"workflows", "cad-design"}
    config = tmp_path / "config.yaml"
    config.write_text(CONFIG + yaml.safe_dump({"plugins": plugins}, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config))
    extensions = tmp_path / "extensions_config.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    _reset_singletons(monkeypatch)

    from deerflow.config import app_config as app_config_module

    app_config_module.get_app_config().database.sqlite_dir = str(home / "db")
    from app.gateway.app import create_app

    CALLS.clear()
    # The Gateway's startup applies the configured log level to the deerflow and app
    # loggers and may lower root handler levels (apply_logging_level); left in place,
    # that INFO level leaks into later caplog assertions in the same worker.
    loggers = {name: logging.getLogger(name).level for name in ("deerflow", "app")}
    root_level, handlers = logging.root.level, {handler: handler.level for handler in logging.root.handlers}
    try:
        with patch("deerflow.agents.lead_agent.agent.create_chat_model", new=lambda *args, **kwargs: RecordingModel()), TestClient(create_app()) as test_client:
            response = test_client.post("/api/v1/auth/register", json={"email": "designer@example.com", "password": "very-strong-password-123"})
            assert response.status_code == 201, response.text
            test_client.headers["X-CSRF-Token"] = test_client.cookies.get("csrf_token")
            yield test_client
    finally:
        reset_loaded_extensions()
        reset_runtime_diagnostics()
        for name, level in loggers.items():
            logging.getLogger(name).setLevel(level)
        logging.root.setLevel(root_level)
        for handler in list(logging.root.handlers):
            if handler in handlers:
                handler.setLevel(handlers[handler])
            else:
                logging.root.removeHandler(handler)


def _action(client, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"/api/plugins/cad-design/actions/{name}", json=payload)
    assert response.status_code == 200, (name, response.status_code, response.text)
    return response.json()


def _settle(client, design_id: str, run_id: str) -> str:
    """Poll the run as the page does, until it leaves pending/running."""
    deadline = time.monotonic() + 60
    status = "pending"
    while status in ("pending", "running") and time.monotonic() < deadline:
        status = _action(client, "run_status", {"design_id": design_id, "run_id": run_id})["status"]
        if status in ("pending", "running"):
            time.sleep(0.05)
    return status


def _chat(client, context: dict[str, Any]) -> None:
    """An ordinary conversation's run on a thread of its own."""
    thread_id = str(uuid.uuid4())
    response = client.post("/api/threads", json={"thread_id": thread_id, "metadata": {}})
    assert response.status_code == 200, response.text
    body = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "A bracket, please."}]}, "context": {"model_name": MODEL, "thinking_enabled": False, **context}}
    response = client.post(f"/api/threads/{thread_id}/runs/wait", json=body)
    assert response.status_code == 200, response.text


def test_a_design_prompt_drafts_with_the_brief_and_saves_a_version(client):
    from deerflow_extension_cad_design.notes import DRAFT_BRIEF

    design = _action(client, "create_design", {"title": "Block"})["design"]
    started = _action(client, "prompt", {"design_id": design["id"], "text": "A 30 x 20 x 10 mm block with a 5 mm cone on top", "model_name": MODEL, "mode": "flash"})
    assert _settle(client, design["id"], started["run_id"]) == "success"

    assert len(CALLS) == 2, CALLS
    first, second = CALLS
    assert _scad_draft() in first["tools"]
    # Only Finalize builds CadQuery: a draft run that could call cad_build followed the
    # cad-modeling skill instead of drafting, which is the owner's empty preview.
    assert all(_cad_build() not in call["tools"] for call in CALLS)
    assert DRAFT_BRIEF in first["system"], "the drafting brief did not reach the model"
    assert "No version yet: start the file." in first["system"]
    # The version note is rebuilt for every call of the run: the draft just saved is the head.
    assert DRAFT_BRIEF in second["system"]
    assert "Head: v1 (model). Last render: not reported yet." in second["system"]

    versions = _action(client, "get_design", {"design_id": design["id"]})["versions"]
    assert [(version["seq"], version["source"], version["scad"]) for version in versions] == [(1, "model", SCAD)]


@pytest.mark.parametrize("forged", [False, True], ids=["plain", "forged-design-flag"])
def test_an_ordinary_chat_never_receives_the_drafting_tool_or_brief(client, forged):
    # A design flag the run's own thread does not back is no design run either.
    context = {"plugin_options": {"cad-design": {"design_id": "a" * 32, "phase": "draft"}}} if forged else {}
    _chat(client, context)

    assert CALLS
    for call in CALLS:
        assert _scad_draft() not in call["tools"]
        assert _cad_build() in call["tools"]
        assert "## Design page" not in call["system"]
        assert "## Design versions" not in call["system"]


def test_the_ultracode_brief_reaches_the_model(client):
    """The workflows extension appends its brief the same way, through the same wrapper."""
    pytest.importorskip("deerflow_extension_workflows")  # not installed on Windows (QuickJS)
    _chat(client, {"plugin_options": {"community.workflows": {"mode": "ultracode"}}})

    assert CALLS
    assert "## Plus Ultracode mode" in CALLS[0]["system"], CALLS[0]["system"][-400:]
