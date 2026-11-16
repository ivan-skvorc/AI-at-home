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


async def _call(loaded, outputs, monkeypatch, worker_result, *, conversation="thread-a", run=None, **arguments):
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
        context={"user_id": "alice", "thread_id": conversation, **({"run_id": run} if run else {})},
    )
    message = state["messages"][-1]
    assert message.status == "success", message.content
    return json.loads(message.content), state, seen


def _files(outputs):
    return sorted(path.name for path in outputs.iterdir()) if outputs.exists() else []


def test_an_older_host_refuses_the_module_and_names_the_api_it_needs(monkeypatch):
    monkeypatch.syspath_prepend(str(PACKAGE))
    monkeypatch.setattr("deerflow.extensions.loader.API_VERSION", "0.2.12")
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config={})])
    assert not loaded.plugins
    assert "requires extension-api 0.2.13, host provides 0.2.12" in diagnostics[0].message


def test_loading_the_module_registers_one_tool_and_does_not_load_the_kernel(cad):
    ((_, plugin),) = cad.plugins
    assert (plugin.namespace, plugin.enabled, [tool.name for tool in plugin.tools]) == ("cad", True, ["cad_build"])
    # A Gateway with the module installed starts without importing the kernel or its 1.7 GB of friends.
    assert not {"cadquery", "OCP", "vtk"} & set(sys.modules)


def test_operator_settings_are_validated_at_startup(monkeypatch):
    monkeypatch.syspath_prepend(str(PACKAGE))
    for config in ({"timeout_seconds": 26}, {"timeout_seconds": True}, {"memory_mb": 100}, {"timeout_seconds": "20"}, {"parallel_builds": 0}, {"parallel_builds": 17}):
        loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config=config)])
        assert not loaded.plugins and "install() failed" in diagnostics[0].message
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config={"enabled": False})])
    assert not loaded.plugins and not diagnostics


def test_the_module_loads_on_a_server_with_many_processors(monkeypatch):
    # The default number of builds at once is half the processors; it has to stay inside what an operator may set.
    import os

    monkeypatch.syspath_prepend(str(PACKAGE))
    monkeypatch.setattr(os, "cpu_count", lambda: 64)
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config={})])
    assert loaded.plugins and not diagnostics
    from deerflow_extension_cad.tool import settings_from

    assert settings_from({})["parallel_builds"] == 16
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert settings_from({})["parallel_builds"] == 1


@pytest.mark.asyncio
async def test_as_many_builds_run_at_once_as_the_operator_set(outputs, monkeypatch):
    monkeypatch.syspath_prepend(str(PACKAGE))
    loaded, _ = load_extensions([ExtensionSpec(use="deerflow_extension_cad:install", config={"parallel_builds": 3})])
    _, _, seen = await _call(loaded, outputs, monkeypatch, BUILT)
    slots = seen[0][1]["slots"]
    assert [slots.acquire(blocking=False) for _ in range(4)] == [True, True, True, False]


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
    # A pass is not the end of the work: the numbers cover a part of what was asked for.
    assert answer["files"] and answer["attempt"] == 1 and answer["next"].startswith("Every check passed. Before you present the part")
    # The Gateway only starts the child: the script reaches it untouched, with the operator's limits
    # and the slots that bound how many builds run at once.
    ((script, limits),) = seen
    assert script == PLATE
    assert {key: value for key, value in limits.items() if key != "slots"} == {"timeout_seconds": 20, "memory_mb": 4096}
    assert limits["slots"].acquire(blocking=False)


@pytest.mark.asyncio
async def test_a_part_that_fails_a_check_leaves_no_step_file(cad, outputs, monkeypatch):
    # The model expected two holes; the part has one.
    one_hole = {**BUILT, "measured": {**MEASURED, "holes": MEASURED["holes"][:1]}}
    answer, state, _ = await _call(cad, outputs, monkeypatch, one_hole, hole_diameters_mm=[4, 4])
    assert answer["passed"] is False
    holes = next(check for check in answer["checks"] if check["check"] == "holes")
    assert (holes["passed"], holes["expected"], holes["measured"]) == (False, [4, 4], [4.0])
    # No STEP and no STL: a STEP file this tool wrote means a part that passed. The failed shape can still be looked at.
    assert _files(outputs) == ["mounting-plate.failed.glb", "mounting-plate.py", "mounting-plate.report.json"]
    assert "Do not present" in answer["next"]
    assert json.loads((outputs / "mounting-plate.report.json").read_text(encoding="utf-8"))["passed"] is False


