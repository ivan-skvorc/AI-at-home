"""Exercise actual LangGraph tool dispatch, not just manifest serialization."""

import asyncio
import json
import os
from dataclasses import FrozenInstanceError, dataclass, replace
from types import MappingProxyType, SimpleNamespace
from typing import Annotated

import pytest
from deerflow_extension_api.plugins import ModelTool, PluginContribution
from langchain_core.messages import AIMessage
from langchain_core.tools import ToolException
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.agents.thread_state import merge_artifacts
from deerflow.extensions.plugin_tools import build_plugin_tools
from deerflow.extensions.registry import ExtensionRegistry


@pytest.fixture
def installed():
    calls = []

    async def search(payload, context):
        calls.append(context)
        return {"query": payload["query"], "user": context.principal.user_id}

    plugin = PluginContribution(
        namespace="community.search",
        title="Search",
        enabled=True,
        tools=(ModelTool("search", "Search selected documents", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}, search),),
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(plugin)
    return registry.build(), plugin, calls


@pytest.mark.asyncio
async def test_real_tool_node_binds_identity_and_deployment_policy(installed):
    loaded, plugin, calls = installed
    (tool,) = build_plugin_tools(loaded)
    assert "runtime" not in json.dumps(tool.tool_call_schema)
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    agent = graph.compile()

    async def invoke(args):
        return (
            await agent.ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"id": "c", "name": tool.name, "args": args}])]},
                context={"user_id": "trusted-user", "thread_id": "thread-a"},
            )
        )["messages"][-1]

    result = await invoke({"query": "hello"})
    assert json.loads(result.content) == {"query": "hello", "user": "trusted-user"}
    assert calls[0].thread_id == "thread-a"
    with pytest.raises(TypeError):
        calls[0].settings["enabled"] = False
    assert (await invoke({"query": "x", "user_id": "victim"})).status == "error"
    assert len(calls) == 1
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(replace(plugin, enabled=False))
    assert build_plugin_tools(registry.build()) == []


def test_registration_rejects_invalid_schema_without_partial_install(installed):
    _, plugin, _ = installed
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        for schema in ({"type": "string"}, {"type": "object", "$ref": "https://example.test/schema"}, {"type": "object", "properties": {"runtime": {"type": "string"}}}):
            with pytest.raises(ValueError):
                registry.plugin(replace(plugin, tools=(replace(plugin.tools[0], input_schema=schema),)))
            assert not registry.build().plugins


@pytest.mark.asyncio
async def test_root_composition_is_enforced_but_never_sent_to_the_model(installed):
    # Providers 400 a request whose tool root carries a union, and that fails
    # every chat the tool is bound to, not just calls to it.
    loaded, plugin, calls = installed
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}},
        "oneOf": [{"required": ["query"]}, {"required": ["ids"]}],
        "additionalProperties": False,
    }
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(replace(plugin, tools=(replace(plugin.tools[0], input_schema=schema),)))
    (tool,) = build_plugin_tools(registry.build())
    parameters = convert_to_openai_tool(tool)["function"]["parameters"]
    assert parameters["type"] == "object"
    assert not {"oneOf", "anyOf", "allOf", "enum", "not"} & parameters.keys()
    assert parameters["properties"] == schema["properties"]
    runtime = SimpleNamespace(context={"user_id": "u"}, config={"configurable": {"user_id": "u"}})
    # The host still validates each call against the declared schema.
    for payload in ({"query": "a", "ids": ["b"]}, {}):
        with pytest.raises(ToolException, match="Invalid plugin tool input"):
            await tool.coroutine(runtime=runtime, **payload)
    assert not calls
    assert json.loads(await tool.coroutine(runtime=runtime, query="a")) == {"query": "a", "user": "u"}


def test_group_filter_and_name_collision_fail_closed(installed):
    loaded, _, _ = installed
    assert build_plugin_tools(loaded, groups=["web"]) == []
    (tool,) = build_plugin_tools(loaded, groups=["extensions"])
    with pytest.raises(ValueError, match="collision"):
        build_plugin_tools(loaded, reserved_names={tool.name})


