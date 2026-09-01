"""The per-conversation internet switch (fork feature, FORK.md §27).

The composer's globe toggle sends ``internet_enabled: false`` in the run context
and the run is assembled without any tool that reaches the internet. Four
properties carry the feature, and every one of them is **silent** when broken —
the conversation keeps answering, it is just no longer offline:

* **Absent is not "off".** Only an explicit ``False`` opts out, so IM channels,
  the TUI, the scheduler and embedded callers — none of which have a composer —
  keep the operator's configured tool list. Reading a missing key as "offline"
  would take web search away from every non-web caller on the day this ships.
* **The classification fails closed.** A tool group that is not on the offline
  allowlist is dropped. Turning this into a blocklist of ``{"web", "browser"}``
  looks equivalent and passes every test that names a shipped group, while
  quietly passing the next provider group anyone adds.
* **Delegation is not an escape hatch.** The `task` tool assembles the
  subagent's toolset from the *parent's* context, so a subagent cannot be asked
  to do the browsing the lead agent may not do.
* **The notice does not ride a template placeholder.** The system prompt is
  operator-editable (FORK.md §19); a ``{...}`` placeholder would simply not
  exist in a saved SYSTEM_PROMPT.md, so the notice is appended to the rendered
  prompt instead — which is what keeps it working for a customized template.
"""

from __future__ import annotations

import asyncio
import importlib
from enum import Enum
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.tools import tool

import deerflow.tools as tools_package
from app.gateway.services import merge_run_context_overrides
from deerflow.agents.lead_agent import agent as lead_agent_module
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_config import ToolConfig
from deerflow.subagents.config import SubagentConfig
from deerflow.tools.internet_access import (
    INTERNET_ENABLED_CONTEXT_KEY,
    OFFLINE_ALLOWED_TOOL_GROUPS,
    OFFLINE_SYSTEM_PROMPT_NOTICE,
    append_offline_notice,
    internet_access_enabled,
    is_offline_safe_group,
)
from deerflow.tools.tools import get_available_tools

task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")


# ---------------------------------------------------------------------------
# The flag itself
# ---------------------------------------------------------------------------


class TestFlagSemantics:
    def test_only_an_explicit_false_goes_offline(self):
        assert internet_access_enabled({INTERNET_ENABLED_CONTEXT_KEY: False}) is False

    @pytest.mark.parametrize(
        "context",
        [
            {},
            None,
            {INTERNET_ENABLED_CONTEXT_KEY: True},
            {INTERNET_ENABLED_CONTEXT_KEY: None},
            # A client that stringifies its booleans is *not* opting out. The
            # frontend normalizes to a real boolean before sending; anything
            # else is a caller with no opinion, and a caller with no opinion
            # must keep the operator's tools.
            {INTERNET_ENABLED_CONTEXT_KEY: "false"},
            {INTERNET_ENABLED_CONTEXT_KEY: 0},
            "not-a-mapping",
        ],
    )
    def test_everything_else_keeps_the_configured_tools(self, context):
        assert internet_access_enabled(context) is True


# ---------------------------------------------------------------------------
# The catalog filter
# ---------------------------------------------------------------------------


def _stand_in_tool(name: str):
    """A configured tool that only has to be distinguishable by name."""

    @tool(name)
    def _t() -> str:
        """A stand-in for a configured tool."""
        return "ok"

    return _t


# Config entries resolve through ``module:attribute``, and the catalog
# deduplicates by the *tool object's* name — so each entry needs its own object.
web_search_tool = _stand_in_tool("web_search")
web_fetch_tool = _stand_in_tool("web_fetch")
browser_navigate_tool = _stand_in_tool("browser_navigate")
read_file_tool = _stand_in_tool("read_file")
write_file_tool = _stand_in_tool("write_file")
generate_image_tool = _stand_in_tool("generate_image")
knowledge_search_tool = _stand_in_tool("knowledge_search")
mystery_tool = _stand_in_tool("mystery_tool")
bash_tool = _stand_in_tool("bash")