ONE_HOLE = {**BUILT, "measured": {**MEASURED, "holes": MEASURED["holes"][:1]}}
REFUSED = {"status": "refused", "construct": "while loop", "line": 3, "message": "a script may not contain a while loop."}


@pytest.mark.asyncio
async def test_builds_of_a_part_are_counted_and_the_answer_says_when_to_stop(cad, outputs, monkeypatch):
    """The agent runs the loop; the tool keeps the count a model loses over a long one."""
    from deerflow_extension_cad.tool import MAX_ATTEMPTS

    answers = []
    for number in range(1, MAX_ATTEMPTS + 2):
        # A different failure every time, so only the count decides what the answer says.
        measured = {**MEASURED, "bbox_mm": [60.0, 40.0, 6.0 + number]}
        answer, _, _ = await _call(cad, outputs, monkeypatch, {**BUILT, "measured": measured}, run="run-1")
        answers.append(answer)
    assert [answer["attempt"] for answer in answers] == list(range(1, MAX_ATTEMPTS + 2))
    for number, answer in enumerate(answers[: MAX_ATTEMPTS - 1], 1):
        assert answer["next"].startswith(f"Attempt {number} of {MAX_ATTEMPTS}. Read what failed, change the script and call cad_build again")
        assert "Do not present" in answer["next"] and "same failure" not in answer["next"]
    for answer in answers[MAX_ATTEMPTS - 1 :]:
        # Not a refusal to build: the user may ask for more. What changes is what the model is told to do.
        # "The last one did not pass": an earlier build of this run may have, and its files stand.
        assert answer["next"].startswith(f"{answer['attempt']} builds of this part in this run and the last one did not pass. Stop building.")
        assert "Tell the user what still fails" in answer["next"] and "call cad_build again" not in answer["next"]
    assert json.loads((outputs / "mounting-plate.report.json").read_text(encoding="utf-8"))["attempt"] == 1
    assert json.loads((outputs / "mounting-plate-3.report.json").read_text(encoding="utf-8"))["attempt"] == 4

    # The user answering is a new run: the count starts over.
    answer, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-2", hole_diameters_mm=[4, 4])
    assert answer["attempt"] == 1 and answer["next"].startswith("Attempt 1 of")
    # A part that passes at the limit is presented, not sent round again.
    for _ in range(MAX_ATTEMPTS - 2):
        await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-2", hole_diameters_mm=[4, 4])
    answer, _, _ = await _call(cad, outputs, monkeypatch, BUILT, run="run-2", hole_diameters_mm=[4, 4])
    assert (answer["passed"], answer["attempt"]) == (True, MAX_ATTEMPTS)
    assert answer["next"].startswith("Every check passed. Present the part") and "build again" not in answer["next"]


@pytest.mark.asyncio
async def test_a_change_that_did_not_touch_the_failure_is_said_to_have_done_nothing(cad, outputs, monkeypatch):
    first, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", hole_diameters_mm=[4, 4])
    again, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", hole_diameters_mm=[4, 4], script=PLATE + "# moved the hole\n")
    assert "same failure" not in first["next"]
    assert again["attempt"] == 2 and "This is the same failure as the attempt before" in again["next"]
    # A different failure is progress of a kind, and is not called a repeat. Neither is the same one two attempts apart.
    other, _, _ = await _call(cad, outputs, monkeypatch, REFUSED, run="run-1", hole_diameters_mm=[4, 4])
    back, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", hole_diameters_mm=[4, 4])
    assert "same failure" not in other["next"] and "same failure" not in back["next"]
    twice, _, _ = await _call(cad, outputs, monkeypatch, REFUSED, run="run-1", hole_diameters_mm=[4, 4])
    refused, _, _ = await _call(cad, outputs, monkeypatch, REFUSED, run="run-1", hole_diameters_mm=[4, 4])
    assert "same failure" not in twice["next"] and "same failure" in refused["next"]


