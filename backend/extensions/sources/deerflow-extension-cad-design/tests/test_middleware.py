import json
from types import SimpleNamespace

import pytest
from deerflow_extension_cad_design.constants import CAD_BUILD_TOOL, SCAD_DRAFT_TOOL, bound_tool_name
from deerflow_extension_cad_design.middleware import Contributor, DesignMode, final_from_answer
from deerflow_extension_cad_design.notes import DIFF_CHARS
from deerflow_extension_cad_design.store import Store
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.types import Command

DESIGN = "a" * 32
OTHER_TOOL = {"type": "function", "function": {"name": "web_search", "description": "", "parameters": {}}}
DRAFT_TOOL = {"type": "function", "function": {"name": SCAD_DRAFT_TOOL, "description": "", "parameters": {}}}


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "d.sqlite")
    store.create_design("alice", DESIGN, "One", "thread-1")
    return store


def request(context, tools=(OTHER_TOOL, DRAFT_TOOL)):
    return ModelRequest(model=None, messages=[], system_message=SystemMessage(content="BASE"), tools=list(tools), state={}, runtime=SimpleNamespace(context=context))


def flagged(phase="draft", head=None, thread="thread-1"):
    return {"thread_id": thread, "plugin_options": {"cad-design": {"design_id": DESIGN, "head": head, "phase": phase}}}


def run(middleware, req):
    seen = []
    middleware.wrap_model_call(req, lambda r: seen.append(r) or "ok")
    return seen[0]


async def arun(middleware, req):
    seen = []

    async def handler(r):
        seen.append(r)
        return "ok"

    await middleware.awrap_model_call(req, handler)
    return seen[0]


def test_the_bound_names_match_the_host():
    plugin_tools = pytest.importorskip("deerflow.extensions.plugin_tools")
    assert bound_tool_name("cad-design", "scad_draft") == plugin_tools.plugin_tool_name("cad-design", "scad_draft") == SCAD_DRAFT_TOOL
    assert plugin_tools.plugin_tool_name("cad", "cad_build") == CAD_BUILD_TOOL
    assert SCAD_DRAFT_TOOL.startswith("ext_cad_design_")


@pytest.mark.parametrize("context", [{}, {"thread_id": "thread-1"}, flagged(thread="thread-2"), {"thread_id": "thread-1", "plugin_options": {"cad-design": {"design_id": "../x"}}}])
async def test_without_a_design_run_the_tool_goes_and_nothing_is_added(store, context):
    middleware = DesignMode(store)
    for sent in (run(middleware, request(context)), await arun(middleware, request(context))):
        assert sent.tools == [OTHER_TOOL]
        assert sent.system_message.content == "BASE"


def test_no_flag_never_touches_the_store(tmp_path):
    store = Store(tmp_path / "never.sqlite")
    run(DesignMode(store), request({"thread_id": "t"}))
    assert not store.exists()


async def test_a_design_run_keeps_the_tool_and_gets_the_brief(store):
    sent = await arun(DesignMode(store), request(flagged()))
    assert sent.tools == [OTHER_TOOL, DRAFT_TOOL]
    text = sent.system_message.content
    assert text.startswith("BASE\n\n## Design page")
    assert "Customizer" in text and "$fn at 64" in text and "No version yet" in text


def test_the_note_carries_the_render_and_the_users_edits(store):
    base = store.add_version("alice", DESIGN, parent_id=None, source="model", scad="w = 4;\ncube(w);\n", params={})
    edit = store.add_version("alice", DESIGN, parent_id=base["id"], source="slider", scad="w = 9;\ncube(w);\n", params={})
    store.set_render("alice", DESIGN, edit["id"], {"ok": False, "partial": False, "error": "Parser error", "error_lines": [2]})
    text = run(DesignMode(store), request(flagged())).system_message.content
    assert "Head: v2 (slider)" in text and "FAILED (lines 2): Parser error" in text
    assert "-w = 4;" in text and "+w = 9;" in text and "your v1" in text
    store.set_render("alice", DESIGN, edit["id"], {"ok": True, "partial": False, "bbox_mm": [9, 9, 9], "volume_mm3": 729, "manifold": True})
    text = run(DesignMode(store), request(flagged())).system_message.content
    assert "ok, bbox 9 x 9 x 9 mm, volume 729 mm3, manifold" in text