def _tools_config() -> list[ToolConfig]:
    here = __name__
    return [
        ToolConfig(name="web_search", group="web", use=f"{here}:web_search_tool"),
        ToolConfig(name="web_fetch", group="web", use=f"{here}:web_fetch_tool"),
        ToolConfig(name="browser_navigate", group="browser", use=f"{here}:browser_navigate_tool"),
        ToolConfig(name="read_file", group="file:read", use=f"{here}:read_file_tool"),
        ToolConfig(name="write_file", group="file:write", use=f"{here}:write_file_tool"),
        ToolConfig(name="generate_image", group="media", use=f"{here}:generate_image_tool"),
        ToolConfig(name="knowledge_search", group="knowledge", use=f"{here}:knowledge_search_tool"),
        # A group nobody has classified — an operator's own tool, or a group a
        # future upstream merge introduces.
        ToolConfig(name="mystery_tool", group="somebodys_new_group", use=f"{here}:mystery_tool"),
    ]


def _app_config(tools: list[ToolConfig] | None = None) -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="m",
                display_name="m",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="m",
                supports_thinking=False,
                supports_vision=False,
            )
        ],
        # A container sandbox, so the bash tool is not filtered out for an
        # unrelated reason while we are asserting what the switch drops.
        sandbox=SandboxConfig(use="deerflow.sandbox.aio:AioSandboxProvider"),
        tools=tools if tools is not None else _tools_config(),
    )


def _names(**kwargs) -> set[str]:
    return {t.name for t in get_available_tools(include_mcp=False, app_config=_app_config(kwargs.pop("tools", None)), **kwargs)}


class TestCatalogFilter:
    def test_online_keeps_every_configured_tool(self):
        # The control: with the switch on, nothing changes.
        names = _names()
        assert {"web_search", "web_fetch", "browser_navigate", "mystery_tool"} <= names

    def test_offline_drops_the_web_and_browser_groups(self):
        names = _names(internet_enabled=False)
        assert not ({"web_search", "web_fetch", "browser_navigate"} & names)

    def test_offline_keeps_the_local_surfaces(self):
        # Files, local media generation and the self-hosted knowledge base are
        # not the internet, and taking them away would make the switch a "do
        # nothing" mode rather than an offline one.
        names = _names(internet_enabled=False)
        assert {"read_file", "write_file", "generate_image", "knowledge_search"} <= names

    def test_offline_drops_an_unclassified_group(self):
        # THE fail-closed property. A blocklist of the two shipped network
        # groups passes every other test in this class and silently ships the
        # next provider group someone adds.
        assert "mystery_tool" not in _names(internet_enabled=False)
        assert "somebodys_new_group" not in OFFLINE_ALLOWED_TOOL_GROUPS

    def test_offline_keeps_the_bash_tool(self):
        # A shell is the sandbox's local execution surface; whether it has a
        # route to the internet belongs to the container the operator runs.
        # Removing it would break running code rather than browsing.
        tools = [*_tools_config(), ToolConfig(name="bash", group="bash", use=f"{__name__}:bash_tool")]
        assert "bash" in _names(internet_enabled=False, tools=tools)

    def test_offline_keeps_the_builtin_tools(self):
        # Clarification, file presentation and friends are local and must
        # survive, or an offline conversation cannot even ask a question.
        assert "ask_clarification" in _names(internet_enabled=False)

    def test_group_classification_is_an_allowlist(self):
        assert is_offline_safe_group("file:read") is True
        assert is_offline_safe_group("web") is False
        assert is_offline_safe_group("browser") is False
        assert is_offline_safe_group(None) is False
        assert is_offline_safe_group("") is False


