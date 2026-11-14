"""The CAD module as the host sees it (roadmap item 44, FORK.md §51).

The kernel is not installed in the backend environment, and these tests do not
need it: they load the example package the way the Gateway does and replace
only the child process. The interpreter and the kernel half are tested inside
the package (``examples/deerflow-extension-cad/tests``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.agents.thread_state import merge_artifacts
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.plugin_tools import build_plugin_tools, plugin_tool_name
from deerflow.tools.internet_access import LOCAL_EXTENSION_TOOL_GROUP, is_offline_safe_group

PACKAGE = Path(__file__).resolve().parents[2] / "examples" / "deerflow-extension-cad"

PLATE = 'import cadquery as cq\nresult = cq.Workplane("XY").box(60, 40, 6).faces(">Z").workplane().pushPoints([(-15, 0), (15, 0)]).hole(4)\n'
MEASURED = {"solids": 1, "valid": True, "closed": True, "bbox_mm": [60.0, 40.0, 6.0], "volume_mm3": 14249.2, "holes": [{"diameter_mm": 4.0, "through": True}, {"diameter_mm": 4.0, "through": True}]}
BUILT = {"status": "built", "measured": MEASURED, "files": {"step": b"STEP", "stl": b"STL", "glb": b"glTF"}}


class _State(MessagesState):
    artifacts: Annotated[list[str], merge_artifacts]
    thread_data: dict


@pytest.fixture
def cad(monkeypatch):
    monkeypatch.syspath_prepend(str(PACKAGE))
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config={})])
    assert not diagnostics
    return loaded


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    from deerflow.config import paths

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths, "_paths", None)
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda **kwargs: SimpleNamespace(uses_thread_data_mounts=True))
    return paths.get_paths().sandbox_outputs_dir("thread-a", user_id="alice")


async def _call(loaded, outputs, monkeypatch, worker_result, **arguments):
    import deerflow_extension_cad.tool as cad_tool

    seen = []

    async def worker(script, **limits):
        seen.append((script, limits))
        return {**worker_result, "files": dict(worker_result.get("files") or {})}

    monkeypatch.setattr(cad_tool, "run_worker", worker)
    (tool,) = build_plugin_tools(loaded)
    graph = StateGraph(_State)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    payload = {"name": "Mounting plate", "script": PLATE, "bbox_xyz_mm": [60, 40, 6], **arguments}
    state = await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "cad-call", "name": tool.name, "args": payload}])], "thread_data": {"outputs_path": str(outputs)}},
        context={"user_id": "alice", "thread_id": "thread-a"},
    )
    message = state["messages"][-1]
    assert message.status == "success", message.content
    return json.loads(message.content), state, seen


def _files(outputs):
    return sorted(path.name for path in outputs.iterdir()) if outputs.exists() else []


def test_an_older_host_refuses_the_module_and_names_the_api_it_needs(monkeypatch):
    monkeypatch.syspath_prepend(str(PACKAGE))
    monkeypatch.setattr("deerflow.extensions.loader.API_VERSION", "0.2.11")
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config={})])
    assert not loaded.plugins
    assert "requires extension-api 0.2.12, host provides 0.2.11" in diagnostics[0].message


def test_loading_the_module_registers_one_tool_and_does_not_load_the_kernel(cad):
    ((_, plugin),) = cad.plugins
    assert (plugin.namespace, plugin.enabled, [tool.name for tool in plugin.tools]) == ("cad", True, ["cad_build"])
    # A Gateway with the module installed starts without importing the kernel or its 1.7 GB of friends.
    assert not {"cadquery", "OCP", "vtk"} & set(sys.modules)


def test_operator_settings_are_validated_at_startup(monkeypatch):
    monkeypatch.syspath_prepend(str(PACKAGE))
    for config in ({"timeout_seconds": 26}, {"timeout_seconds": True}, {"memory_mb": 100}, {"timeout_seconds": "20"}):
        loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config=config)])
        assert not loaded.plugins and "install() failed" in diagnostics[0].message
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config={"enabled": False})])
    assert not loaded.plugins and not diagnostics


def test_cad_build_is_declared_in_the_group_that_survives_the_internet_switch(cad):
    ((_, plugin),) = cad.plugins
    (tool,) = plugin.tools
    assert tool.group == LOCAL_EXTENSION_TOOL_GROUP
    assert is_offline_safe_group(tool.group)
    # Not `media` (that is the local ComfyUI service) and not the plugin default.
    assert tool.group not in ("media", "extensions")


def test_cad_build_is_offered_with_the_internet_off_and_follows_an_agents_group_list(cad):
    from deerflow.tools import tools as assembly

    config = SimpleNamespace(tools=[], models=[], acp_agents={})
    name = plugin_tool_name("cad", "cad_build")

    def offered(**kwargs):
        return [tool.name for tool in assembly.get_available_tools(app_config=config, extensions=cad, include_mcp=False, include_upload_tool=False, **kwargs)]

    assert name in offered(internet_enabled=False)
    assert name in offered(internet_enabled=False, groups=[LOCAL_EXTENSION_TOOL_GROUP])
    assert name not in offered(groups=["file:read"])


@pytest.mark.asyncio
async def test_a_part_that_passes_every_check_is_handed_over_with_its_step_file(cad, outputs, monkeypatch):
    answer, state, seen = await _call(cad, outputs, monkeypatch, BUILT, volume_min_max_mm3=[14000, 14400], hole_diameters_mm=[4, 4])
    assert answer["passed"] is True
    assert [check["check"] for check in answer["checks"]] == ["one closed solid", "bounding box", "volume", "holes"]
    assert all(check["passed"] for check in answer["checks"])
    # The script as given, the report, and the three exports: five files.
    assert _files(outputs) == ["mounting-plate.glb", "mounting-plate.py", "mounting-plate.report.json", "mounting-plate.step", "mounting-plate.stl"]
    assert (outputs / "mounting-plate.py").read_text(encoding="utf-8") == PLATE
    assert (outputs / "mounting-plate.step").read_bytes() == b"STEP"
    report = json.loads((outputs / "mounting-plate.report.json").read_text(encoding="utf-8"))
    assert report["passed"] is True and report["measured"]["bbox_mm"] == [60.0, 40.0, 6.0]
    assert sorted(state["artifacts"]) == sorted(f"/mnt/user-data/outputs/{name}" for name in _files(outputs))
    assert answer["files"] and "next" not in answer
    # The Gateway only starts the child: the script reaches it untouched, with the operator's limits.
    assert seen == [(PLATE, {"timeout_seconds": 20, "memory_mb": 4096})]


@pytest.mark.asyncio
async def test_a_part_that_fails_a_check_leaves_no_step_file(cad, outputs, monkeypatch):
    # The model expected two holes; the part has one.
    one_hole = {**BUILT, "measured": {**MEASURED, "holes": MEASURED["holes"][:1]}}
    answer, state, _ = await _call(cad, outputs, monkeypatch, one_hole, hole_diameters_mm=[4, 4])
    assert answer["passed"] is False
    holes = next(check for check in answer["checks"] if check["check"] == "holes")
    assert (holes["passed"], holes["expected"], holes["measured"]) == (False, [4, 4], [4.0])
    # No STEP and no STL: a STEP file in the outputs means a part that passed. The failed shape can still be looked at.
    assert _files(outputs) == ["mounting-plate.failed.glb", "mounting-plate.py", "mounting-plate.report.json"]
    assert "Do not present" in answer["next"]
    assert json.loads((outputs / "mounting-plate.report.json").read_text(encoding="utf-8"))["passed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("measured", "failing"),
    [
        ({"bbox_mm": [60.0, 40.0, 6.5]}, "bounding box"),
        ({"volume_mm3": 9000.0}, "volume"),
        ({"solids": 2}, "one closed solid"),
        ({"valid": False}, "one closed solid"),
        ({"closed": False}, "one closed solid"),
        ({"holes": [{"diameter_mm": 4.0}, {"diameter_mm": 4.5}]}, "holes"),
    ],
)
async def test_each_check_decides_on_its_own(cad, outputs, monkeypatch, measured, failing):
    answer, _, _ = await _call(cad, outputs, monkeypatch, {**BUILT, "measured": {**MEASURED, **measured}}, volume_min_max_mm3=[14000, 14400], hole_diameters_mm=[4, 4])
    assert [check["check"] for check in answer["checks"] if not check["passed"]] == [failing]
    assert not [name for name in _files(outputs) if name.endswith((".step", ".stl"))]


@pytest.mark.asyncio
async def test_a_refused_script_is_reported_with_its_construct_and_line_and_builds_nothing(cad, outputs, monkeypatch):
    refused = {"status": "refused", "construct": "import", "line": 1, "message": "the only import a script may contain is: import cadquery as cq"}
    answer, state, _ = await _call(cad, outputs, monkeypatch, refused)
    assert answer["passed"] is False
    assert answer["error"] == {"construct": "import", "line": 1, "message": refused["message"]}
    assert _files(outputs) == ["mounting-plate.py", "mounting-plate.report.json"]
    assert "checks" not in answer


@pytest.mark.asyncio
async def test_a_rebuild_keeps_its_files_together_under_one_new_stem(cad, outputs, monkeypatch):
    await _call(cad, outputs, monkeypatch, BUILT)
    answer, _, _ = await _call(cad, outputs, monkeypatch, BUILT)
    assert sorted(Path(path).name for path in answer["files"]) == ["mounting-plate-1.glb", "mounting-plate-1.py", "mounting-plate-1.report.json", "mounting-plate-1.step", "mounting-plate-1.stl"]


@pytest.mark.asyncio
async def test_a_part_the_host_would_not_store_is_not_presented_as_delivered(cad, outputs, monkeypatch):
    import deerflow_extension_cad.tool as cad_tool

    from deerflow.config.app_config import AppConfig, PluginOutputsConfig
    from deerflow.config.sandbox_config import SandboxConfig

    async def worker(script, **limits):
        return {"status": "built", "measured": MEASURED, "files": {"step": b"S" * 64, "stl": b"L" * 4096, "glb": b"g" * 64}}

    monkeypatch.setattr(cad_tool, "run_worker", worker)
    (tool,) = build_plugin_tools(cad)
    graph = StateGraph(_State)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"), plugin_outputs=PluginOutputsConfig(max_file_bytes=1024, max_call_bytes=1024 * 1024))
    state = await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "cad-call", "name": tool.name, "args": {"name": "plate", "script": PLATE, "bbox_xyz_mm": [60, 40, 6]}}])], "thread_data": {"outputs_path": str(outputs)}},
        context={"user_id": "alice", "thread_id": "thread-a", "app_config": config},
    )
    answer = json.loads(state["messages"][-1].content)
    # The checks passed, the operator's cap refused the STL: no STEP is written after it.
    assert answer["passed"] is False
    assert any("plate.stl was not saved (LIMIT_EXCEEDED)" in problem for problem in answer["problems"])
    assert _files(outputs) == ["plate.glb", "plate.py", "plate.report.json"]


@pytest.mark.asyncio
async def test_the_tool_does_not_start_a_build_it_could_not_hand_over(cad, monkeypatch):
    import deerflow_extension_cad.tool as cad_tool

    async def must_not_run(script, **limits):
        raise AssertionError("no conversation, no build")

    monkeypatch.setattr(cad_tool, "run_worker", must_not_run)
    (tool,) = build_plugin_tools(cad)
    runtime = SimpleNamespace(context={"user_id": "alice"}, config={"configurable": {"user_id": "alice"}}, state={}, tool_call_id="c")
    answer = json.loads(await tool.coroutine(runtime=runtime, name="plate", script=PLATE, bbox_xyz_mm=[60, 40, 6]))
    assert answer["passed"] is False and "cannot receive files" in answer["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        ({"thread_id": "other-conversation"}, "unknown argument 'thread_id'"),
        ({"path": "/etc"}, "unknown argument 'path'"),
        # A misspelled expectation must not become a check that silently never runs.
        ({"hole_diameter_mm": [4, 4]}, "unknown argument 'hole_diameter_mm'"),
        ({"bbox_xyz_mm": [60, 40]}, "bbox_xyz_mm must be three positive numbers"),
        ({"bbox_xyz_mm": [60, 40, 0]}, "bbox_xyz_mm must be three positive numbers"),
        ({"volume_min_max_mm3": [200, 100]}, "volume_min_max_mm3 must be [min, max]"),
        ({"hole_diameters_mm": [4, 0]}, "hole_diameters_mm must list one positive diameter"),
        ({"script": "   "}, "script is empty"),
        ({"name": ""}, "name must be 1 to 60 characters"),
    ],
)
async def test_unusable_arguments_are_answered_before_any_build(cad, monkeypatch, arguments, says):
    import deerflow_extension_cad.tool as cad_tool

    async def must_not_run(script, **limits):
        raise AssertionError("arguments that cannot be checked must not start a build")

    monkeypatch.setattr(cad_tool, "run_worker", must_not_run)
    (tool,) = build_plugin_tools(cad)
    runtime = SimpleNamespace(context={"user_id": "alice", "thread_id": "thread-a"}, config={"configurable": {"user_id": "alice"}}, state={"thread_data": {"outputs_path": "/nowhere"}}, tool_call_id="c")
    answer = json.loads(await tool.coroutine(runtime=runtime, **{"name": "plate", "script": PLATE, "bbox_xyz_mm": [60, 40, 6], **arguments}))
    assert answer["passed"] is False and says in answer["error"]["message"]


def test_the_schema_the_model_sees_is_structure_only_and_requires_the_size(cad):
    from jsonschema import Draft202012Validator

    ((_, plugin),) = cad.plugins
    schema = dict(plugin.tools[0].input_schema)
    validator = Draft202012Validator(schema)
    good = {"name": "plate", "script": PLATE, "bbox_xyz_mm": [60, 40, 6]}
    assert validator.is_valid(good) and validator.is_valid({**good, "volume_min_max_mm3": [1, 2], "hole_diameters_mm": []})
    for bad in ({"name": "plate", "script": PLATE}, {**good, "bbox_xyz_mm": "60x40x6"}, {**good, "script": 5}, {**good, "hole_diameters_mm": ["4"]}, {**good, "bbox_xyz_mm": [60, 40, True]}):
        assert not validator.is_valid(bad)
    # Descriptions cost every request of every conversation; the parameter names carry the meaning.
    assert all("description" not in spec for spec in schema["properties"].values())