@pytest.mark.asyncio
async def test_a_part_cannot_pass_by_moving_its_expected_numbers_without_it_being_said(cad, outputs, monkeypatch):
    """The numbers of the first build stand for what the user asked for."""
    wrong_height = {**BUILT, "measured": {**MEASURED, "bbox_mm": [60.0, 40.0, 8.0]}}
    failed, _, _ = await _call(cad, outputs, monkeypatch, wrong_height, run="run-1", hole_diameters_mm=[4, 4])
    assert failed["passed"] is False and "expected_changed" not in failed and "first built against" not in failed["next"]

    # The script is the same; the expectation was moved to where the part already is.
    moved, _, _ = await _call(cad, outputs, monkeypatch, wrong_height, run="run-1", bbox_xyz_mm=[60, 40, 8])
    assert moved["passed"] is True
    assert moved["expected_changed"] == {"bbox_xyz_mm": {"first": [60, 40, 6], "now": [60, 40, 8]}, "hole_diameters_mm": {"first": [4, 4], "now": None}}
    assert moved["next"].startswith("Every check passed.") and "tell the user which changed and why" in moved["next"]
    report = json.loads((outputs / "mounting-plate-1.report.json").read_text(encoding="utf-8"))
    assert report["expected_changed"] == moved["expected_changed"] and report["passed"] is True

    # Still said while the part is being rebuilt in this run, pass or fail.
    still, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", bbox_xyz_mm=[60, 40, 8], hole_diameters_mm=[4, 4])
    assert still["passed"] is False and set(still["expected_changed"]) == {"bbox_xyz_mm"} and "first built against" in still["next"]
    # "Keep going" is a new run and not a new request: the part is still held to its first numbers.
    kept, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-2", bbox_xyz_mm=[60, 40, 8], hole_diameters_mm=[4, 4])
    assert kept["attempt"] == 1 and set(kept["expected_changed"]) == {"bbox_xyz_mm"}
    # Back on the first numbers there is nothing to say.
    back, _, _ = await _call(cad, outputs, monkeypatch, BUILT, run="run-2", hole_diameters_mm=[4, 4])
    assert back["passed"] is True and "expected_changed" not in back and "first built against" not in back["next"]
    # After a pass, the user's next message may ask for a different part under the same name.
    new, _, _ = await _call(cad, outputs, monkeypatch, wrong_height, run="run-3", bbox_xyz_mm=[60, 40, 8])
    assert (new["passed"], new["attempt"]) == (True, 1) and "expected_changed" not in new


@pytest.mark.asyncio
async def test_a_check_added_later_is_held_and_not_reported_as_a_change(cad, outputs, monkeypatch):
    # Stating the volume on the second build makes the part harder to pass, not easier.
    first, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1")
    added, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", volume_min_max_mm3=[14000, 14400], hole_diameters_mm=[4, 4])
    assert "expected_changed" not in first and "expected_changed" not in added
    # From then on it is one of the part's numbers: widening it or dropping it is said.
    widened, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", volume_min_max_mm3=[1, 99999], hole_diameters_mm=[4, 4])
    assert widened["expected_changed"] == {"volume_min_max_mm3": {"first": [14000, 14400], "now": [1, 99999]}}
    dropped, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", volume_min_max_mm3=[14000, 14400])
    assert dropped["expected_changed"] == {"hole_diameters_mm": {"first": [4, 4], "now": None}}
    # The same numbers written as floats are the same numbers.
    same, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", bbox_xyz_mm=[60.0, 40.0, 6.0], volume_min_max_mm3=[14000.0, 14400], hole_diameters_mm=[4.0, 4])
    assert "expected_changed" not in same
    # And numbers closer than the tool's own tolerance, which a model copies back from "measured".
    close, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", bbox_xyz_mm=[60.0000001, 40, 6], volume_min_max_mm3=[14000, 14400], hole_diameters_mm=[4.000001, 4])
    assert "expected_changed" not in close
    # So are the same holes in another order: the check sorts them, and the answer prints them sorted.
    await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", name="two sizes", hole_diameters_mm=[6, 4])
    sorted_back, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", name="two sizes", hole_diameters_mm=[4, 6])
    assert "expected_changed" not in sorted_back