class TestRemoteToolSources:
    def _enable_one_mcp_server(self, monkeypatch, mcp_tool):
        from deerflow.config import extensions_config as extensions_config_module

        monkeypatch.setattr(
            extensions_config_module.ExtensionsConfig,
            "from_file",
            classmethod(lambda cls: SimpleNamespace(get_enabled_mcp_servers=lambda: {"server": object()})),
        )
        import deerflow.mcp.cache as mcp_cache

        monkeypatch.setattr(mcp_cache, "get_cached_mcp_tools", lambda: [mcp_tool])

    def test_offline_drops_mcp_tools(self, monkeypatch):
        @tool
        def remote_thing() -> str:
            """An MCP-provided tool."""
            return "ok"

        self._enable_one_mcp_server(monkeypatch, remote_thing)
        online = {t.name for t in get_available_tools(app_config=_app_config())}
        offline = {t.name for t in get_available_tools(app_config=_app_config(), internet_enabled=False)}
        # An MCP server is a network endpoint by construction, and a local one
        # still proxies to remote APIs.
        assert "remote_thing" in online
        assert "remote_thing" not in offline

    def test_offline_drops_the_acp_agent_tool(self, monkeypatch):
        config = _app_config()
        object.__setattr__(config, "acp_agents", {"codex": SimpleNamespace(command="codex")})
        import deerflow.tools.builtins.invoke_acp_agent_tool as acp_module

        @tool
        def invoke_acp_agent() -> str:
            """Delegate to an external ACP agent."""
            return "ok"

        monkeypatch.setattr(acp_module, "build_invoke_acp_agent_tool", lambda agents: invoke_acp_agent)
        online = {t.name for t in get_available_tools(include_mcp=False, app_config=config)}
        offline = {t.name for t in get_available_tools(include_mcp=False, app_config=config, internet_enabled=False)}
        # An external agent process has its own uncontrolled network access, so
        # delegating to one is an internet call by proxy.
        assert "invoke_acp_agent" in online
        assert "invoke_acp_agent" not in offline


# ---------------------------------------------------------------------------
# The offline notice
# ---------------------------------------------------------------------------


class TestOfflineNotice:
    def test_it_is_appended_to_a_rendered_prompt_not_a_placeholder(self):
        # The property that matters: this works on *any* rendered prompt, which
        # is what keeps an operator's customized SYSTEM_PROMPT.md (FORK.md §19)
        # — a template that contains no placeholder of ours — from silently
        # losing the notice.
        rendered = "A CUSTOM TEMPLATE WITH NO PLACEHOLDERS AT ALL"
        out = append_offline_notice(rendered)
        assert out.startswith(rendered)
        assert "Internet Access: OFF" in out

    def test_it_is_not_appended_twice(self):
        once = append_offline_notice("prompt")
        assert append_offline_notice(once) == once
        assert once.count("Internet Access: OFF") == 1

    def test_it_tells_the_model_not_to_route_around_the_switch(self):
        # Without this the model reaches for the shell as soon as `web_fetch`
        # is missing, which is the one hole the tool filter cannot close.
        flat = " ".join(OFFLINE_SYSTEM_PROMPT_NOTICE.split())
        assert "no network calls from the shell" in flat


# ---------------------------------------------------------------------------
# The lead-agent assembly
# ---------------------------------------------------------------------------


def _assemble(monkeypatch, context: dict) -> dict:
    """Assemble a lead agent with the expensive parts stubbed."""
    captured: dict = {}

    def _get_available_tools(**kwargs):
        captured["tool_kwargs"] = kwargs
        return []

    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "RENDERED SYSTEM PROMPT")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: captured.setdefault("agent_kwargs", kwargs))
    monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
    monkeypatch.setattr(tools_package, "get_available_tools", _get_available_tools)

    config: dict = {"configurable": {}, "context": dict(context)}
    assembly = lead_agent_module._assemble_lead_agent(config, app_config=_app_config())
    captured["config"] = config
    captured["descriptor"] = assembly.descriptor
    return captured


