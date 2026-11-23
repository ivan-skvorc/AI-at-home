import pytest
from conftest import action_context
from deerflow_extension_api import AgentRunError

from deerflow_extension_cad_design.actions import ACTIONS, Designs, simplify_messages
from deerflow_extension_cad_design.constants import CAD_BUILD_TOOL, SCAD_DRAFT_TOOL

CUBE = "size = 10; // [1:1:50]\ncube(size);\n"


async def new_design(designs, runs, user="alice", title="Bracket"):
    return (await designs.create_design({"title": title}, action_context(user, runs)))["design"]


async def model_version(designs, design, scad=CUBE, user="alice"):
    return designs.store.add_version(user, design["id"], parent_id=design.get("head_version_id"), source="model", scad=scad, params={"size": 10})


def test_every_declared_action_exists():
    for name in ACTIONS:
        assert callable(getattr(Designs, name)), name


async def test_create_makes_a_hidden_owned_thread(designs, runs):
    design = await new_design(designs, runs)
    assert runs.threads == [{"thread_id": "thread-1", "metadata": {"cad_design_id": design["id"], "deerflow_listed": False}}]
    assert design["thread_id"] == "thread-1" and design["title"] == "Bracket"
    listed = await designs.list_designs({}, action_context("alice", runs))
    assert [d["id"] for d in listed["designs"]] == [design["id"]]
    assert listed["designs"][0]["thumbnail"] is None and listed["designs"][0]["versions"] == 0
    assert (await designs.list_designs({}, action_context("bob", runs)))["designs"] == []


async def test_a_refused_create_deletes_its_thread(designs, runs, monkeypatch):
    import deerflow_extension_cad_design.store as store_module

    monkeypatch.setattr(store_module, "MAX_DESIGNS_PER_OWNER", 1)
    await new_design(designs, runs)
    with pytest.raises(AgentRunError) as refused:
        await new_design(designs, runs)
    assert refused.value.status_code == 409
    assert runs.deleted == ["thread-2"]


async def test_other_users_get_404(designs, runs):
    design = await new_design(designs, runs)
    for name, payload in (
        ("get_design", {"design_id": design["id"]}),
        ("rename_design", {"design_id": design["id"], "title": "x"}),
        ("delete_design", {"design_id": design["id"]}),
        ("prompt", {"design_id": design["id"], "text": "hi"}),
        ("messages", {"design_id": design["id"]}),
    ):
        with pytest.raises(AgentRunError) as caught:
            await getattr(designs, name)(payload, action_context("bob", runs))
        assert caught.value.status_code == 404, name


async def test_ids_are_validated(designs, runs):
    for payload in ({"design_id": "../x"}, {"design_id": "A" * 32}, {}):
        with pytest.raises(ValueError):
            await designs.get_design(payload, action_context("alice", runs))
    design = await new_design(designs, runs)
    with pytest.raises(ValueError):
        await designs.run_status({"design_id": design["id"], "run_id": "a/b"}, action_context("alice", runs))


async def test_without_a_session_handle_runs_are_unavailable(designs):
    with pytest.raises(AgentRunError) as caught:
        await designs.create_design({}, action_context("alice", None))
    assert caught.value.status_code == 503