def test_built_tools_carry_host_recorded_plugin_provenance(installed):
    """The tag is written at construction, from registry-validated values."""
    from deerflow.tools.tool_provenance import get_plugin_source, is_plugin_tool, resolve_tool_provenance

    loaded, plugin, _ = installed
    (tool,) = build_plugin_tools(loaded)

    assert is_plugin_tool(tool) is True
    assert get_plugin_source(tool) == {
        "namespace": plugin.namespace,
        "declaration": "search",
        "installation": "test",
    }
    provenance = resolve_tool_provenance(tool)
    assert provenance is not None
    assert provenance.source == f"plugin:{plugin.namespace}"
    assert provenance.declaration == "search"


@pytest.mark.parametrize("source", ["config", "builtin", "mcp", "acp"])
def test_assembly_keeps_ordinary_and_unaffected_plugin_tools_on_collision(installed, monkeypatch, caplog, source):
    from langchain_core.tools import Tool

    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.extensions.plugin_tools import plugin_tool_name
    from deerflow.tools import tools as assembly

    loaded, plugin, _ = installed
    name = plugin_tool_name(plugin.namespace, "search")
    ordinary = Tool(name=name, description="Ordinary tool", func=lambda query: "ordinary result")
    healthy = replace(plugin, namespace="community.healthy")
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(plugin)
        registry.plugin(healthy)
    config = SimpleNamespace(
        tools=[SimpleNamespace(name=name, use="test:ordinary", group="extensions")] if source == "config" else [],
        models=[],
        acp_agents={"test": {}} if source == "acp" else {},
    )
    monkeypatch.setattr(assembly, "BUILTIN_TOOLS", [ordinary] if source == "builtin" else [])
    monkeypatch.setattr(assembly, "is_mcp_task_runtime_available", lambda: False)
    monkeypatch.setattr(assembly, "is_host_bash_allowed", lambda config: False)
    monkeypatch.setattr(assembly, "resolve_variable", lambda *args: ordinary)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: SimpleNamespace(get_enabled_mcp_servers=lambda: {"test": {}}))
    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", lambda: [ordinary])
    monkeypatch.setattr("deerflow.tools.builtins.invoke_acp_agent_tool.build_invoke_acp_agent_tool", lambda agents: ordinary)

    result = assembly.get_available_tools(app_config=config, extensions=registry.build(), include_mcp=source == "mcp", include_upload_tool=False)
    # Model-bound built-ins are assembled independently of BUILTIN_TOOLS.
    expected_ordinary = [name, "inspect_run_status"] if source in {"config", "builtin"} else ["inspect_run_status", name]
    assert [tool.name for tool in result] == [*expected_ordinary, plugin_tool_name(healthy.namespace, "search")]
    retained = next(tool for tool in result if tool.name == name)
    assert retained is ordinary
    assert retained.invoke("hello") == "ordinary result"
    assert "Duplicate tool name" in caplog.text

    # A host collision must not weaken the strict plugin-vs-plugin check.
    duplicate_snapshot = replace(loaded, plugins=loaded.plugins + loaded.plugins)
    with pytest.raises(ValueError, match="collision"):
        assembly.get_available_tools(app_config=config, extensions=duplicate_snapshot, include_mcp=False, include_upload_tool=False)


@pytest.mark.asyncio
async def test_model_tool_receives_run_control_from_host_runtime(installed):
    from unittest.mock import Mock

    from deerflow_extension_api import AGENT_RUNS_CONTEXT_KEY

    loaded, plugin, calls = installed
    (tool,) = build_plugin_tools(loaded)
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    scoped = object()
    handle = SimpleNamespace(for_plugin=Mock(return_value=scoped))
    await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "call", "name": tool.name, "args": {"query": "hello"}}])]},
        context={"user_id": "alice", "thread_id": "thread", AGENT_RUNS_CONTEXT_KEY: handle},
    )
    handle.for_plugin.assert_called_once_with(plugin.namespace)
    assert calls[0].agent_runs is scoped


def _tool_graph(plugin, declaration):
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(replace(plugin, tools=(declaration,)))
    (tool,) = build_plugin_tools(registry.build())
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile(), tool


async def _call_tool(graph, tool, **context):
    result = await graph.ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "artifact-call", "name": tool.name, "args": {"query": "hello"}}])]},
        context={"user_id": "trusted-user", "thread_id": "thread-a", **context},
    )
    return result["messages"][-1]