@pytest.mark.asyncio
async def test_each_part_and_each_conversation_is_counted_apart(cad, outputs, monkeypatch, tmp_path):
    await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", hole_diameters_mm=[4, 4])
    same, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", hole_diameters_mm=[4, 4], name="mounting  PLATE")
    lid, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-1", hole_diameters_mm=[4, 4], bbox_xyz_mm=[60, 40, 2], name="Lid")
    # Counted by its name, case, spacing and punctuation aside.
    assert (same["attempt"], lid["attempt"]) == (2, 1) and "expected_changed" not in lid
    # Not by the name its files get: names without a Latin letter all become "part" there, and a long
    # name is cut. The first build of a lid was told to stop after seven builds of a bracket.
    for first, second in (("支架", "盖子"), ("Кронштейн", "Крышка"), ("Mounting plate for the left side of the frame", "Mounting plate for the left side of the door")):
        one, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-9", hole_diameters_mm=[4, 4], name=first)
        two, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-9", hole_diameters_mm=[4, 4], bbox_xyz_mm=[30, 30, 2], name=second)
        again, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, run="run-9", hole_diameters_mm=[4, 4], name=f" {first.upper()}! ")
        assert (one["attempt"], two["attempt"], again["attempt"]) == (1, 1, 2), (first, second)
        assert "expected_changed" not in two
    from deerflow_extension_cad.tool import part_key

    # A vowel sign is part of a word: a screw and a punch are two parts. What cannot be seen is not part of a name.
    assert part_key("पेंच") != part_key("पंच") and part_key("किला") != part_key("कुला")
    assert part_key("plate\u200b") == part_key("ｐｌａｔｅ") == part_key("Plate") == "plate"
    assert part_key("Hook rack") == part_key("hook-rack") == part_key(" HOOK_RACK! ")
    assert part_key("Lid 1") != part_key("Lid 2") and part_key("!!!") == "!!!"
    from deerflow.config import paths

    elsewhere = paths.get_paths().sandbox_outputs_dir("thread-b", user_id="alice")
    other, _, _ = await _call(cad, elsewhere, monkeypatch, ONE_HOLE, conversation="thread-b", run="run-1", hole_diameters_mm=[4, 4], bbox_xyz_mm=[1, 2, 3])
    assert other["attempt"] == 1 and "expected_changed" not in other


@pytest.mark.asyncio
async def test_only_a_build_the_script_answers_for_is_an_attempt(cad, outputs, monkeypatch):
    for uncounted in ({"status": "busy", "message": "every build slot is taken"}, {"status": "loading", "message": "still loading"}, {"status": "unavailable", "message": "libGL.so.1 is missing"}):
        answer, _, _ = await _call(cad, outputs, monkeypatch, uncounted, run="run-1")
        assert answer["passed"] is False and "attempt" not in answer and "Attempt" not in answer["next"]
    answer, _, _ = await _call(cad, outputs, monkeypatch, BUILT, run="run-1", bbox_xyz_mm=[60, 40])
    assert "attempt" not in answer and "Correct the arguments" in answer["next"]
    counted, _, _ = await _call(cad, outputs, monkeypatch, REFUSED, run="run-1")
    assert counted["attempt"] == 1 and counted["next"].startswith("Attempt 1 of")


@pytest.mark.asyncio
async def test_a_host_that_stamps_no_run_still_counts_and_a_pass_ends_the_count(cad, outputs, monkeypatch):
    first, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, hole_diameters_mm=[4, 4])
    second, _, _ = await _call(cad, outputs, monkeypatch, BUILT, hole_diameters_mm=[4, 4])
    third, _, _ = await _call(cad, outputs, monkeypatch, ONE_HOLE, hole_diameters_mm=[4, 4], bbox_xyz_mm=[60, 40, 9])
    assert [answer["attempt"] for answer in (first, second, third)] == [1, 2, 1]
    assert "expected_changed" not in third