async def test_rename_delete_restore_purge(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    assert (await designs.rename_design({"design_id": design["id"], "title": "  New   name "}, context))["design"]["title"] == "New name"
    await designs.delete_design({"design_id": design["id"]}, context)
    trash = (await designs.list_designs({"trash": True}, context))["designs"]
    assert [d["id"] for d in trash] == [design["id"]] and trash[0]["deleted_at"]
    await designs.restore_design({"design_id": design["id"]}, context)
    with pytest.raises(AgentRunError):
        await designs.purge_design({"design_id": design["id"]}, context)
    await designs.delete_design({"design_id": design["id"]}, context)
    assert await designs.purge_design({"design_id": design["id"]}, context) == {"purged": True}


async def test_purge_deletes_the_designs_thread_too(designs, runs):
    """The thread holds every prompt, draft and build output and is unlisted, so it goes with the design."""
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    await designs.delete_design({"design_id": design["id"]}, context)
    runs.delete_refuse = (409, "Thread has work in flight")
    with pytest.raises(AgentRunError) as busy:
        await designs.purge_design({"design_id": design["id"]}, context)
    assert busy.value.status_code == 409
    assert [d["id"] for d in (await designs.list_designs({"trash": True}, context))["designs"]] == [design["id"]]
    runs.delete_refuse = (404, "Thread not found")  # already gone: the rows still go
    assert await designs.purge_design({"design_id": design["id"]}, context) == {"purged": True}
    assert (await designs.list_designs({"trash": True}, context))["designs"] == []
    second = await new_design(designs, runs, title="Two")
    runs.delete_refuse = None
    await designs.delete_design({"design_id": second["id"]}, context)
    await designs.purge_design({"design_id": second["id"]}, context)
    assert runs.deleted == [second["thread_id"]]
    with pytest.raises(AgentRunError) as foreign:
        await designs.purge_design({"design_id": design["id"]}, action_context("bob", runs))
    assert foreign.value.status_code == 404


async def test_save_version_and_report_render(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    base = await model_version(designs, design)
    saved = (await designs.save_version({"design_id": design["id"], "parent_id": base["id"], "scad": "cube(3);", "params": {"size": 3}, "source": "slider"}, context))["version"]
    assert (saved["seq"], saved["source"], saved["parent_id"]) == (2, "slider", base["id"])
    for bad in ({"source": "model"}, {"params": {"bad name": 1}}, {"params": {"x": "1"}}, {"scad": "x" * 70000}):
        with pytest.raises(ValueError):
            await designs.save_version({"design_id": design["id"], "parent_id": base["id"], "scad": "cube(3);", "params": {}, "source": "hand", **bad}, context)
    render = {"ok": True, "bbox_mm": [10, 10, 10], "volume_mm3": 1000, "manifold": True, "triangles": 12, "ms": 40}
    stored = (await designs.report_render({"design_id": design["id"], "version_id": saved["id"], "render": render}, context))["version"]
    assert stored["render"] == {"ok": True, "partial": False, "bbox_mm": [10.0, 10.0, 10.0], "volume_mm3": 1000.0, "manifold": True, "triangles": 12, "ms": 40}
    for bad in ({"ok": True, "partial": True}, {"ok": True, "html": "<b>"}, {"ok": "yes"}, {"ok": True, "bbox_mm": [1, 2]}, {"ok": False, "error_lines": ["1"]}):
        with pytest.raises(ValueError):
            await designs.report_render({"design_id": design["id"], "version_id": saved["id"], "render": bad}, context)


async def test_save_version_is_refused_while_a_run_is_active(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    await designs.prompt({"design_id": design["id"], "text": "a cube"}, context)
    runs.status = "running"
    with pytest.raises(AgentRunError) as caught:
        await designs.save_version({"design_id": design["id"], "parent_id": None, "scad": "cube(1);", "params": {}, "source": "hand"}, context)
    assert caught.value.status_code == 409
    runs.status = "success"
    await designs.save_version({"design_id": design["id"], "parent_id": None, "scad": "cube(1);", "params": {}, "source": "hand"}, context)


async def test_prompt_starts_a_streaming_design_run(designs, runs):
    design = await new_design(designs, runs)
    version = await model_version(designs, design)
    answer = await designs.prompt({"design_id": design["id"], "text": "make it taller", "model_name": "qwen3:8b", "mode": "thinking"}, action_context("alice", runs))
    assert answer == {"run_id": "run-1", "thread_id": "thread-1"}
    started = runs.started[0]
    assert started["stream_mode"] == ["values", "messages-tuple"]
    assert started["input"] == {"messages": [{"role": "user", "content": "make it taller"}]}
    assert started["context"] == {
        "plugin_options": {"cad-design": {"design_id": design["id"], "head": version["id"], "phase": "draft"}},
        "model_name": "qwen3:8b",
        "thinking_enabled": True,
    }
    assert designs.store.get_design("alice", design["id"])["run_id"] == "run-1"
    for bad in ({"text": ""}, {"text": "x" * 9000}, {"text": "hi", "mode": "ultracode"}, {"text": "hi", "model_name": "a b"}):
        with pytest.raises(ValueError):
            await designs.prompt({"design_id": design["id"], **bad}, action_context("alice", runs))


async def test_a_long_hand_edit_rides_the_prompt_in_full(designs, runs):
    design = await new_design(designs, runs)
    base = await model_version(designs, design, scad="\n".join(f"p{i} = {i};" for i in range(200)))
    edited = "\n".join(f"p{i} = {i + 1};" for i in range(200))
    designs.store.add_version("alice", design["id"], parent_id=base["id"], source="hand", scad=edited, params={})
    await designs.prompt({"design_id": design["id"], "text": "go on"}, action_context("alice", runs))
    assert edited in runs.started[0]["input"]["messages"][0]["content"]


async def test_repair_once_per_failed_model_version(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    version = await model_version(designs, design)
    with pytest.raises(AgentRunError):  # no failed render yet
        await designs.repair({"design_id": design["id"], "version_id": version["id"]}, context)
    await designs.report_render({"design_id": design["id"], "version_id": version["id"], "render": {"ok": False, "error": "syntax error", "error_lines": [2]}}, context)
    await designs.repair({"design_id": design["id"], "version_id": version["id"]}, context)
    assert runs.started[0]["context"]["plugin_options"]["cad-design"]["phase"] == "repair"
    with pytest.raises(AgentRunError) as caught:
        await designs.repair({"design_id": design["id"], "version_id": version["id"]}, context)
    assert caught.value.status_code == 409
    fixed = designs.store.add_version("alice", design["id"], parent_id=version["id"], source="repair", scad="cube(1);", params={})
    await designs.report_render({"design_id": design["id"], "version_id": fixed["id"], "render": {"ok": False, "error": "still"}}, context)
    with pytest.raises(AgentRunError):  # a repair's own failure gets no second repair
        await designs.repair({"design_id": design["id"], "version_id": fixed["id"]}, context)


async def test_finalize_needs_a_good_render_and_marks_running(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    version = await model_version(designs, design)
    with pytest.raises(AgentRunError):
        await designs.finalize({"design_id": design["id"], "version_id": version["id"]}, context)
    await designs.report_render({"design_id": design["id"], "version_id": version["id"], "render": {"ok": True, "bbox_mm": [10, 10, 10]}}, context)
    await designs.finalize({"design_id": design["id"], "version_id": version["id"]}, context)
    started = runs.started[0]
    assert started["context"]["plugin_options"]["cad-design"] == {"design_id": design["id"], "head": version["id"], "phase": "finalize"}
    assert CUBE in started["input"]["messages"][0]["content"]
    final = designs.store.get_version("alice", design["id"], version["id"])["final"]
    assert final == {"status": "running", "files": [], "draft_bbox_mm": [10.0, 10.0, 10.0], "run_id": "run-1"}
    # The run ends without a build: run_status says so instead of "running" forever.
    runs.status = "success"
    assert (await designs.run_status({"design_id": design["id"], "run_id": "run-1"}, context)) == {"status": "success"}
    final = designs.store.get_version("alice", design["id"], version["id"])["final"]
    assert final["status"] == "failed"
    assert designs.store.get_design("alice", design["id"])["run_id"] is None


async def test_a_refused_finalize_does_not_stay_running(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    version = await model_version(designs, design)
    await designs.report_render({"design_id": design["id"], "version_id": version["id"], "render": {"ok": True, "bbox_mm": [10, 10, 10]}}, context)
    runs.refuse = (409, "busy")
    with pytest.raises(AgentRunError):
        await designs.finalize({"design_id": design["id"], "version_id": version["id"]}, context)
    assert designs.store.get_version("alice", design["id"], version["id"])["final"]["status"] == "failed"


async def test_messages_are_simplified_and_bounded(designs, runs):
    design = await new_design(designs, runs)
    runs.state = {
        "values": {
            "messages": [
                {"type": "system", "content": "secret"},
                {"type": "human", "id": "1", "content": "a cube"},
                {"type": "human", "id": "h", "content": "hidden", "additional_kwargs": {"hide_from_ui": True}},
                {"type": "ai", "id": "2", "content": [{"type": "text", "text": "Here"}], "tool_calls": [{"name": SCAD_DRAFT_TOOL, "args": {"code": "x" * 5000}, "id": "c"}]},
                {"type": "tool", "id": "3", "name": SCAD_DRAFT_TOOL, "content": '{"seq": 1}'},
                {"type": "tool", "id": "4", "name": CAD_BUILD_TOOL, "content": "{}"},
            ]
        }
    }
    shown = (await designs.messages({"design_id": design["id"]}, action_context("alice", runs)))["messages"]
    assert [m["role"] for m in shown] == ["user", "assistant", "tool", "tool"]
    assert shown[1]["text"] == "Here" and shown[1]["tool_calls"][0]["name"] == "scad_draft"
    assert len(shown[1]["tool_calls"][0]["args"]["code"]) < 4100
    assert [shown[2]["tool_name"], shown[3]["tool_name"]] == ["scad_draft", "cad_build"]
    assert len(simplify_messages([{"type": "human", "content": "x"}] * 500)) == 200


async def test_cancel_and_get_version(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    version = await model_version(designs, design)
    await designs.cancel({"design_id": design["id"], "run_id": "run-9"}, context)
    assert runs.cancelled == [("thread-1", "run-9")]
    assert (await designs.get_version({"design_id": design["id"], "version_id": version["id"]}, context))["version"]["scad"] == CUBE
    got = await designs.get_design({"design_id": design["id"]}, context)
    assert got["design"]["head_version_id"] == version["id"] and got["versions"][0]["scad"] == CUBE


async def test_a_file_the_user_wrote_before_any_model_version_reaches_the_model(designs, runs):
    """With no model version to diff against, the note has no diff, so the prompt carries the file."""
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    hand = "wall = 2; // [1:0.5:5]\ncube([40, 20, wall]);\n"
    saved = (await designs.save_version({"design_id": design["id"], "parent_id": None, "scad": hand, "params": {"wall": 2}, "source": "hand"}, context))["version"]
    await designs.prompt({"design_id": design["id"], "text": "make the wall thicker"}, context)
    message = runs.started[-1]["input"]["messages"][0]["content"]
    assert message.startswith("make the wall thicker") and hand in message
    # A slider move on top of it is still the user's own file.
    designs.store.add_version("alice", design["id"], parent_id=saved["id"], source="slider", scad=hand.replace("2;", "3;"), params={"wall": 3})
    runs.status = "success"
    await designs.prompt({"design_id": design["id"], "text": "again"}, context)
    assert "wall = 3;" in runs.started[-1]["input"]["messages"][0]["content"]


async def test_a_short_edit_of_a_model_version_rides_the_note_not_the_message(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    base = await model_version(designs, design)
    designs.store.add_version("alice", design["id"], parent_id=base["id"], source="hand", scad=CUBE.replace("10;", "12;"), params={"size": 12})
    await designs.prompt({"design_id": design["id"], "text": "round it"}, context)
    assert runs.started[-1]["input"]["messages"][0]["content"] == "round it"