@pytest.mark.asyncio
async def test_opt_in_mode_rejects_legacy_tuple_through_real_tool_node(installed):
    # A trusted package can subclass the old declaration. This drives ToolNode
    # even on a pre-feature host, exposing ignored response-format declarations.
    @dataclass(frozen=True)
    class ArtifactTool(ModelTool):
        response_format: str = "content_and_artifact"

    async def handler(payload, context):
        return ("visible", {"private": "must not become content"})

    _, plugin, _ = installed
    old = plugin.tools[0]
    graph, tool = _tool_graph(plugin, ArtifactTool(old.name, old.description, old.input_schema, handler))
    message = await _call_tool(graph, tool)
    assert message.status == "error"
    assert message.artifact is None
    assert "must not become content" not in message.content


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact", [None, {"rows": [{"label": "故障", "score": 0.9}]}])
async def test_typed_result_separates_content_from_artifact_and_preserves_identity(installed, artifact):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    contexts = []

    async def handler(payload, context):
        contexts.append(context)
        return PluginToolResult("One record classified.", artifact)

    declaration = replace(plugin.tools[0], handler=handler, response_format="content_and_artifact")
    graph, tool = _tool_graph(plugin, declaration)
    message = await _call_tool(graph, tool)
    assert (message.content, message.artifact, message.status) == ("One record classified.", artifact, "success")
    assert (message.tool_call_id, message.name) == ("artifact-call", tool.name)
    assert (contexts[0].principal.user_id, contexts[0].thread_id) == ("trusted-user", "thread-a")
    assert "runtime" not in json.dumps(tool.tool_call_schema)


@pytest.mark.asyncio
async def test_artifact_is_independent_json_snapshot(installed):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    rows = [{"label": "original"}]
    artifact = MappingProxyType({"rows": rows})

    async def handler(payload, context):
        return PluginToolResult("ready", artifact)

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler, response_format="content_and_artifact"))
    message = await _call_tool(graph, tool)
    rows[0]["label"] = "changed after return"
    assert message.artifact == {"rows": [{"label": "original"}]}
    json.dumps(message.artifact, allow_nan=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["plain", "tuple", "bad-content", "list-artifact", "nan", "object", "int-key", "bool-key", "null-key", "float-key", "key-collision", "nested-key", "list-key", "tuple-key"])
async def test_opt_in_invalid_result_is_sanitized_without_artifact(installed, kind):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    values = {
        "plain": {"sensitive": "secret"},
        "tuple": ("visible", {"sensitive": "secret"}),
        "bad-content": PluginToolResult({"sensitive": "secret"}, None),
        "list-artifact": PluginToolResult("visible", ["secret"]),
        "nan": PluginToolResult("visible", {"score": float("nan")}),
        "object": PluginToolResult("visible", {"sensitive": object()}),
        "int-key": PluginToolResult("visible", {1: "secret"}),
        "bool-key": PluginToolResult("visible", {True: "secret"}),
        "null-key": PluginToolResult("visible", {None: "secret"}),
        "float-key": PluginToolResult("visible", {1.5: "secret"}),
        "key-collision": PluginToolResult("visible", {1: "secret", "1": "other"}),
        "nested-key": PluginToolResult("visible", {"record": {1: "secret", "1": "other"}}),
        "list-key": PluginToolResult("visible", {"rows": [{1: "secret"}]}),
        "tuple-key": PluginToolResult("visible", {"rows": ({1: "secret"},)}),
    }

    async def handler(payload, context):
        return values[kind]

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler, response_format="content_and_artifact"))
    message = await _call_tool(graph, tool)
    assert message.status == "error"
    assert message.artifact is None
    assert message.content == "Plugin tool unavailable or input rejected."


@pytest.mark.asyncio
@pytest.mark.parametrize("over_limit", [False, True])
async def test_artifact_mode_combines_utf8_content_and_artifact_budget(installed, over_limit):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    artifact = {"value": "中" * 1000}
    overhead = len(json.dumps({"content": "", "artifact": artifact}, ensure_ascii=False).encode())
    content = "a" * (64 * 1024 - overhead + int(over_limit))

    async def handler(payload, context):
        return PluginToolResult(content, artifact)

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler, response_format="content_and_artifact"))
    message = await _call_tool(graph, tool)
    if over_limit:
        assert message.status == "error"
        assert message.artifact is None
        assert message.content == "Plugin result exceeds 64 KiB."
    else:
        assert message.status == "success"
        assert message.content == content
        assert message.artifact == artifact


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{"text": "中文"}, ("legacy tuple", {"a": 1}), "quoted string", None, {1: "integer", "nested": {None: "null"}}])
async def test_default_mode_keeps_legacy_json_encoding(installed, value):
    _, plugin, _ = installed

    async def handler(payload, context):
        return value

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler))
    message = await _call_tool(graph, tool)
    assert message.content == json.dumps(value, ensure_ascii=False, allow_nan=False)
    assert message.artifact is None