@pytest.mark.asyncio
async def test_a_result_of_several_loose_bodies_says_what_this_tool_cannot_deliver(cad, outputs, monkeypatch):
    # What a loop over links builds when the links do not touch. No change to such a script passes, so the answer says so.
    answer, _, _ = await _call(cad, outputs, monkeypatch, {**BUILT, "measured": {**MEASURED, "solids": 4}}, run="run-1")
    assert answer["passed"] is False
    (note,) = [note for note in answer["notes"] if "separate bodies" in note]
    assert note.startswith("The result is 4 separate bodies") and "overlap or share a face" in note
    # One instruction, in the field a model follows, with both ways out. The note and `next` used to disagree.
    assert answer["next"].startswith("Attempt 1 of 8. The result is several separate bodies")
    assert "call cad_build again with the same name" in answer["next"] and "print-in-place" in answer["next"] and "tell the user" in answer["next"]
    assert "Read what failed, change the script" not in answer["next"]
    one, _, _ = await _call(cad, outputs, monkeypatch, BUILT, run="run-1", name="one body")
    assert "notes" not in one and "separate bodies" not in one["next"]


def test_the_table_of_counted_parts_does_not_grow_for_ever(monkeypatch):
    monkeypatch.syspath_prepend(str(PACKAGE))
    from deerflow_extension_cad import tool

    attempts = tool.Attempts()
    for index in range(tool.MAX_COUNTED_PARTS + 5):
        assert attempts.record(f"thread-{index}", "part", "run", {"bbox_xyz_mm": [1, 1, 1]}, False, "x")[0] == 1
        # A part being rebuilt right now is not what makes room: the one built longest ago is.
        assert attempts.record("thread-busy", "bracket", "run", {"bbox_xyz_mm": [1, 1, 1]}, False, f"failure {index}")[0] == index + 1
    assert len(attempts._parts) == tool.MAX_COUNTED_PARTS
    assert attempts.record("thread-0", "part", "run", {"bbox_xyz_mm": [1, 1, 1]}, False, "x")[0] == 1
    assert attempts.record(f"thread-{tool.MAX_COUNTED_PARTS + 4}", "part", "run", {"bbox_xyz_mm": [1, 1, 1]}, False, "x")[0] == 2


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
@pytest.mark.parametrize(
    ("worker_result", "arguments", "says", "not_says"),
    [
        # The server cannot build at all: trying again with another script is wasted rounds.
        ({"status": "unavailable", "message": "the CAD kernel could not be loaded: libGL.so.1: cannot open shared object file"}, {}, "Do not call cad_build again", "Fix the script"),
        # Every slot is taken: nothing is wrong with the script.
        ({"status": "busy", "message": "the server is building other parts"}, {}, "same arguments", "Fix the script"),
        # The first build after an install or update ran out of time loading the kernel.
        ({"status": "loading", "message": "the CAD kernel was still loading when the time ran out"}, {}, "same arguments", "Fix the script"),
        ({"status": "failed", "line": 3, "operation": "fillet", "message": "fillet() failed"}, {}, "change the script and call cad_build again", "same arguments"),
    ],
    ids=["no kernel on the server", "every build slot taken", "the kernel still loading", "a build error"],
)
async def test_what_to_do_next_follows_the_cause(cad, outputs, monkeypatch, worker_result, arguments, says, not_says):
    answer, _, _ = await _call(cad, outputs, monkeypatch, worker_result, **arguments)
    assert answer["passed"] is False
    assert says in answer["next"] and not_says not in answer["next"]
    # A build that never started leaves nothing behind, not even the script.
    assert (_files(outputs) == []) is (worker_result["status"] in ("busy", "loading"))


@pytest.mark.asyncio
async def test_a_kernel_that_never_finishes_loading_does_not_keep_a_model_calling(cad, outputs, monkeypatch):
    # "Call again" is right for a fresh install, where each attempt leaves more of the kernel compiled.
    # Where nothing can be kept (a read-only environment), it would be an endless loop.
    loading = {"status": "loading", "message": "the CAD kernel was still loading when the time ran out"}
    refused = {"status": "refused", "construct": "import", "line": 1, "message": "the only import a script may contain is: import cadquery as cq"}
    first, _, _ = await _call(cad, outputs, monkeypatch, loading)
    second, _, _ = await _call(cad, outputs, monkeypatch, loading)
    assert "same arguments" in first["next"] and "next build is quick" in second["next"]
    # A refused script never loads the kernel, so it says nothing about whether the kernel can.
    await _call(cad, outputs, monkeypatch, refused)
    third, _, _ = await _call(cad, outputs, monkeypatch, loading)
    assert "Do not call cad_build again" in third["next"] and "make doctor" in third["next"]
    assert "quick" not in third["next"] and "quick" not in third["error"]["message"]
    # The count is this conversation's: someone else asking after the same restart is on a first attempt.
    other, _, _ = await _call(cad, outputs, monkeypatch, loading, conversation="thread-b")
    assert "same arguments" in other["next"]
    # A build that got past loading clears the count.
    await _call(cad, outputs, monkeypatch, BUILT)
    again, _, _ = await _call(cad, outputs, monkeypatch, loading)
    assert "same arguments" in again["next"]


