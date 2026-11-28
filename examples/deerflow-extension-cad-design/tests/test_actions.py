from types import SimpleNamespace

import pytest
from conftest import action_context
from deerflow_extension_api import AgentRunError, ExtensionRuntimeDeps, HostPolicySnapshot

from deerflow_extension_cad_design.actions import ACTIONS, MAX_SUMMARY_CHARS, MAX_TOOL_CHARS, Designs, HostSandbox, simplify_messages, summarize_args

FOLDER = "/mnt/user-data/outputs/design"


async def new_design(designs, runs, user="alice", title="Bracket"):
    return (await designs.create_design({"title": title}, action_context(user, runs)))["design"]


def test_every_declared_action_exists():
    for name in ACTIONS:
        assert callable(getattr(Designs, name)), name


def test_the_retired_actions_are_gone():
    # Versions are the run's folders now; the Gateway stores, renders and repairs nothing.
    assert not {"get_version", "save_version", "report_render", "set_head", "repair", "finalize"} & set(ACTIONS)


async def test_create_makes_a_hidden_owned_thread(designs, runs):
    design = await new_design(designs, runs)
    assert runs.threads == [{"thread_id": "thread-1", "metadata": {"cad_design_id": design["id"], "deerflow_listed": False}}]
    assert design["thread_id"] == "thread-1" and design["title"] == "Bracket"
    listed = await designs.list_designs({}, action_context("alice", runs))
    assert listed["designs"] == [{"id": design["id"], "title": "Bracket", "updated_at": design["updated_at"], "deleted_at": None}]
    assert listed["container"] is False
    assert (await designs.list_designs({}, action_context("bob", runs)))["designs"] == []


async def test_a_refused_create_deletes_its_thread(designs, runs, monkeypatch):
    import deerflow_extension_cad_design.store as store_module

    monkeypatch.setattr(store_module, "MAX_DESIGNS_PER_OWNER", 1)
    await new_design(designs, runs)
    with pytest.raises(AgentRunError) as refused:
        await new_design(designs, runs)
    assert refused.value.status_code == 409
    assert runs.deleted == ["thread-2"]


async def test_get_design_names_the_fixed_folder_and_the_host_mode(designs, runs, sandbox):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    assert await designs.get_design({"design_id": design["id"]}, context) == {"design": design, "folder": FOLDER, "container": False}
    # The Gateway hands every service the projected host policy when it starts.
    await sandbox.start(ExtensionRuntimeDeps(policy=HostPolicySnapshot(sandbox_container=True)))
    assert (await designs.get_design({"design_id": design["id"]}, context))["container"] is True
    assert (await designs.list_designs({}, context))["container"] is True
    await sandbox.start(ExtensionRuntimeDeps(policy=HostPolicySnapshot()))
    assert (await designs.get_design({"design_id": design["id"]}, context))["container"] is False


async def test_a_host_older_than_the_flag_reads_as_no_container():
    sandbox = HostSandbox()
    await sandbox.start(SimpleNamespace(policy=SimpleNamespace(token_budget_enabled=False)))
    assert sandbox.container is False
    await sandbox.start(SimpleNamespace(policy=SimpleNamespace(sandbox_container="yes")))
    assert sandbox.container is False
    await sandbox.stop()


async def test_other_users_get_404(designs, runs):
    design = await new_design(designs, runs)
    for name, payload in (
        ("get_design", {"design_id": design["id"]}),
        ("rename_design", {"design_id": design["id"], "title": "x"}),
        ("delete_design", {"design_id": design["id"]}),
        ("prompt", {"design_id": design["id"], "text": "hi"}),
        ("messages", {"design_id": design["id"]}),
        ("run_status", {"design_id": design["id"], "run_id": "run-1"}),
        ("cancel", {"design_id": design["id"], "run_id": "run-1"}),
    ):
        with pytest.raises(AgentRunError) as caught:
            await getattr(designs, name)(payload, action_context("bob", runs))
        assert caught.value.status_code == 404, name
    assert runs.started == [] and runs.cancelled == []


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
    """The thread holds every prompt and version folder and is unlisted, so it goes with the design."""
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    await designs.delete_design({"design_id": design["id"]}, context)
    runs.delete_refuse = (409, "Thread has work in flight")
    with pytest.raises(AgentRunError) as busy:
        await designs.purge_design({"design_id": design["id"]}, context)
    assert busy.value.status_code == 409
    assert [d["id"] for d in (await designs.list_designs({"trash": True}, context))["designs"]] == [design["id"]]
    runs.delete_refuse = (404, "Thread not found")  # already gone: the row still goes
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


#: What the host's composer controls send for Ultra on a thinking model (``runContext()``).
ULTRA = {"model_name": "qwen3:8b", "mode": "ultra", "thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": True, "reasoning_effort": "high", "subagent_model_name": "gpt-4o-mini"}