@pytest.mark.asyncio
async def test_default_mode_cannot_serialize_typed_artifact_result(installed):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    result = PluginToolResult("visible", {"sensitive": "secret"})
    # This is also what the old host's unchanged JSON path does.
    with pytest.raises(TypeError):
        json.dumps(result)

    async def handler(payload, context):
        return result

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler))
    message = await _call_tool(graph, tool)
    assert message.status == "error" and message.artifact is None
    assert message.content == "Plugin tool unavailable or input rejected."


@pytest.mark.asyncio
async def test_artifact_mode_propagates_caller_cancellation(installed):
    _, plugin, _ = installed
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def handler(payload, context):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler, response_format="content_and_artifact"))
    task = asyncio.create_task(_call_tool(graph, tool))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_new_contract_keeps_old_positional_signature_and_is_frozen(installed):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    old = plugin.tools[0]
    declaration = ModelTool(old.name, old.description, old.input_schema, old.handler, "custom-group")
    assert declaration.response_format == "content" and declaration.group == "custom-group"
    with pytest.raises(TypeError):
        ModelTool(old.name, old.description, old.input_schema, old.handler, "custom-group", "content_and_artifact")
    result = PluginToolResult("visible", None)
    with pytest.raises(FrozenInstanceError):
        result.content = "changed"


@pytest.mark.parametrize("mode", ["unknown", None, []])
def test_invalid_response_format_rejects_whole_plugin_before_registration(installed, mode):
    _, plugin, _ = installed
    registry = ExtensionRegistry()
    declaration = replace(plugin.tools[0], name="other", response_format=mode)
    with registry.attributed_to("test"):
        with pytest.raises(ValueError, match="response format"):
            registry.plugin(replace(plugin, tools=(*plugin.tools, declaration)))
    assert not registry.build().plugins


# --- A tool hands a file to its conversation (extension API 0.2.12) ----------


class _OutputsState(MessagesState):
    artifacts: Annotated[list[str], merge_artifacts]
    thread_data: dict


def _outputs_dir(thread="thread-a", user="trusted-user"):
    from deerflow.config.paths import get_paths

    return get_paths().sandbox_outputs_dir(thread, user_id=user)


@pytest.fixture
def outputs_home(tmp_path, monkeypatch):
    from deerflow.config import paths

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths, "_paths", None)
    # The default install mounts thread data into the sandbox; nothing to synchronize.
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda **kwargs: SimpleNamespace(uses_thread_data_mounts=True))
    return tmp_path