@pytest.mark.asyncio
async def test_what_the_checks_do_not_cover_reaches_the_model(cad, outputs, monkeypatch):
    holes = [{"diameter_mm": 4.0, "through": True, "depth_mm": 6.0}, {"diameter_mm": 4.0, "through": False, "depth_mm": 0.5}]
    measured = {**MEASURED, "enclosed_voids": 1, "unused_outline": True, "mesh": {"tolerance_mm": 0.4, "angular_rad": 0.8}, "holes": holes}
    answer, _, _ = await _call(cad, outputs, monkeypatch, {**BUILT, "measured": measured}, hole_diameters_mm=[4, 4])
    assert answer["passed"] is True
    notes = " ".join(answer["notes"])
    assert "sealed" in notes and "outline" in notes and "coarser" in notes
    solid = next(check for check in answer["checks"] if check["check"] == "one closed solid")
    assert "1 sealed cavity" in solid["measured"]
    holes = next(check for check in answer["checks"] if check["check"] == "holes")
    assert holes["blind_depths_mm"] == [0.5]
    # A hole that crosses two walls is one hole, and the answer says why the count is what it is.
    through_both = {**MEASURED, "holes": [{"diameter_mm": 8.0, "through": True, "depth_mm": 80.0, "walls": 2}]}
    answer, _, _ = await _call(cad, outputs, monkeypatch, {**BUILT, "measured": through_both}, hole_diameters_mm=[8])
    assert any("1 hole passes through 2 walls" in note for note in answer["notes"])
    # A plain part carries none of it.
    plain, _, _ = await _call(cad, outputs, monkeypatch, {**BUILT, "measured": {**MEASURED, "mesh": {"tolerance_mm": 0.1, "angular_rad": 0.3}}}, volume_min_max_mm3=[14000, 14400], hole_diameters_mm=[4, 4])
    assert "notes" not in plain and "unchecked" not in plain and "blind_depths_mm" not in next(check for check in plain["checks"] if check["check"] == "holes")


@pytest.mark.asyncio
async def test_what_was_measured_and_not_asked_about_is_given(cad, outputs, monkeypatch):
    # With only a bounding box to meet, a missing hole passes. The model is at least shown what is there.
    answer, _, _ = await _call(cad, outputs, monkeypatch, BUILT)
    assert answer["passed"] is True
    assert answer["unchecked"] == {"volume_mm3": 14249.2, "hole_diameters_mm": [4.0, 4.0]}
    answer, _, _ = await _call(cad, outputs, monkeypatch, BUILT, hole_diameters_mm=[4, 4])
    assert answer["unchecked"] == {"volume_mm3": 14249.2}


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
    assert any("plate.stl (4 KB) was not saved (LIMIT_EXCEEDED)" in problem for problem in answer["problems"])
    assert _files(outputs) == ["plate.glb", "plate.py", "plate.report.json"]
    # The script is not at fault, and the answer does not say it is.
    assert "could not all be stored" in answer["next"] and "Fix the script" not in answer["next"]