async def test_prompt_starts_a_streaming_design_run_with_the_chosen_run_context(designs, runs):
    design = await new_design(designs, runs)
    answer = await designs.prompt({"design_id": design["id"], "text": "make it taller", "context": ULTRA}, action_context("alice", runs))
    assert answer == {"run_id": "run-1", "thread_id": "thread-1"}
    started = runs.started[0]
    assert started["stream_mode"] == ["values", "messages-tuple"]
    assert started["input"] == {"messages": [{"role": "user", "content": "make it taller"}]}
    assert started["context"] == {**ULTRA, "plugin_options": {"cad-design": {"design_id": design["id"]}}}
    assert designs.store.get_design("alice", design["id"])["run_id"] == "run-1"


async def test_without_a_run_context_the_server_defaults_apply(designs, runs):
    design = await new_design(designs, runs)
    for payload in ({}, {"context": None}, {"context": {}}, {"context": {"model_name": None, "mode": None}}):
        await designs.prompt({"design_id": design["id"], "text": "a plate", **payload}, action_context("alice", runs))
        assert runs.started[-1]["context"] == {"plugin_options": {"cad-design": {"design_id": design["id"]}}}


async def test_the_run_context_keeps_only_what_the_chat_sends(designs, runs):
    design = await new_design(designs, runs)
    context = {
        **ULTRA,
        # Host-owned or unknown keys never reach the run.
        "agent_name": "other-agent",
        "is_bootstrap": True,
        "thread_id": "thread-9",
        "memory_enabled": True,
        "github_token": "secret",
        "democracy_participants": ["a", "b"],
        "democracy_grading": "boolean",
        "max_total_subagents": 6,
        "max_concurrent_subagents": 2,
    }
    await designs.prompt({"design_id": design["id"], "text": "x", "context": context}, action_context("alice", runs))
    sent = runs.started[-1]["context"]
    assert set(sent) == set(ULTRA) | {"democracy_participants", "democracy_grading", "max_total_subagents", "max_concurrent_subagents", "plugin_options"}
    # Like the chat, a subagent model rides only on a run that delegates.
    await designs.prompt({"design_id": design["id"], "text": "x", "context": {**ULTRA, "mode": "pro", "subagent_enabled": False}}, action_context("alice", runs))
    assert "subagent_model_name" not in runs.started[-1]["context"]


async def test_a_forged_design_flag_is_replaced_and_other_plugins_options_ride_along(designs, runs):
    design = await new_design(designs, runs)
    workflows = {"mode": "ultracode", "max_agents": 10, "max_parallel": 4, "max_minutes": 30, "model": "qwen3:8b"}
    forged = {"cad-design": {"design_id": "f" * 32, "extra": True}, "community.workflows": workflows}
    await designs.prompt({"design_id": design["id"], "text": "x", "context": {**ULTRA, "mode": "ultracode", "plugin_options": forged}}, action_context("alice", runs))
    options = runs.started[-1]["context"]["plugin_options"]
    assert options == {"cad-design": {"design_id": design["id"]}, "community.workflows": workflows}
    assert forged["cad-design"]["design_id"] == "f" * 32, "the page's own object is not mutated"


@pytest.mark.parametrize(
    "context",
    [
        "flash",
        ["mode", "flash"],
        {"mode": "turbo"},
        {"mode": True},
        {"model_name": "a b"},
        {"model_name": 7},
        {"thinking_enabled": "yes"},
        {"is_plan_mode": 1},
        {"subagent_enabled": 0},
        {"reasoning_effort": "very high"},
        {"reasoning_effort": "x" * 33},
        {"subagent_model_name": "two words"},
        {"max_total_subagents": 0},
        {"max_total_subagents": 51},
        {"max_total_subagents": True},
        {"max_concurrent_subagents": 65},
        {"max_concurrent_subagents": 2.5},
        {"democracy_participants": ["a"]},
        {"democracy_participants": ["a", "a"]},
        {"democracy_participants": [f"m{i}" for i in range(13)]},
        {"democracy_participants": "a,b"},
        {"democracy_grading": "ten_point"},
        {"plugin_options": []},
        {"plugin_options": {"x": 1}},
        {"plugin_options": {"a:b": {}}},
        {"plugin_options": {"": {}}},
        {"plugin_options": {"x": {"v": float("nan")}}},
        {"plugin_options": {"x": {"v": object()}}},
        {"plugin_options": {f"p{i}": {} for i in range(9)}},
        # The page's eight plus this design's flag is one namespace too many.
        {"plugin_options": {f"p{i}": {} for i in range(8)}},
        {"plugin_options": {"x": {"v": "y" * 4100}}},
    ],
)
async def test_an_invalid_run_context_is_refused(designs, runs, context):
    design = await new_design(designs, runs)
    with pytest.raises(ValueError):
        await designs.prompt({"design_id": design["id"], "text": "hi", "context": context}, action_context("alice", runs))
    assert runs.started == []


async def test_the_prompt_text_is_bounded(designs, runs):
    design = await new_design(designs, runs)
    for bad in ({"text": ""}, {"text": "  "}, {"text": "x" * 9000}, {}):
        with pytest.raises(ValueError):
            await designs.prompt({"design_id": design["id"], **bad}, action_context("alice", runs))
    assert runs.started == []