def _output_tool(plugin, handler, response_format="content"):
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(replace(plugin, tools=(replace(plugin.tools[0], handler=handler, response_format=response_format),)))
    (tool,) = build_plugin_tools(registry.build())
    graph = StateGraph(_OutputsState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile(), tool


async def _run_output_tool(graph, tool, *, thread="thread-a", user="trusted-user", thread_data=None, **context):
    state = await graph.ainvoke(
        {
            "messages": [AIMessage(content="", tool_calls=[{"id": "file-call", "name": tool.name, "args": {"query": "hello"}}])],
            "thread_data": {"outputs_path": str(_outputs_dir(thread, user))} if thread_data is None else thread_data,
        },
        context={"user_id": user, "thread_id": thread, **context},
    )
    return state, state["messages"][-1]


def _writer(files, *, seen=None):
    """A handler that writes each (name, content) and reports the host's answer per file."""

    async def handler(payload, context):
        from deerflow_extension_api import HostCapabilityError

        answers = []
        for name, content in files:
            try:
                answers.append(await context.write_output(name, content))
            except HostCapabilityError as exc:
                answers.append(f"refused:{exc.code}")
        if seen is not None:
            seen.append(context)
        return {"files": answers}

    return handler


def _all_files(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


@pytest.mark.asyncio
@pytest.mark.parametrize("response_format", ["content", "content_and_artifact"])
async def test_tool_file_lands_in_the_conversation_outputs_and_is_registered_as_an_artifact(installed, outputs_home, response_format):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    payload = b"\x00binary\xff" * 100

    async def handler(payload_, context):
        path = await context.write_output("report.bin", payload)
        return PluginToolResult(path, {"path": path}) if response_format == "content_and_artifact" else {"path": path}

    graph, tool = _output_tool(plugin, handler, response_format)
    state, message = await _run_output_tool(graph, tool, run_id="run-1")

    virtual = "/mnt/user-data/outputs/report.bin"
    assert (_outputs_dir() / "report.bin").read_bytes() == payload
    # Registered the way a built-in tool's Command registers it: the artifact panel reads this list.
    assert state["artifacts"] == [virtual]
    assert (message.status, message.tool_call_id, message.name) == ("success", "file-call", tool.name)
    if response_format == "content_and_artifact":
        assert (message.content, message.artifact) == (virtual, {"path": virtual})
    else:
        # File bytes never reach the model, so they do not count against the 64 KiB result cap.
        assert json.loads(message.content) == {"path": virtual}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["../escape.txt", "sub/report.txt", "sub\\report.txt", "..", "a..b.txt", "", ".", "nul\x00.txt", "line\nbreak.txt", "x" * 256])
async def test_unsafe_file_name_is_refused_before_a_byte_is_written(installed, outputs_home, name):
    _, plugin, _ = installed
    graph, tool = _output_tool(plugin, _writer([(name, b"data")]))
    state, message = await _run_output_tool(graph, tool)
    assert json.loads(message.content) == {"files": ["refused:INVALID_NAME"]}
    assert _all_files(outputs_home) == []
    assert not state.get("artifacts")


@pytest.mark.asyncio
async def test_file_over_the_operator_cap_is_refused_before_a_byte_is_written(installed, outputs_home):
    from deerflow.config.app_config import AppConfig, PluginOutputsConfig
    from deerflow.config.sandbox_config import SandboxConfig

    _, plugin, _ = installed
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"), plugin_outputs=PluginOutputsConfig(max_file_bytes=8, max_call_bytes=12))
    files = [("too-big.bin", b"x" * 9), ("fits.bin", b"x" * 8), ("over-call.bin", b"x" * 5), ("rest.bin", b"x" * 4)]
    graph, tool = _output_tool(plugin, _writer(files))
    state, message = await _run_output_tool(graph, tool, app_config=config)
    # Per file first, then the running total of this one call.
    assert json.loads(message.content) == {"files": ["refused:LIMIT_EXCEEDED", "/mnt/user-data/outputs/fits.bin", "refused:LIMIT_EXCEEDED", "/mnt/user-data/outputs/rest.bin"]}
    assert _all_files(_outputs_dir()) == ["fits.bin", "rest.bin"]
    assert state["artifacts"] == ["/mnt/user-data/outputs/fits.bin", "/mnt/user-data/outputs/rest.bin"]
    # The per-call total starts again with the next call.
    state, message = await _run_output_tool(graph, tool, app_config=config)
    assert json.loads(message.content)["files"][1] == "/mnt/user-data/outputs/fits-1.bin"
    # Only the worker-pinned AppConfig is operator config: a look-alike under the
    # same context key cannot raise the caps (here it falls back to the defaults).
    forged = SimpleNamespace(plugin_outputs=PluginOutputsConfig(max_file_bytes=1, max_call_bytes=1))
    state, message = await _run_output_tool(graph, tool, app_config=forged)
    assert json.loads(message.content)["files"][0] == "/mnt/user-data/outputs/too-big.bin"


def test_default_caps_are_operator_config_and_admit_a_few_mebibytes_per_file():
    from deerflow.config.app_config import AppConfig, PluginOutputsConfig

    defaults = PluginOutputsConfig()
    assert (defaults.max_file_bytes, defaults.max_call_bytes) == (8 * 1024 * 1024, 32 * 1024 * 1024)
    assert AppConfig.model_fields["plugin_outputs"].default_factory is PluginOutputsConfig
    for invalid in ({"max_file_bytes": 0}, {"max_call_bytes": -1}, {"max_file_bytes": True}, {"unknown": 1}):
        with pytest.raises(ValueError):
            PluginOutputsConfig(**invalid)


@pytest.mark.asyncio
async def test_existing_file_or_link_is_never_replaced(installed, outputs_home):
    _, plugin, _ = installed
    outputs = _outputs_dir()
    outputs.mkdir(parents=True)
    (outputs / "report.txt").write_bytes(b"earlier")
    outside = outputs_home / "outside.txt"
    if os.name == "posix":
        (outputs / "link.txt").symlink_to(outside)
    files = [("report.txt", b"new"), ("link.txt", b"new")] if os.name == "posix" else [("report.txt", b"new")]
    graph, tool = _output_tool(plugin, _writer(files))
    _, message = await _run_output_tool(graph, tool)
    expected = ["/mnt/user-data/outputs/report-1.txt", "/mnt/user-data/outputs/link-1.txt"][: len(files)]
    assert json.loads(message.content) == {"files": expected}
    assert (outputs / "report.txt").read_bytes() == b"earlier"
    assert (outputs / "report-1.txt").read_bytes() == b"new"
    # A link planted in outputs is neither followed nor replaced.
    assert not outside.exists()


@pytest.mark.asyncio
async def test_a_tool_cannot_make_a_file_appear_in_another_conversation(installed, outputs_home):
    import inspect

    from deerflow_extension_api.plugins import ToolContext

    _, plugin, _ = installed
    # The capability takes a name and bytes: there is no thread, user or directory to supply.
    assert list(inspect.signature(ToolContext.write_output).parameters) == ["self", "name", "content"]

    graph, tool = _output_tool(plugin, _writer([("report.txt", b"mine")]))
    await _run_output_tool(graph, tool, thread="thread-a")
    assert _all_files(outputs_home) == ["users/trusted-user/threads/thread-a/user-data/outputs/report.txt"]

    # Run state that points at another conversation's (or another user's) outputs
    # is not authority: the write is checked against the run's own thread.
    for foreign in (_outputs_dir("thread-b"), _outputs_dir("thread-a", "victim"), outputs_home / "elsewhere"):
        state, message = await _run_output_tool(graph, tool, thread="thread-a", thread_data={"outputs_path": str(foreign)})
        assert json.loads(message.content) == {"files": ["refused:FORBIDDEN"]}
        assert not state.get("artifacts")
    state, message = await _run_output_tool(graph, tool, thread="thread-a", thread_data={})
    assert json.loads(message.content) == {"files": ["refused:FORBIDDEN"]}
    assert _all_files(outputs_home) == ["users/trusted-user/threads/thread-a/user-data/outputs/report.txt"]


@pytest.mark.asyncio
async def test_writer_kept_after_the_call_returned_writes_nothing(installed, outputs_home):
    from deerflow_extension_api import HostCapabilityError

    _, plugin, _ = installed
    seen = []
    graph, tool = _output_tool(plugin, _writer([("during.txt", b"in the call")], seen=seen))
    await _run_output_tool(graph, tool)
    with pytest.raises(HostCapabilityError) as refused:
        await seen[0].write_output("after.txt", b"later")
    assert refused.value.code == "FORBIDDEN"
    assert _all_files(_outputs_dir()) == ["during.txt"]


@pytest.mark.asyncio
async def test_delegated_subagent_call_writes_into_the_leads_shared_outputs(installed, outputs_home):
    _, plugin, _ = installed
    graph, tool = _output_tool(plugin, _writer([("part.txt", b"from the subagent")]))
    # A subagent runs with the lead's thread id and thread_data, and without
    # the lead's run id or run-control handle (subagents/executor.py).
    state, message = await _run_output_tool(graph, tool, thread="lead-thread", is_subagent=True, agent_id="general-purpose")
    assert json.loads(message.content) == {"files": ["/mnt/user-data/outputs/part.txt"]}
    assert (_outputs_dir("lead-thread") / "part.txt").read_bytes() == b"from the subagent"
    assert state["artifacts"] == ["/mnt/user-data/outputs/part.txt"]


@pytest.mark.asyncio
async def test_non_mounted_sandbox_receives_the_same_bytes_or_the_write_fails_whole(installed, outputs_home, monkeypatch):
    _, plugin, _ = installed
    synced = []

    class RemoteSandbox:
        fail = False

        def update_file(self, path, content):
            if self.fail:
                raise OSError("sandbox unreachable")
            synced.append((path, content))

    remote = RemoteSandbox()

    async def run_sandbox(runtime):
        return remote

    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda **kwargs: SimpleNamespace(uses_thread_data_mounts=False))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized_async", run_sandbox)
    graph, tool = _output_tool(plugin, _writer([("report.txt", b"shared")]))
    _, message = await _run_output_tool(graph, tool)
    assert json.loads(message.content) == {"files": ["/mnt/user-data/outputs/report.txt"]}
    assert synced == [("/mnt/user-data/outputs/report.txt", b"shared")]
    assert (_outputs_dir() / "report.txt").read_bytes() == b"shared"

    remote.fail = True
    state, message = await _run_output_tool(graph, tool)
    assert json.loads(message.content) == {"files": ["refused:UNAVAILABLE"]}
    # No half-delivered file: the host copy the sandbox never received is taken back.
    assert _all_files(_outputs_dir()) == ["report.txt"]
    assert not state.get("artifacts")