@pytest.mark.asyncio
async def test_a_build_whose_script_cannot_be_stored_stores_nothing(cad, outputs, monkeypatch):
    import deerflow_extension_cad.tool as cad_tool

    from deerflow.config.app_config import AppConfig, PluginOutputsConfig
    from deerflow.config.sandbox_config import SandboxConfig

    async def worker(script, **limits):
        return {"status": "built", "measured": MEASURED, "files": {"step": b"S", "stl": b"L", "glb": b"g"}}

    monkeypatch.setattr(cad_tool, "run_worker", worker)
    (tool,) = build_plugin_tools(cad)
    graph = StateGraph(_State)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    # The script is the first file and names the set: a cap below its size refuses it and lets the small files through.
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"), plugin_outputs=PluginOutputsConfig(max_file_bytes=len(PLATE) - 1, max_call_bytes=1024 * 1024))
    state = await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "cad-call", "name": tool.name, "args": {"name": "plate", "script": PLATE, "bbox_xyz_mm": [60, 40, 6]}}])], "thread_data": {"outputs_path": str(outputs)}},
        context={"user_id": "alice", "thread_id": "thread-a", "app_config": config},
    )
    answer = json.loads(state["messages"][-1].content)
    assert answer["passed"] is False and answer["files"] == []
    assert _files(outputs) == []
    assert "could not be stored" in answer["error"]["message"] and "Tell the user" in answer["next"]

    # The same refusal by the host, for a script the reader refused: the model still learns why, and what to fix.
    async def refusing(script, **limits):
        return {"status": "refused", "construct": "import", "line": 1, "message": "the only import a script may contain is: import cadquery as cq"}

    monkeypatch.setattr(cad_tool, "run_worker", refusing)
    state = await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "cad-call-2", "name": tool.name, "args": {"name": "plate", "script": PLATE, "bbox_xyz_mm": [60, 40, 6]}}])], "thread_data": {"outputs_path": str(outputs)}},
        context={"user_id": "alice", "thread_id": "thread-a", "app_config": config},
    )
    answer = json.loads(state["messages"][-1].content)
    assert answer["error"] == {"construct": "import", "line": 1, "message": "the only import a script may contain is: import cadquery as cq"}
    assert "Fix the script" in answer["next"] and "met its checks" not in answer["next"] and answer["files"] == []


@pytest.mark.asyncio
async def test_the_tool_does_not_start_a_build_it_could_not_hand_over(cad, monkeypatch):
    import deerflow_extension_cad.tool as cad_tool

    async def must_not_run(script, **limits):
        raise AssertionError("no conversation, no build")

    monkeypatch.setattr(cad_tool, "run_worker", must_not_run)
    (tool,) = build_plugin_tools(cad)
    runtime = SimpleNamespace(context={"user_id": "alice"}, config={"configurable": {"user_id": "alice"}}, state={}, tool_call_id="c")
    answer = json.loads(await tool.coroutine(runtime=runtime, name="plate", script=PLATE, bbox_xyz_mm=[60, 40, 6]))
    assert answer["passed"] is False and "cannot receive files" in answer["error"]["message"]
    assert answer["files"] == [] and answer["next"]


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
        # Valid for the schema, and fatal later: a number no float can hold, a character no file can.
        ({"bbox_xyz_mm": [10**400, 40, 6]}, "bbox_xyz_mm must be three positive numbers"),
        ({"volume_min_max_mm3": [0, 10**400]}, "volume_min_max_mm3 must be [min, max]"),
        # Not numbers. The schema leaves the items untyped to keep the tool small, so this is where they are caught.
        ({"hole_diameters_mm": ["4"]}, "hole_diameters_mm must list one positive diameter"),
        ({"bbox_xyz_mm": [60, 40, True]}, "bbox_xyz_mm must be three positive numbers"),
        ({"volume_min_max_mm3": ["1", "2"]}, "volume_min_max_mm3 must be [min, max]"),
        ({"name": "plate \ud83d"}, "name contains a character"),
        ({"script": PLATE + "# \ud83d\n"}, "script contains a character"),
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
    assert answer["files"] == [] and "Correct the arguments" in answer["next"]


def test_the_schema_the_model_sees_is_structure_only_and_requires_the_size(cad):
    from jsonschema import Draft202012Validator

    ((_, plugin),) = cad.plugins
    schema = dict(plugin.tools[0].input_schema)
    validator = Draft202012Validator(schema)
    good = {"name": "plate", "script": PLATE, "bbox_xyz_mm": [60, 40, 6]}
    assert validator.is_valid(good) and validator.is_valid({**good, "volume_min_max_mm3": [1, 2], "hole_diameters_mm": []})
    for bad in ({"name": "plate", "script": PLATE}, {**good, "bbox_xyz_mm": "60x40x6"}, {**good, "script": 5}, {**good, "hole_diameters_mm": 4}):
        assert not validator.is_valid(bad)
    # Descriptions and item types cost every request of every conversation; the parameter
    # names carry the meaning and the handler checks the numbers.
    assert all(set(spec) == {"type"} for spec in schema["properties"].values())