def test_the_note_is_bounded(store):
    base = store.add_version("alice", DESIGN, parent_id=None, source="model", scad="\n".join(f"p{i} = {i};" for i in range(3000)), params={})
    store.add_version("alice", DESIGN, parent_id=base["id"], source="hand", scad="\n".join(f"p{i} = {i + 1};" for i in range(3000)), params={})
    note = run(DesignMode(store), request(flagged())).system_message.content.split("## Design versions", 1)[1]
    assert len(note) < DIFF_CHARS + 500
    assert "cut; the whole current file is in the user's message" in note


def test_finalize_drops_the_drafting_tool_and_names_the_bbox(store):
    version = store.add_version("alice", DESIGN, parent_id=None, source="model", scad="cube(10);", params={})
    store.set_render("alice", DESIGN, version["id"], {"ok": True, "partial": False, "bbox_mm": [10, 20, 5.5]})
    sent = run(DesignMode(store), request(flagged("finalize", version["id"])))
    assert sent.tools == [OTHER_TOOL]
    assert "finalize" in sent.system_message.content and "[10.0, 20.0, 5.5]" in sent.system_message.content


def cad_close(expected, measured):
    """cad_build's own bounding-box rule (deerflow_extension_cad/checks.py _close): 0.01 mm or 0.1 %."""
    return abs(expected - measured) <= max(0.01, 0.001 * abs(expected))


def cad_answer(bbox=(10, 20, 5.5), expected=(10, 20, 5.5), solid=True):
    """An answer as the real cad_build forms it: `passed` is every check's AND, the box judged at 0.1 %."""
    box_ok = all(cad_close(e, m) for e, m in zip(expected, bbox, strict=True))
    checks = [{"check": "one closed solid", "expected": "x", "measured": "1 solid" if solid else "2 solids", "passed": solid}, {"check": "bounding box", "expected": list(expected), "measured": list(bbox), "passed": box_ok}]
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "files": ["/mnt/user-data/outputs/part.py", "/mnt/user-data/outputs/part.glb"],
        "attempt": 1,
        "next": "Tell the user.",
    }


def test_the_cad_answer_fixture_is_what_cad_build_returns():
    checks = pytest.importorskip("deerflow_extension_cad.checks")
    assert checks.LENGTH_TOLERANCE_MM == 0.01 and checks.LENGTH_TOLERANCE_RATIO == 0.001


def test_final_from_answer():
    built = final_from_answer(cad_answer(), {"status": "running", "run_id": "run-1"}, [10, 20, 5.5])
    assert built["status"] == "built" and built["files"] == ["part.py", "part.glb"] and built["run_id"] == "run-1"
    assert built["bbox_mm"] == [10, 20, 5.5] and built["tolerance_mm"] == [0.5, 0.5, 0.5]
    # cad_build fails these on its 0.1 % box check; the page's max(0.5 mm, 2 %) still calls them built.
    near = cad_answer(bbox=(10.4, 20.3, 5.9))
    assert near["passed"] is False
    assert final_from_answer(near, None, [10, 20, 5.5])["status"] == "built"
    mismatch = final_from_answer(cad_answer(bbox=(10, 22, 5.5)), None, [10, 20, 5.5])
    assert mismatch["status"] == "mismatch" and mismatch["draft_bbox_mm"] == [10, 20, 5.5]
    assert final_from_answer(cad_answer(bbox=(101.5, 20, 5.5), expected=(100, 20, 5.5)), None, [100, 20, 5.5])["status"] == "built"  # 2 % of 100 mm
    failed = final_from_answer({"passed": False, "error": {"message": "refused: if"}, "files": []}, None, [1, 1, 1])
    assert failed["status"] == "failed" and failed["message"] == "refused: if"
    # Any other failed check still fails the build, whatever the box says.
    other = final_from_answer(cad_answer(bbox=(10.3, 20, 5.5), solid=False), None, [10, 20, 5.5])
    assert other["status"] == "failed" and other["message"] == "Failed checks: one closed solid, bounding box"