@pytest.mark.asyncio
async def test_host_without_the_capability_answers_unsupported():
    from deerflow_extension_api import ExtensionPrincipal, HostCapabilityError
    from deerflow_extension_api.plugins import ToolContext

    # What a host that predates API 0.2.12 constructs: no writer is bound.
    context = ToolContext(ExtensionPrincipal("alice"), MappingProxyType({"enabled": True}), "thread-a", run_id="run-1")
    assert context.output_writer is None
    with pytest.raises(HostCapabilityError) as refused:
        await context.write_output("report.txt", b"data")
    assert refused.value.code == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_call_outside_a_conversation_has_no_writer(installed, outputs_home):
    _, plugin, _ = installed
    seen = []
    (tool,) = build_plugin_tools(_registry_with(plugin, _writer([("report.txt", b"data")], seen=seen)))
    runtime = SimpleNamespace(context={"user_id": "u"}, config={"configurable": {"user_id": "u"}}, state={}, tool_call_id="c")
    assert json.loads(await tool.coroutine(runtime=runtime, query="a")) == {"files": ["refused:UNSUPPORTED"]}
    assert seen[0].output_writer is None
    assert _all_files(outputs_home) == []


def _registry_with(plugin, handler):
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(replace(plugin, tools=(replace(plugin.tools[0], handler=handler),)))
    return registry.build()