async def test_an_older_viewed_version_is_named_in_the_message(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)

    async def sent(**extra):
        await designs.prompt({"design_id": design["id"], "text": "make this one taller", **extra}, context)
        return runs.started[-1]["input"]["messages"][0]["content"]

    older = await sent(viewing=2, newest=5)
    assert older.startswith("make this one taller") and f"v2 ({FOLDER}/v2)" in older and "not the newest" in older
    assert await sent(viewing=5, newest=5) == "make this one taller"
    assert await sent() == "make this one taller"
    # The page may send viewing alone, only when it is not the newest.
    assert f"v3 ({FOLDER}/v3)" in await sent(viewing=3)
    for bad in ({"viewing": 0}, {"viewing": True}, {"viewing": "2"}, {"viewing": 1.5}, {"viewing": 6, "newest": 5}, {"newest": -1}):
        with pytest.raises(ValueError):
            await designs.prompt({"design_id": design["id"], "text": "x", **bad}, context)


async def test_run_status_releases_the_design_once_the_run_ends(designs, runs):
    design = await new_design(designs, runs)
    context = action_context("alice", runs)
    run = await designs.prompt({"design_id": design["id"], "text": "a plate"}, context)
    runs.status = "running"
    assert await designs.run_status({"design_id": design["id"], "run_id": run["run_id"]}, context) == {"status": "running"}
    assert designs.store.get_design("alice", design["id"])["run_id"] == run["run_id"]
    runs.status = "success"
    # Another run's end leaves the design's own run alone.
    await designs.run_status({"design_id": design["id"], "run_id": "run-other"}, context)
    assert designs.store.get_design("alice", design["id"])["run_id"] == run["run_id"]
    assert await designs.run_status({"design_id": design["id"], "run_id": run["run_id"]}, context) == {"status": "success"}
    assert designs.store.get_design("alice", design["id"])["run_id"] is None


async def test_cancel(designs, runs):
    design = await new_design(designs, runs)
    await designs.cancel({"design_id": design["id"], "run_id": "run-9"}, action_context("alice", runs))
    assert runs.cancelled == [("thread-1", "run-9")]


async def test_messages_show_any_tool_by_name_and_one_line(designs, runs):
    design = await new_design(designs, runs)
    render = "python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py render /mnt/user-data/workspace/design/model.scad --design /mnt/user-data/outputs/design --print-layout\necho done"
    runs.state = {
        "values": {
            "messages": [
                {"type": "system", "content": "secret"},
                {"type": "human", "id": "1", "content": "a cube"},
                {"type": "human", "id": "h", "content": "hidden", "additional_kwargs": {"hide_from_ui": True}},
                {
                    "type": "ai",
                    "id": "2",
                    "content": [{"type": "text", "text": "Here"}],
                    "tool_calls": [
                        {"name": "bash", "args": {"description": "Render v1", "command": render}, "id": "a"},
                        {"name": "write_file", "args": {"description": "Write the model", "path": "/mnt/user-data/workspace/design/model.scad", "content": "x" * 50000}, "id": "b"},
                        {"name": "present_files", "args": {"filepaths": [f"/o/{i}.stl" for i in range(8)]}, "id": "c"},
                        {"name": "custom", "args": {"n": 3, "query": "  \n  second line wins\nthird"}, "id": "d"},
                        {"name": "nothing", "args": {"n": 3}, "id": "e"},
                    ],
                },
                {"type": "tool", "id": "3", "name": "bash", "content": "y" * 50000},
            ]
        }
    }
    shown = (await designs.messages({"design_id": design["id"]}, action_context("alice", runs)))["messages"]
    assert [m["role"] for m in shown] == ["user", "assistant", "tool"]
    assert shown[1]["text"] == "Here"
    assert shown[1]["tool_calls"] == [
        {"name": "bash", "summary": render.splitlines()[0]},
        {"name": "write_file", "summary": "/mnt/user-data/workspace/design/model.scad"},
        {"name": "present_files", "summary": "/o/0.stl, /o/1.stl, /o/2.stl, /o/3.stl, /o/4.stl (+3 more)"},
        {"name": "custom", "summary": "second line wins"},
        {"name": "nothing", "summary": ""},
    ]
    assert "args" not in shown[1]["tool_calls"][1], "a call's arguments (a whole file) never reach the page"
    assert shown[2]["tool_name"] == "bash" and len(shown[2]["text"]) == MAX_TOOL_CHARS + 3
    assert len(simplify_messages([{"type": "human", "content": "x"}] * 500)) == 200


def test_summaries_ignore_what_is_not_an_argument_map():
    assert summarize_args(None) == summarize_args(["ls"]) == summarize_args({}) == ""
    assert summarize_args({"command": "", "description": "Look around"}) == "Look around"
    assert summarize_args({"command": "echo " + "x" * 500}) == ("echo " + "x" * 500)[:MAX_SUMMARY_CHARS] + "..."


def test_a_non_string_mode_is_a_bad_value_not_a_server_error():
    from deerflow_extension_cad_design.actions import design_run_context

    for bad in ([], {}, ["flash"], 3):
        try:
            design_run_context({"mode": bad}, "a" * 32)
        except ValueError:
            continue
        raise AssertionError(f"mode={bad!r} was accepted")