class TestLeadAgentAssembly:
    def test_the_switch_reaches_the_tool_catalog(self, monkeypatch):
        captured = _assemble(monkeypatch, {INTERNET_ENABLED_CONTEXT_KEY: False})
        assert captured["tool_kwargs"]["internet_enabled"] is False

    def test_a_run_with_no_opinion_keeps_its_tools(self, monkeypatch):
        captured = _assemble(monkeypatch, {})
        assert captured["tool_kwargs"]["internet_enabled"] is True

    def test_an_offline_run_carries_the_notice_in_its_system_prompt(self, monkeypatch):
        captured = _assemble(monkeypatch, {INTERNET_ENABLED_CONTEXT_KEY: False})
        assert "Internet Access: OFF" in captured["agent_kwargs"]["system_prompt"]

    def test_an_online_run_carries_no_notice(self, monkeypatch):
        captured = _assemble(monkeypatch, {})
        assert "Internet Access: OFF" not in captured["agent_kwargs"]["system_prompt"]

    def test_the_resolved_switch_is_published_for_the_subagents(self, monkeypatch):
        # The `task` tool reads the run context, so the factory writes the value
        # it actually built with back into both places a subagent may read.
        captured = _assemble(monkeypatch, {INTERNET_ENABLED_CONTEXT_KEY: False})
        assert captured["config"]["context"][INTERNET_ENABLED_CONTEXT_KEY] is False
        assert captured["config"]["configurable"][INTERNET_ENABLED_CONTEXT_KEY] is False

    def test_the_run_declares_which_way_the_switch_was(self, monkeypatch):
        # The assembly descriptor is what an extension observing a run gets to
        # read; a run that is offline but does not say so cannot be audited.
        from deerflow.extensions import bind_agent_build_extensions
        from deerflow.extensions.registry import ExtensionRegistry

        class _Observer:
            def on_agent_assembled(self, app_store, descriptor):
                return None

        registry = ExtensionRegistry()
        with registry.attributed_to("test"):
            registry.agent_assembly_observer(_Observer())
        # The descriptor is only built when an observer is registered to
        # receive it (the zero-observer fast path skips the hashing work).
        with bind_agent_build_extensions(registry.build()):
            captured = _assemble(monkeypatch, {INTERNET_ENABLED_CONTEXT_KEY: False})
        assert captured["descriptor"].effective_policies["internet_enabled"] is False


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


def _no_sleep(*_args, **_kwargs):
    async def _sleep():
        return None

    return _sleep()


@pytest.fixture()
def stub_task_tool(monkeypatch):
    """Drive the real ``task_tool`` with the executor and polling stubbed."""
    captured: dict = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "task-1"

    class _Status(Enum):
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"
        TIMED_OUT = "timed_out"

    get_available_tools_mock = MagicMock(return_value=[])
    captured["get_available_tools"] = get_available_tools_mock

    monkeypatch.setattr(task_tool_module, "SubagentStatus", _Status)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(
        task_tool_module,
        "get_subagent_config",
        lambda *args, **kwargs: SubagentConfig(name="general-purpose", description="d", system_prompt="p", max_turns=5, timeout_seconds=5),
    )
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda *args, **kwargs: ["general-purpose"])
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _id: SimpleNamespace(
            status=_Status.COMPLETED,
            ai_messages=[],
            result="done",
            error=None,
            stop_reason=None,
            token_usage_records=[],
            usage_reported=False,
        ),
    )
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda *a, **k: None)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", get_available_tools_mock)
    return captured


def _delegate(context: dict):
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": {}},
        context={"thread_id": "thread-1", **context},
        config={"metadata": {"model_name": "lead-model", "trace_id": "trace-1"}},
    )
    coroutine = getattr(task_tool_module.task_tool, "coroutine", None)
    kwargs = {
        "runtime": runtime,
        "description": "do a thing",
        "prompt": "do a thing",
        "subagent_type": "general-purpose",
        "tool_call_id": "call-1",
    }
    if coroutine is not None:
        return asyncio.run(coroutine(**kwargs))
    return task_tool_module.task_tool.func(**kwargs)


class TestDelegation:
    def test_a_subagent_inherits_an_offline_run(self, stub_task_tool):
        # Without this, "no internet" is one `task` call away from untrue.
        _delegate({INTERNET_ENABLED_CONTEXT_KEY: False})
        assert stub_task_tool["get_available_tools"].call_args.kwargs["internet_enabled"] is False

    def test_a_subagent_of_an_ordinary_run_keeps_its_tools(self, stub_task_tool):
        _delegate({})
        assert stub_task_tool["get_available_tools"].call_args.kwargs["internet_enabled"] is True


# ---------------------------------------------------------------------------
# The Gateway
# ---------------------------------------------------------------------------


class TestGatewayForwarding:
    def test_the_switch_is_an_accepted_run_context_key(self):
        config: dict = {}
        merge_run_context_overrides(config, {INTERNET_ENABLED_CONTEXT_KEY: False})
        # Both, because the lead-agent factory merges configurable and context
        # and either one alone would depend on which caller wrote it.
        assert config["configurable"][INTERNET_ENABLED_CONTEXT_KEY] is False
        assert config["context"][INTERNET_ENABLED_CONTEXT_KEY] is False