@pytest.mark.parametrize("host_version", ["0.2.11", "0.2.12"])
def test_example_extension_requires_a_host_with_file_output(monkeypatch, host_version):
    from pathlib import Path

    from deerflow.extensions.loader import ExtensionSpec, load_extensions

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-example"))
    monkeypatch.setattr("deerflow.extensions.loader.API_VERSION", host_version)
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_example:install", config={})])
    if host_version == "0.2.11":
        # An older host says so at load, instead of offering a tool whose file never appears.
        assert not loaded.plugins
        assert "requires extension-api 0.2.12, host provides 0.2.11" in diagnostics[0].message
    else:
        assert not diagnostics
        assert [plugin.namespace for _, plugin in loaded.plugins] == ["example.notes"]


@pytest.mark.asyncio
async def test_example_extension_tool_saves_a_note_through_the_real_tool_node(outputs_home, monkeypatch):
    from pathlib import Path

    from deerflow.extensions.loader import ExtensionSpec, load_extensions

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-example"))
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_example:install", config={})])
    assert not diagnostics
    (tool,) = build_plugin_tools(loaded)
    graph = StateGraph(_OutputsState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    state = await graph.compile().ainvoke(
        {
            "messages": [AIMessage(content="", tool_calls=[{"id": "note-call", "name": tool.name, "args": {"title": "Shopping list", "text": "eggs\nflour"}}])],
            "thread_data": {"outputs_path": str(_outputs_dir())},
        },
        context={"user_id": "trusted-user", "thread_id": "thread-a"},
    )
    assert state["artifacts"] == ["/mnt/user-data/outputs/shopping-list.md"]
    assert (_outputs_dir() / "shopping-list.md").read_text(encoding="utf-8") == "# Shopping list\n\neggs\nflour\n"
    assert json.loads(state["messages"][-1].content) == {"saved": "/mnt/user-data/outputs/shopping-list.md"}