def test_a_faceted_draft_against_its_true_part_is_built():
    """cylinder(r=10) at 30 fragments renders 19.89 mm across; the CadQuery cylinder is 20 mm."""
    draft = [20, 19.89, 5]
    answer = cad_answer(bbox=(20, 20, 5), expected=draft)
    assert answer["passed"] is False  # the real tool's verdict, as the brief makes it
    final = final_from_answer(answer, None, draft)
    assert final["status"] == "built" and final["bbox_mm"] == [20, 20, 5]


def test_the_finalize_brief_says_a_small_size_miss_is_not_a_failure():
    from deerflow_extension_cad_design.notes import FINALIZE_BRIEF

    assert "0.5 mm or 2 %" in FINALIZE_BRIEF and "do not rebuild" in FINALIZE_BRIEF


async def test_the_finalize_build_is_recorded(store):
    version = store.add_version("alice", DESIGN, parent_id=None, source="model", scad="cube(10);", params={})
    store.set_render("alice", DESIGN, version["id"], {"ok": True, "partial": False, "bbox_mm": [10, 20, 5.5]})
    store.set_final("alice", DESIGN, version["id"], {"status": "running", "files": [], "draft_bbox_mm": [10, 20, 5.5], "run_id": "run-1"})
    middleware = DesignMode(store)
    message = ToolMessage(content=json.dumps(cad_answer(bbox=(10, 25, 5.5))), tool_call_id="c", name=CAD_BUILD_TOOL)
    call = SimpleNamespace(tool_call={"name": CAD_BUILD_TOOL, "id": "c", "args": {}}, runtime=SimpleNamespace(context=flagged("finalize", version["id"])))

    async def handler(_):
        return Command(update={"messages": [message], "artifacts": []})

    result = await middleware.awrap_tool_call(call, handler)
    assert isinstance(result, Command)
    final = store.get_version("alice", DESIGN, version["id"])["final"]
    assert final["status"] == "mismatch" and final["bbox_mm"] == [10, 25, 5.5] and final["run_id"] == "run-1"
    # The next turn's note says so.
    text = run(middleware, request(flagged("draft", version["id"]))).system_message.content
    assert "measured 10 x 25 x 5.5 mm against the draft's 10 x 20 x 5.5 mm" in text


async def test_builds_outside_a_finalize_run_are_not_recorded(store):
    version = store.add_version("alice", DESIGN, parent_id=None, source="model", scad="cube(10);", params={})
    middleware = DesignMode(store)
    message = ToolMessage(content=json.dumps(cad_answer()), tool_call_id="c", name=CAD_BUILD_TOOL)
    for context in ({"thread_id": "thread-1"}, flagged("draft", version["id"]), flagged("finalize", version["id"], thread="thread-2")):
        call = SimpleNamespace(tool_call={"name": CAD_BUILD_TOOL, "id": "c", "args": {}}, runtime=SimpleNamespace(context=context))

        async def handler(_):
            return message

        assert await middleware.awrap_tool_call(call, handler) is message
    assert store.get_version("alice", DESIGN, version["id"])["final"] is None


def test_the_contributor_is_lead_only(store):
    from deerflow_extension_api import AgentScope, Placement

    contributor = Contributor(store)
    placed = contributor.contribute_middlewares(None, SimpleNamespace(scope=AgentScope.LEAD))
    assert len(placed) == 1 and placed[0].placement == Placement.MODEL_LOGICAL
    assert placed[0].scope == AgentScope.LEAD and isinstance(placed[0].middleware, DesignMode)


async def test_subagents_never_receive_the_drafting_tool(store):
    """The host binds plugin tools into delegated subagents too; they never draft, flagged run or not."""
    from deerflow_extension_api import AgentScope, Placement

    placed = Contributor(store).contribute_middlewares(None, SimpleNamespace(scope=AgentScope.SUBAGENT))
    assert len(placed) == 1 and placed[0].placement == Placement.MODEL_LOGICAL and placed[0].scope == AgentScope.SUBAGENT
    middleware = placed[0].middleware
    for context in ({}, flagged()):
        for sent in (run(middleware, request(context)), await arun(middleware, request(context))):
            assert sent.tools == [OTHER_TOOL]
            assert sent.system_message.content == "BASE"
    assert run(middleware, request({}, tools=(OTHER_TOOL,))).tools == [OTHER_TOOL]
