"""Double Plus Ultracode on the script-workflows extension.

Covers what the mode adds on top of the workflow engine (test_workflow_plugin.py):
per-run limits from the user's settings, the lead's brief, phase()/pipeline(),
exactly-once result delivery into the launching conversation (including after
a restart), schema-checked outputs with re-asks, per-step models, shared
workspaces under the operator's policy, child-thread spend links, the spend
cap's clean refusal, the conversation's model and internet switch, launch
refusals the lead can read, retained-record pruning and step-output salvage.
"""

import asyncio
import json
import os
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from deerflow_extension_api import AGENT_RUNS_CONTEXT_KEY, EXTENSION_MESSAGE_ORIGIN_KEY, AgentRun, AgentRunError, ExtensionPrincipal, WorkspaceMerge, WorkspaceSnapshot
from deerflow_extension_api.plugins import ActionContext, ToolContext
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import ToolException
from test_workflow_plugin import Runs

from deerflow.extensions.loader import ExtensionSpec, load_extensions

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Workflow worker execution requires POSIX")

ROOT = Path(__file__).resolve().parents[2]
CONVERSATION = "conversation-1"
NAMESPACE = "community.workflows"


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples/deerflow-extension-workflows"))


class ModeRuns(Runs):
    """The engine's fake host, plus a conversation, workspaces and scripted answers."""

    def __init__(self):
        super().__init__()
        self.threads[CONVERSATION] = {"values": {"messages": []}, "next": [], "interrupts": [], "assistant": "lead_agent"}
        self.created = []
        self.deliveries = []
        self.delivery_contexts = []
        self.contexts = []
        self.copies = []
        self.merges = []
        self.answers = {}
        self.start_error = None
        self.delivery_error = None
        self.merge_result = WorkspaceMerge(applied=("workspace/a.py",), conflicts=("workspace/b.py",), skipped=())

    def for_plugin(self, namespace):
        assert namespace == NAMESPACE
        return self

    async def create_thread(self, *, assistant_id, thread_id, metadata, parent_thread_id=None):
        self.created.append((thread_id, parent_thread_id))
        return await super().create_thread(assistant_id=assistant_id, thread_id=thread_id, metadata=metadata)

    async def start(self, *, thread_id, input, idempotency_key, context=None):
        if thread_id == CONVERSATION:
            if self.delivery_error is not None:
                raise self.delivery_error
            if idempotency_key in self.runs:
                return self.runs[idempotency_key]
            run = AgentRun(thread_id, idempotency_key, "success", "lead_agent")
            self.runs[idempotency_key] = run
            self.deliveries.append((input, idempotency_key))
            self.delivery_contexts.append(context)
            return run
        if self.start_error is not None:
            raise self.start_error
        self.contexts.append(context)
        return await super().start(thread_id=thread_id, input=input, idempotency_key=idempotency_key)

    async def answer(self, run, input):
        scripted = self.answers.get(run.thread_id)
        if scripted is None:
            return await super().answer(run, input)
        await asyncio.sleep(0.01)
        output = scripted.pop(0) if len(scripted) > 1 else scripted[0]
        self.threads[run.thread_id]["values"]["messages"].append({"type": "ai", "content": json.dumps(output)})
        self.runs[run.run_id] = AgentRun(run.thread_id, run.run_id, "success")

    async def copy_workspace(self, *, source_thread_id, thread_id):
        self.copies.append((source_thread_id, thread_id))
        return WorkspaceSnapshot(source_thread_id=source_thread_id, files={"workspace/a.py": "0" * 64, "workspace/b.py": "1" * 64})

    async def merge_workspace(self, *, thread_id, into_thread_id, base):
        self.merges.append((thread_id, into_thread_id, dict(base.files)))
        return self.merge_result


async def load(tmp_path, monkeypatch, **extra):
    monkeypatch.syspath_prepend(str(ROOT / "examples/deerflow-extension-workflows"))
    config = {
        "enabled": True,
        "storage_path": str(tmp_path / "workflows.sqlite"),
        "agents": ["lead_agent"],
        "max_calls": 40,
        "concurrency": 4,
        "timeout_seconds": 10,
        **extra,
    }
    loaded, diagnostics = await asyncio.to_thread(load_extensions, [ExtensionSpec(use="deerflow_extension_workflows:install", config=config)])
    assert not diagnostics, diagnostics
    ((_, declaration),) = loaded.plugins
    actions = {a.name: a.handler for a in declaration.backend}
    service = actions["launch"].__self__
    await service.start(None)
    return loaded, actions, service


@pytest_asyncio.fixture
async def mode(tmp_path, monkeypatch):
    import deerflow_extension_workflows.delivery as delivery

    monkeypatch.setattr(delivery, "RETRY_DELAYS", (0.01,))
    loaded, actions, service = await load(tmp_path, monkeypatch)
    runs = ModeRuns()
    yield SimpleNamespace(loaded=loaded, actions=actions, service=service, runs=runs, tmp_path=tmp_path, monkeypatch=monkeypatch)
    await service.stop()
    await runs.close()


def tool_context(runs, options=None, thread_id=CONVERSATION, owner="alice"):
    return ToolContext(ExtensionPrincipal(owner), {"enabled": True}, thread_id, agent_runs=runs, run_options=options or {})


def session(runs, owner="alice"):
    return ActionContext(ExtensionPrincipal(owner), {"enabled": True}, agent_runs=runs, interaction="session")


def lead_tool(env, name, options=None, owner="alice"):
    """A model tool behind the host's production wrapper, as the lead calls it."""
    from deerflow.extensions.plugin_tools import build_plugin_tools, plugin_tool_name

    tool = next(t for t in build_plugin_tools(env.loaded) if t.name == plugin_tool_name(NAMESPACE, name))
    context = {"thread_id": CONVERSATION, AGENT_RUNS_CONTEXT_KEY: env.runs, "user_id": owner}
    if options:
        context["plugin_options"] = {NAMESPACE: options}
    runtime = SimpleNamespace(context=context, config={"configurable": {"user_id": owner}})

    async def call(**payload):
        return json.loads(await tool.coroutine(runtime=runtime, **payload))

    return call


async def finish(env, run_id):
    await asyncio.wait_for(env.service.wait_idle(run_id), 10)
    return await env.actions["get"]({"run_id": run_id}, session(env.runs))


async def delivered(env, run_id):
    for _ in range(500):
        record = await asyncio.to_thread(env.service.store.delivery, "alice", run_id)
        if record and record["status"] != "pending":
            return record
        await asyncio.sleep(0.01)
    return await asyncio.to_thread(env.service.store.delivery, "alice", run_id)


ULTRACODE = {"mode": "ultracode", "max_agents": 3, "max_parallel": 1}


@pytest.mark.asyncio
async def test_settings_limits_lower_the_run_and_never_raise_it(mode):
    launched = await mode.service.launch({"request_id": "small", "script": "return 1;"}, tool_context(mode.runs, ULTRACODE))
    record = await finish(mode, launched["run_id"])
    assert record["mode"] == "ultracode"
    assert record["limits"]["max_calls"] == 3 and record["limits"]["concurrency"] == 1
    # Above the operator's values the settings change nothing; other runs ignore them.
    greedy = await mode.service.launch({"request_id": "greedy", "script": "return 1;"}, tool_context(mode.runs, {"mode": "ultracode", "max_agents": 10_000, "max_parallel": 999}))
    assert (await finish(mode, greedy["run_id"]))["limits"]["max_calls"] == 40
    plain = await mode.service.launch({"request_id": "plain", "script": "return 1;"}, tool_context(mode.runs, {"max_agents": 1}))
    plain_record = await finish(mode, plain["run_id"])
    assert plain_record["mode"] is None and plain_record["limits"]["max_calls"] == 40


@pytest.mark.asyncio
async def test_settings_time_limit_shortens_the_run_and_never_lengthens_it(tmp_path, monkeypatch):
    import deerflow_extension_workflows.delivery as delivery

    monkeypatch.setattr(delivery, "RETRY_DELAYS", (0.01,))
    _, _, service = await load(tmp_path, monkeypatch, timeout_seconds=600)
    runs = ModeRuns()
    try:
        short = await service.launch({"request_id": "short", "script": "return 1;"}, tool_context(runs, {**ULTRACODE, "max_minutes": 2}))
        await asyncio.wait_for(service.wait_idle(short["run_id"]), 10)
        long = await service.launch({"request_id": "long", "script": "return 1;"}, tool_context(runs, {**ULTRACODE, "max_minutes": 999}))
        await asyncio.wait_for(service.wait_idle(long["run_id"]), 10)
        get = lambda run_id: service.store.get("alice", run_id)  # noqa: E731
        assert (await asyncio.to_thread(get, short["run_id"]))["limits"]["timeout_seconds"] == 120
        assert (await asyncio.to_thread(get, long["run_id"]))["limits"]["timeout_seconds"] == 600
    finally:
        await service.stop()
        await runs.close()


@pytest.mark.asyncio
async def test_the_run_wall_clock_comes_from_the_record_not_the_operator(mode):
    import deerflow_extension_workflows.service as service_module

    mode.monkeypatch.setattr(service_module, "run_limits", lambda options, config: {"max_calls": 3, "concurrency": 1, "timeout_seconds": 1})

    async def slow(run, input):
        await asyncio.sleep(5)

    mode.runs.answer = slow
    launched = await mode.service.launch({"request_id": "slow", "script": "await agent({stepId:'a', agentRef:'lead_agent', task:'x'}); return 1;"}, tool_context(mode.runs, ULTRACODE))
    started = asyncio.get_running_loop().time()
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "failed" and "Execution deadline exceeded" in record["error"]
    assert asyncio.get_running_loop().time() - started < 4  # the operator's 10 s would still be running


@pytest.mark.asyncio
async def test_agents_are_told_they_run_unattended_with_a_bounded_answer(mode):
    script = "await agent({stepId:'a', agentRef:'lead_agent', task:'scan'}); return 1;"
    launched = await mode.service.launch({"request_id": "note", "script": script}, tool_context(mode.runs, ULTRACODE))
    await finish(mode, launched["run_id"])
    task = json.loads(mode.runs.starts[0][1]["messages"][0]["content"])
    assert task["task"] == "scan"
    assert "never ask for clarification" in task["run_note"] and "8,000 characters" in task["run_note"]
    # Plain workflows keep their task exactly as the script wrote it.
    plain = await mode.service.launch({"request_id": "plain-note", "script": script.replace("'a'", "'b'")}, tool_context(mode.runs))
    await finish(mode, plain["run_id"])
    assert mode.runs.starts[1][1]["messages"][0]["content"] == json.dumps("scan")


@pytest.mark.asyncio
async def test_double_ultracode_children_carry_the_unlimited_mode(mode):
    """The host lifts automatic limits only when a run's context says so: each
    agent and the result follow-up carry the mode, and the workflow has no wall
    clock. Plus Ultracode keeps every limit (FORK.md §44)."""
    from deerflow_extension_workflows.ultracode import NO_WALL_CLOCK_SECONDS

    script = "await agent({stepId:'a', agentRef:'lead_agent', task:'scan'}); return 1;"
    options = {"mode": "double_ultracode", "max_agents": 3, "max_parallel": 1, "max_minutes": 1}
    launched = await mode.service.launch({"request_id": "double", "script": script}, tool_context(mode.runs, options))
    record = await finish(mode, launched["run_id"])
    assert record["mode"] == "double_ultracode"
    assert record["limits"]["max_calls"] == 3
    assert record["limits"]["timeout_seconds"] == NO_WALL_CLOCK_SECONDS
    assert mode.runs.contexts == [{"mode": "double_ultracode"}]
    assert (await delivered(mode, launched["run_id"]))["status"] == "delivered"
    # The result turn also gets the run options back, so a workflow it launches is the same mode.
    assert mode.runs.delivery_contexts == [{"mode": "double_ultracode", "plugin_options": {NAMESPACE: {"mode": "double_ultracode", "max_agents": 3, "max_parallel": 1}}}]
    # Plus Ultracode does not stamp the mode, so its agents and its result turn stay limited.
    plus = await mode.service.launch({"request_id": "plus", "script": script.replace("'a'", "'b'")}, tool_context(mode.runs, {**ULTRACODE, "max_minutes": 1}))
    plus_record = await finish(mode, plus["run_id"])
    assert plus_record["limits"]["timeout_seconds"] == 10  # the operator's wall time
    assert mode.runs.contexts[1] is None
    assert (await delivered(mode, plus["run_id"]))["status"] == "delivered"
    assert mode.runs.delivery_contexts[1] == {"plugin_options": {NAMESPACE: {"mode": "ultracode", "max_agents": 3, "max_parallel": 1, "max_minutes": 1}}}


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode_id", "wall_seconds"), [("double_ultracode", 2**31 - 1), ("ultracode", 120)])
async def test_a_follow_up_workflow_from_the_result_turn_keeps_the_mode_and_the_users_limits(tmp_path, monkeypatch, mode_id, wall_seconds):
    """The result note invites a smaller follow-up workflow. It is launched from
    the result turn, whose only run options are the ones delivery sends."""
    import deerflow_extension_workflows.delivery as delivery
    from deerflow_extension_api import plugin_run_options

    monkeypatch.setattr(delivery, "RETRY_DELAYS", (0.01,))
    _, actions, service = await load(tmp_path, monkeypatch, timeout_seconds=600)
    env = SimpleNamespace(service=service, actions=actions, runs=ModeRuns())
    try:
        options = {"mode": mode_id, "max_agents": 3, "max_parallel": 1, "max_minutes": 2}
        first = await service.launch({"request_id": "first", "script": "return 1;"}, tool_context(env.runs, options))
        await finish(env, first["run_id"])
        assert (await delivered(env, first["run_id"]))["status"] == "delivered"
        result_turn = plugin_run_options(env.runs.delivery_contexts[0], NAMESPACE)

        script = "await agent({stepId:'a', agentRef:'lead_agent', task:'rest'}); return 1;"
        follow_up = await service.launch({"request_id": "follow-up", "script": script}, tool_context(env.runs, result_turn))
        record = await finish(env, follow_up["run_id"])
        assert record["mode"] == mode_id
        assert record["limits"]["max_calls"] == 3 and record["limits"]["concurrency"] == 1
        assert record["limits"]["timeout_seconds"] == wall_seconds
        assert env.runs.contexts == [{"mode": "double_ultracode"} if mode_id == "double_ultracode" else None]
        # Its own result turn is started exactly like the first one.
        assert (await delivered(env, follow_up["run_id"]))["status"] == "delivered"
        assert env.runs.delivery_contexts[1] == env.runs.delivery_contexts[0]
    finally:
        await service.stop()
        await env.runs.close()


@pytest.mark.asyncio
async def test_agents_and_the_result_turn_inherit_the_conversations_model_and_internet_switch(mode):
    """A workflow's agents and its result turn are separate runs: without the
    conversation's choices they fall back to the server's default model and
    get web tools in a conversation the user switched offline."""
    script = "await agent({stepId:'own', agentRef:'lead_agent', task:'x', model:'local-small'}); await agent({stepId:'inherits', agentRef:'lead_agent', task:'y'}); return 1;"
    options = {**ULTRACODE, "model": "provider/chosen:1", "internet_enabled": False}
    launched = await mode.service.launch({"request_id": "inherit", "script": script}, tool_context(mode.runs, options))
    assert (await finish(mode, launched["run_id"]))["status"] == "completed"
    # The script's per-step model still wins.
    assert mode.runs.contexts == [{"model_name": "local-small", "internet_enabled": False}, {"model_name": "provider/chosen:1", "internet_enabled": False}]
    assert (await delivered(mode, launched["run_id"]))["status"] == "delivered"
    (result_turn,) = mode.runs.delivery_contexts
    assert result_turn["model_name"] == "provider/chosen:1" and result_turn["internet_enabled"] is False
    # ... and a follow-up workflow launched from the result turn inherits both again.
    assert result_turn["plugin_options"][NAMESPACE] == {"mode": "ultracode", "max_agents": 3, "max_parallel": 1, "max_minutes": 1, "model": "provider/chosen:1", "internet_enabled": False}

    # Anything else is ignored, never an error: the options are browser input.
    for index, ignored in enumerate(({"model": "not a model name"}, {"model": 7}, {"model": "x" * 201}, {"internet_enabled": "false"}, {"internet_enabled": 0}, {"internet_enabled": True})):
        mode.runs.contexts.clear()
        plain = await mode.service.launch({"request_id": f"ignored-{index}", "script": f"await agent({{stepId:'s{index}', agentRef:'lead_agent', task:'z'}}); return 1;"}, tool_context(mode.runs, {**ULTRACODE, **ignored}))
        assert (await finish(mode, plain["run_id"]))["status"] == "completed"
        assert mode.runs.contexts == [None], ignored
        assert (await delivered(mode, plain["run_id"]))["status"] == "delivered"
        assert mode.runs.delivery_contexts[-1] == {"plugin_options": {NAMESPACE: {"mode": "ultracode", "max_agents": 3, "max_parallel": 1, "max_minutes": 1}}}, ignored


@pytest.mark.asyncio
async def test_a_caught_agent_failure_does_not_end_the_workflow(mode):
    """The brief's settle pattern works: an over-long answer fails one step only."""
    original_create = mode.runs.create_thread
    created = []

    async def scripted_create(*, assistant_id, thread_id, metadata, parent_thread_id=None):
        created.append(thread_id)
        mode.runs.answers[thread_id] = ["x" * 13_000] if len(created) == 1 else ["fine"]
        return await original_create(assistant_id=assistant_id, thread_id=thread_id, metadata=metadata, parent_thread_id=parent_thread_id)

    mode.runs.create_thread = scripted_create
    script = """
const settle = (p) => p.then((r) => ({ok: true, output: r.output}), (e) => ({ok: false, error: String(e)}));
const big = await settle(agent({stepId:'big', agentRef:'lead_agent', task:'report everything'}));
const small = await settle(agent({stepId:'small', agentRef:'lead_agent', task:'summarize'}));
return {big, small};
"""
    launched = await mode.service.launch({"request_id": "settled", "script": script}, tool_context(mode.runs, ULTRACODE))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed", record["error"]
    assert record["result"]["big"]["ok"] is False and "12,000-byte limit" in record["result"]["big"]["error"]
    assert record["result"]["small"] == {"ok": True, "output": "fine"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode_id", ["ultracode", "double_ultracode"])
async def test_a_child_question_fails_only_its_step_in_ultracode_runs(mode, mode_id):
    """Nobody can answer a child: its step fails, the others and their outputs are kept."""
    answer = mode.runs.answer

    async def unwrapped(run, input):
        # The engine's fake asks a question for the bare task 'clarification'.
        task = json.loads(input["messages"][0]["content"])["task"]
        return await answer(run, {"messages": [{**input["messages"][0], "content": json.dumps(task)}]})

    mode.runs.answer = unwrapped
    script = """
const settle = (p) => p.then((r) => ({ok: true, output: r.output}), (e) => ({ok: false, error: String(e)}));
const asked = await settle(agent({stepId:'asks', agentRef:'lead_agent', task:'clarification'}));
const worked = await settle(agent({stepId:'works', agentRef:'lead_agent', task:'work'}));
return {asked, worked};
"""
    launched = await mode.service.launch({"request_id": "question", "script": script}, tool_context(mode.runs, {**ULTRACODE, "mode": mode_id}))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed", record["error"]
    assert record["result"]["asked"]["ok"] is False and "Child requires input" in record["result"]["asked"]["error"]
    assert record["result"]["worked"] == {"ok": True, "output": {"echo": "work"}}
    assert {step["step_id"]: step["status"] for step in record["steps"]} == {"asks": "waiting_input", "works": "completed"}


@pytest.mark.asyncio
async def test_an_uncaught_agent_failure_is_reported_as_itself(mode):
    """The script's own error wins over 'returned before awaiting', and carries the child's stop reason."""
    answer = mode.runs.answer

    async def scripted(run, input):
        if json.loads(input["messages"][0]["content"]) != "fail":
            return await answer(run, input)
        await asyncio.sleep(0.01)
        mode.runs.runs[run.run_id] = AgentRun(run.thread_id, run.run_id, "error", stop_reason="token_budget_exceeded")

    mode.runs.answer = scripted
    script = "await parallel([() => agent({stepId:'bad', agentRef:'lead_agent', task:'fail'}), () => agent({stepId:'slow', agentRef:'lead_agent', task:'blocked'})]); return 1;"
    launched = await mode.service.launch({"request_id": "masked", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "failed"
    assert "Agent run did not succeed: token_budget_exceeded" in record["error"], record["error"]
    assert {step["step_id"]: step["status"] for step in record["steps"]} == {"bad": "failed", "slow": "cancelled"}
    posted = (await delivered(mode, launched["run_id"])) and mode.runs.deliveries[0][0]["messages"][0]["content"]
    assert "bad (failed): Agent run did not succeed: token_budget_exceeded" in posted


@pytest.mark.asyncio
@pytest.mark.parametrize(("script", "problem"), [("const x = ;", "SyntaxError"), ("const loop = {}; loop.self = loop; return loop;", "circular")])
async def test_a_script_that_cannot_run_or_return_names_the_problem(mode, script, problem):
    launched = await mode.service.launch({"request_id": "broken", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "failed" and problem in record["error"], record["error"]


@pytest.mark.asyncio
async def test_an_oversized_final_result_fails_with_an_error_that_names_the_limit(mode):
    launched = await mode.service.launch({"request_id": "big-result", "script": "return 'x'.repeat(13000);"}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "failed" and "12,000-byte limit" in record["error"], record["error"]
    # The lead reads the limit before it writes the script, and where the finished steps stay readable.
    ((_, declaration),) = mode.loaded.plugins
    description = next(tool.description for tool in declaration.tools if tool.name == "launch_workflow")
    assert "12,000 bytes" in description and "1,500 if mostly non-Latin" in description and "inspect_workflow_step" in description
    # ... and, on any launch, which agent references the operator admits.
    assert "100 log() lines" in description and "(lead_agent)" in description


@pytest.mark.asyncio
async def test_settings_agent_limit_stops_the_fourth_agent(mode):
    script = "for (let i = 0; i < 4; i++) await agent({stepId:'s'+i, agentRef:'lead_agent', task:'t'+i}); return 'never';"
    launched = await mode.service.launch({"request_id": "capped", "script": script}, tool_context(mode.runs, ULTRACODE))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "failed" and "Total Agent call limit" in record["error"]
    assert len(record["steps"]) == 3


@pytest.mark.asyncio
async def test_phase_and_pipeline_group_steps_and_bound_parallelism(mode):
    script = """
phase('understand');
const first = await agent({stepId:'scan', agentRef:'lead_agent', task:'scan'});
phase('change');
const results = await pipeline(['a','b','c','d','e','f'], (item, index) => agent({stepId:'item'+index, agentRef:'lead_agent', task:item}), {concurrency: 2});
return {count: results.length, first: first.output};
"""
    launched = await mode.service.launch({"request_id": "phased", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed" and record["result"]["count"] == 6
    assert [phase["title"] for phase in record["phases"]] == ["understand", "change"]
    assert record["phases"][1]["first_step"] == 1
    assert {step["step_id"]: step.get("phase") for step in record["steps"]}["item5"] == 1
    assert mode.runs.peak <= 2


@pytest.mark.asyncio
async def test_a_long_agent_is_polled_with_backoff(mode):
    """Every status poll is an authorized host call: a long agent must not cost 50 a second."""
    polls = []
    get = mode.runs.get

    async def counted(*, thread_id, run_id):
        polls.append(run_id)
        return await get(thread_id=thread_id, run_id=run_id)

    async def slow(run, input):
        await asyncio.sleep(0.6)
        mode.runs.threads[run.thread_id]["values"]["messages"].append({"type": "ai", "content": '"done"'})
        mode.runs.runs[run.run_id] = AgentRun(run.thread_id, run.run_id, "success")

    mode.runs.get, mode.runs.answer = counted, slow
    launched = await mode.service.launch({"request_id": "slow", "script": "return (await agent({stepId:'a', agentRef:'lead_agent', task:'x'})).output;"}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed" and record["result"] == "done"
    assert len(polls) < 15, len(polls)


@pytest.mark.asyncio
async def test_pipeline_runs_each_item_through_every_stage(mode):
    """A second stage function is a stage, not an ignored options object."""
    script = """
const out = await pipeline(['a','b','c'],
  (item, index) => agent({stepId:'one'+index, agentRef:'lead_agent', task:item}),
  (previous, item, index) => agent({stepId:'two'+index, agentRef:'lead_agent', task:previous.output.echo + item + index}),
  {concurrency: 2});
return out.map((r) => r.output.echo);
"""
    launched = await mode.service.launch({"request_id": "stages", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed", record["error"]
    assert record["result"] == ["aa0", "bb1", "cc2"] and len(record["steps"]) == 6
    assert mode.runs.peak <= 2


@pytest.mark.asyncio
async def test_progress_messages_never_end_the_workflow(mode):
    """A long or empty log() line or phase() title is cut or skipped, after and before agents ran."""
    script = """
phase('p'.repeat(100)); phase('');
const a = await agent({stepId:'a', agentRef:'lead_agent', task:'x'});
log('x'.repeat(300)); log(''); log('\u4e2d'.repeat(28)); log('y'.repeat(3000000));
return a.output;
"""
    launched = await mode.service.launch({"request_id": "progress", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed", record["error"]
    logs = record["logs"]
    assert len(logs) == 3 and all(log.endswith("...") and len(json.dumps(log)) <= 160 for log in logs)
    assert logs[0].startswith("x" * 150) and logs[1].startswith("\u4e2d" * 20)
    (title,) = [phase["title"] for phase in record["phases"]]
    assert title == "p" * 77 + "..." and record["steps"][0]["phase"] == 0


@pytest.mark.asyncio
async def test_a_wide_fanout_with_large_tasks_fits_the_bridge(mode):
    """Every call issued in one JS turn crosses the bridge in one frame."""
    script = "const r = await parallel(Array.from({length: 30}, (_, i) => () => agent({stepId:'w'+i, agentRef:'lead_agent', task:'x'.repeat(5000)}))); return r.length;"
    launched = await mode.service.launch({"request_id": "wide", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed", record["error"]
    assert record["result"] == 30 and len(record["steps"]) == 30


@pytest.mark.asyncio
async def test_a_fanout_wider_than_the_pending_window_queues_in_order(tmp_path, monkeypatch):
    """More than 64 unresolved agent() calls wait their turn instead of failing the run."""
    _, _, service = await load(tmp_path, monkeypatch, max_calls=256, concurrency=16, global_concurrency=16, timeout_seconds=120)
    runs = ModeRuns()
    script = "const r = await parallel(Array.from({length: 70}, (_, i) => () => agent({stepId:'p'+i, agentRef:'lead_agent', task:'p'+i}))); return r.map((x) => x.output.echo);"
    try:
        launched = await service.launch({"request_id": "queued", "script": script}, tool_context(runs))
        await asyncio.wait_for(service.wait_idle(launched["run_id"]), 60)
        record = await asyncio.to_thread(service.store.get, "alice", launched["run_id"])
        assert record["status"] == "completed", record["error"]
        assert record["result"] == [f"p{i}" for i in range(70)]
    finally:
        await service.stop()
        await runs.close()


@pytest.mark.asyncio
async def test_a_record_over_the_store_limit_still_ends_and_reports(mode):
    from deerflow_extension_workflows.store import RecordLimit

    put = mode.service.store.put

    def limited(owner, record):
        # Stands in for 8 MiB of tasks and answers: the record fits only without its journal.
        if len(record["steps"]) >= 2 and record.get("journal"):
            raise RecordLimit("Workflow record limit (8 MiB)")
        return put(owner, record)

    mode.monkeypatch.setattr(mode.service.store, "put", limited)
    script = "for (let i = 0; i < 3; i++) await agent({stepId:'s'+i, agentRef:'lead_agent', task:'t'+i}); return 'never';"
    launched = await mode.service.launch({"request_id": "too-big", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "failed" and "8 MiB" in record["error"]
    assert launched["run_id"] not in mode.service.entries
    assert (await delivered(mode, launched["run_id"]))["status"] == "delivered"
    assert "8 MiB" in mode.runs.deliveries[0][0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_result_is_posted_once_into_the_launching_conversation(mode):
    launched = await mode.service.launch({"request_id": "deliver", "script": "const a = await agent({stepId:'a', agentRef:'lead_agent', task:'x'}); return {answer: a.output};"}, tool_context(mode.runs))
    await finish(mode, launched["run_id"])
    outcome = await delivered(mode, launched["run_id"])
    assert outcome["status"] == "delivered"
    ((posted, key),) = mode.runs.deliveries
    assert key == f"workflow-result:{launched['run_id']}"
    message = posted["messages"][0]
    assert message["role"] == "user" and message["id"] == f"workflow-result-{launched['run_id'][:32]}"
    assert message["content"].startswith("[Workflow result]") and "untrusted" in message["content"] and '"answer"' in message["content"]
    # Any later session action re-arms pending deliveries only: nothing is posted twice.
    await mode.actions["list"]({}, session(mode.runs))
    await asyncio.sleep(0.05)
    assert len(mode.runs.deliveries) == 1


@pytest.mark.asyncio
async def test_a_busy_conversation_is_waited_for_not_interrupted(mode):
    mode.runs.threads[CONVERSATION]["interrupts"] = [{"value": "Approve?"}]
    launched = await mode.service.launch({"request_id": "busy", "script": "return 1;"}, tool_context(mode.runs))
    await finish(mode, launched["run_id"])
    await asyncio.sleep(0.1)
    pending = await asyncio.to_thread(mode.service.store.delivery, "alice", launched["run_id"])
    assert pending["status"] == "pending" and "current turn" in pending["error"]
    assert mode.runs.deliveries == []
    mode.runs.threads[CONVERSATION]["interrupts"] = []
    assert (await delivered(mode, launched["run_id"]))["status"] == "delivered"
    assert len(mode.runs.deliveries) == 1


@pytest.mark.asyncio
async def test_a_long_busy_conversation_does_not_use_up_delivery_attempts(mode):
    """A long task in the launching chat must not make the result give up."""
    import deerflow_extension_workflows.delivery as delivery

    mode.monkeypatch.setattr(delivery, "MAX_ATTEMPTS", 2)
    mode.runs.threads[CONVERSATION]["next"] = ["agent"]
    launched = await mode.service.launch({"request_id": "long-busy", "script": "return 1;"}, tool_context(mode.runs))
    await finish(mode, launched["run_id"])
    await asyncio.sleep(0.2)  # many more busy polls than MAX_ATTEMPTS
    assert mode.runs.deliveries == []
    mode.runs.threads[CONVERSATION]["next"] = []
    assert (await delivered(mode, launched["run_id"]))["status"] == "delivered"


@pytest.mark.asyncio
async def test_a_spend_capped_delivery_is_posted_once_a_run_is_allowed(mode):
    """The usual end of a run that used up the cap: the result run is refused
    too. It must arrive when the cap's window reopens, with no owner action."""
    mode.runs.delivery_error = AgentRunError(402, "Spend budget exhausted")
    launched = await mode.service.launch({"request_id": "capped-result", "script": "return 1;"}, tool_context(mode.runs))
    await asyncio.wait_for(mode.service.wait_idle(launched["run_id"]), 10)
    for _ in range(500):
        pending = await asyncio.to_thread(mode.service.store.delivery, "alice", launched["run_id"])
        if pending["error"]:
            break
        await asyncio.sleep(0.01)
    assert pending["status"] == "pending" and "Spend cap reached" in pending["error"]
    assert mode.runs.deliveries == []
    mode.runs.delivery_error = None
    assert (await delivered(mode, launched["run_id"]))["status"] == "delivered"
    assert len(mode.runs.deliveries) == 1


@pytest.mark.asyncio
async def test_pending_delivery_resumes_after_restart_with_a_fresh_session(tmp_path, monkeypatch):
    import deerflow_extension_workflows.delivery as delivery

    monkeypatch.setattr(delivery, "RETRY_DELAYS", (0.01,))
    _, actions, service = await load(tmp_path, monkeypatch)
    revoked = ModeRuns()
    revoked.delivery_error = AgentRunError(403, "revoked")
    launched = await service.launch({"request_id": "restart", "script": "return 'done';"}, tool_context(revoked))
    await asyncio.wait_for(service.wait_idle(launched["run_id"]), 10)
    for _ in range(100):
        if (await asyncio.to_thread(service.store.delivery, "alice", launched["run_id"]))["error"]:
            break
        await asyncio.sleep(0.01)
    await service.stop()
    await revoked.close()
    assert (await asyncio.to_thread(service.store.delivery, "alice", launched["run_id"]))["status"] == "pending"

    _, actions, service = await load(tmp_path, monkeypatch)
    fresh = ModeRuns()
    try:
        await actions["list"]({}, session(fresh))
        for _ in range(500):
            if fresh.deliveries:
                break
            await asyncio.sleep(0.01)
        assert len(fresh.deliveries) == 1 and fresh.deliveries[0][1] == f"workflow-result:{launched['run_id']}"
    finally:
        await service.stop()
        await fresh.close()


@pytest.mark.asyncio
async def test_cancelled_workflows_post_nothing(mode):
    mode.runs.release.clear()
    launched = await mode.service.launch({"request_id": "cancel", "script": "await agent({stepId:'a', agentRef:'lead_agent', task:'blocked'}); return 1;"}, tool_context(mode.runs))
    await asyncio.wait_for(mode.runs.entered.wait(), 5)
    await mode.actions["cancel"]({"run_id": launched["run_id"]}, session(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "cancelled"
    assert (await delivered(mode, launched["run_id"]))["status"] == "skipped"
    assert mode.runs.deliveries == []


@pytest.mark.asyncio
async def test_browser_launches_have_no_return_path(mode):
    launched = await mode.actions["launch"]({"request_id": "browser", "script": "return 1;"}, session(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["launched_from_conversation"] is False and record["delivery"] is None


@pytest.mark.asyncio
async def test_schema_mismatch_is_reasked_under_a_new_attempt_identity(mode):
    schema = {"type": "object", "required": ["score"], "properties": {"score": {"type": "integer"}}}
    script = f"const r = await agent({{stepId:'grade', agentRef:'lead_agent', task:'grade it', schema:{json.dumps(schema)}}}); return r;"
    launched = await mode.service.launch({"request_id": "schema", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    # The fake echoes {"echo": task}, which fails the schema three times.
    assert record["status"] == "failed" and "did not match the schema after 3 attempts" in record["error"]
    keys = [key for _, _, key in mode.runs.starts]
    assert len(keys) == 3 and len(set(keys)) == 3 and [key.rsplit(":", 1)[1] for key in keys] == ["1", "2", "3"]
    first_task = json.loads(mode.runs.starts[0][1]["messages"][0]["content"])
    assert first_task["output_schema"] == schema
    reask = json.loads(mode.runs.starts[1][1]["messages"][0]["content"])
    assert reask["output_schema"] == schema and "problem" in reask


@pytest.mark.asyncio
async def test_a_reask_that_matches_completes_the_step(mode):
    schema = {"type": "object", "required": ["score"]}
    original_create = mode.runs.create_thread

    async def scripted_create(*, assistant_id, thread_id, metadata, parent_thread_id=None):
        mode.runs.answers[thread_id] = [{"wrong": True}, {"score": 4}]
        return await original_create(assistant_id=assistant_id, thread_id=thread_id, metadata=metadata, parent_thread_id=parent_thread_id)

    mode.runs.create_thread = scripted_create
    script = f"const r = await agent({{stepId:'grade', agentRef:'lead_agent', task:'grade', schema:{json.dumps(schema)}}}); return r;"
    launched = await mode.service.launch({"request_id": "reask-ok", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed", record["error"]
    assert record["result"]["output"] == {"score": 4} and record["result"]["attempts"] == 2
    # Every attempt runs on the one child thread, so the child keeps its context.
    assert len({thread for thread, _, _ in mode.runs.starts}) == 1


@pytest.mark.asyncio
async def test_schema_accepts_an_answer_delivered_as_content_blocks(mode):
    """A thinking model answers in blocks: only the text is parsed, sized and checked."""

    async def blocks(run, input):
        await asyncio.sleep(0.01)
        content = [{"type": "thinking", "thinking": "t" * 13_000, "signature": "s"}, {"type": "text", "text": '{"score": 4}'}]
        mode.runs.threads[run.thread_id]["values"]["messages"].append({"type": "ai", "content": content})
        mode.runs.runs[run.run_id] = AgentRun(run.thread_id, run.run_id, "success")

    mode.runs.answer = blocks
    schema = {"type": "object", "required": ["score"]}
    script = f"const r = await agent({{stepId:'grade', agentRef:'lead_agent', task:'grade', schema:{json.dumps(schema)}}}); return r;"
    launched = await mode.service.launch({"request_id": "blocks", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed", record["error"]
    assert record["result"]["output"] == {"score": 4} and record["result"]["attempts"] == 1


@pytest.mark.asyncio
async def test_per_step_model_reaches_the_child_run_context(mode):
    script = "const a = await agent({stepId:'cheap', agentRef:'lead_agent', task:'x', model:'local-small'}); const b = await agent({stepId:'default', agentRef:'lead_agent', task:'y'}); return 1;"
    launched = await mode.service.launch({"request_id": "models", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "completed"
    assert mode.runs.contexts == [{"model_name": "local-small"}, None]
    assert {step["step_id"]: step.get("model") for step in record["steps"]} == {"cheap": "local-small", "default": None}


@pytest.mark.asyncio
async def test_child_threads_link_to_the_launching_conversation(mode):
    launched = await mode.service.launch({"request_id": "linked", "script": "await agent({stepId:'a', agentRef:'lead_agent', task:'x'}); return 1;"}, tool_context(mode.runs))
    await finish(mode, launched["run_id"])
    assert [parent for _, parent in mode.runs.created] == [CONVERSATION]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "requested", "allowed"),
    [("off", "snapshot", False), ("read", "snapshot", True), ("read", "merge", False), ("write", "merge", True)],
)
async def test_shared_workspace_follows_the_operator_policy(tmp_path, monkeypatch, policy, requested, allowed):
    _, actions, service = await load(tmp_path, monkeypatch, shared_workspace=policy)
    runs = ModeRuns()
    try:
        script = f"const r = await agent({{stepId:'edit', agentRef:'lead_agent', task:'edit', workspace:'{requested}'}}); return r;"
        launched = await service.launch({"request_id": f"ws-{policy}-{requested}", "script": script}, tool_context(runs))
        await asyncio.wait_for(service.wait_idle(launched["run_id"]), 10)
        record = await actions["get"]({"run_id": launched["run_id"]}, session(runs))
        if not allowed:
            assert record["status"] == "failed" and "does not allow workspace" in record["error"]
            assert runs.copies == [] and runs.merges == []
            return
        assert record["status"] == "completed", record["error"]
        ((source, child),) = runs.copies
        assert source == CONVERSATION and child.startswith("workflow-")
        task = json.loads(runs.starts[0][1]["messages"][0]["content"])
        assert "workspace_note" in task
        if requested == "merge":
            ((merged_child, into, base),) = runs.merges
            assert (merged_child, into) == (child, CONVERSATION) and set(base) == {"workspace/a.py", "workspace/b.py"}
            assert record["result"]["workspace"] == {"applied": 1, "conflicts": ["workspace/b.py"], "skipped": 0}
        else:
            assert runs.merges == [] and "workspace" not in record["result"]
    finally:
        await service.stop()
        await runs.close()


@pytest.mark.asyncio
async def test_shared_workspace_needs_a_conversation(tmp_path, monkeypatch):
    _, actions, service = await load(tmp_path, monkeypatch, shared_workspace="write")
    runs = ModeRuns()
    try:
        launched = await actions["launch"]({"request_id": "no-origin", "script": "return await agent({stepId:'e', agentRef:'lead_agent', task:'x', workspace:'snapshot'});"}, session(runs))
        await asyncio.wait_for(service.wait_idle(launched["run_id"]), 10)
        record = await actions["get"]({"run_id": launched["run_id"]}, session(runs))
        assert record["status"] == "failed" and "launched from a conversation" in record["error"]
    finally:
        await service.stop()
        await runs.close()


@pytest.mark.asyncio
async def test_spend_cap_refusal_is_a_clean_failure_not_a_reconciliation(mode):
    mode.runs.start_error = AgentRunError(402, "Spend budget exhausted")
    launched = await mode.service.launch({"request_id": "capped-spend", "script": "await agent({stepId:'a', agentRef:'lead_agent', task:'x'}); return 1;"}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "failed"
    assert record["steps"][0]["status"] == "failed" and record["steps"][0]["admission_rejected"] is True
    assert "Spend cap reached" in record["error"]


@pytest.mark.asyncio
async def test_large_limits_come_back_with_a_size_advisory(mode):
    reply = await mode.service.launch({"request_id": "advisory", "script": "return 1;"}, tool_context(mode.runs))
    assert "up to 40 agents" in reply["advisory"]
    small = await mode.service.launch({"request_id": "no-advisory", "script": "return 1;"}, tool_context(mode.runs, ULTRACODE))
    assert "advisory" not in small


@pytest.mark.asyncio
async def test_a_refused_launch_tells_the_lead_why(mode):
    """The host replaces any error a tool raises with one fixed sentence, so a
    refusal has to come back as an ordinary result for the lead to act on it."""
    launch = lead_tool(mode, "launch_workflow")
    mode.runs.release.clear()
    blocked = "await agent({stepId:'a', agentRef:'lead_agent', task:'blocked'}); return 1;"
    running = [await launch(request_id=f"running-{index}", script=blocked) for index in range(2)]
    assert all(reply["run_id"] and "launched" not in reply for reply in running)

    full = await launch(request_id="third", script="return 1;")  # two active workflows per owner by default
    assert full["launched"] is False and "Active workflow limit" in full["error"]
    reused = await launch(request_id="running-0", script="return 2;")
    assert reused["launched"] is False and "request_id already used" in reused["error"]
    # 9,000 newlines pass the tool schema's 16,000 characters and double once JSON-encoded.
    long_script = await launch(request_id="long-script", script="return 1;" + "\n" * 9000)
    assert long_script["launched"] is False and "script" in long_script["error"] and "16,000" in long_script["error"]
    long_args = await launch(request_id="long-args", script="return 1;", args={"blob": "x" * 5000})
    assert long_args["launched"] is False and "args" in long_args["error"] and "4,000" in long_args["error"]
    for reply in (full, reused, long_script, long_args):
        assert set(reply) == {"launched", "error"} and len(reply["error"]) <= 240

    mode.runs.release.set()
    for reply in running:
        assert (await finish(mode, reply["run_id"]))["status"] == "completed"
    # Nothing was stored for a refusal: the same request can be sent again.
    retried = await launch(request_id="third", script="return 1;")
    assert (await finish(mode, retried["run_id"]))["status"] == "completed"


def retained(index, status):
    return {"id": f"old-{index:03d}", "request_id": f"old-{index}", "fingerprint": "seeded", "status": status, "steps": [], "definition": None, "result": None, "error": None}


@pytest.mark.asyncio
async def test_the_oldest_finished_workflow_makes_room_for_a_new_launch(mode):
    """Every Plus or Double Plus message stores a record. At the retained limit
    the oldest one that is finished for good goes; records kept for recovery,
    reconciliation or an unposted result stay."""
    store = mode.service.store
    kept = {0: "recoverable", 1: "needs_reconciliation", 2: "waiting_input", 3: "interrupted", 4: "completed"}

    def seed():
        for index in range(100):
            store.create("alice", retained(index, kept.get(index, "failed" if index % 2 else "completed")))
        store.delivery_create("alice", "old-004", CONVERSATION)  # its result is not posted yet
        store.delivery_create("alice", "old-005", CONVERSATION)
        store.delivery_finish("alice", "old-005", "delivered", run_id="r")
        store.capture_artifact("alice", "old-005", "file", "a.txt", b"bytes")
        for index in range(100):
            store.create("bob", {**retained(index, "recoverable"), "id": f"bob-{index:03d}"})

    def present(owner="alice"):
        with closing(store.connect()) as db:
            return {row[0] for row in db.execute("SELECT id FROM workflows WHERE owner=?", (owner,))}

    await asyncio.to_thread(seed)
    before = await asyncio.to_thread(present)
    # A refused result run leaves old-004's delivery pending whatever the timing.
    mode.runs.delivery_error = AgentRunError(403, "revoked")
    first = await mode.service.launch({"request_id": "new-1", "script": "return 1;"}, tool_context(mode.runs))
    second = await mode.service.launch({"request_id": "new-2", "script": "return 1;"}, tool_context(mode.runs))
    for launched in (first, second):
        await asyncio.wait_for(mode.service.wait_idle(launched["run_id"]), 10)
    after = await asyncio.to_thread(present)
    assert before - after == {"old-005", "old-006"}  # the two oldest finished ones, oldest first
    assert after - before == {first["run_id"], second["run_id"]} and len(after) == 100
    # A pruned record takes its files and its delivery row with it, like an explicit delete.
    assert await asyncio.to_thread(store.artifact_by_step, "alice", "old-005", "file") is None
    assert await asyncio.to_thread(store.delivery, "alice", "old-005") is None

    # With nothing finished to remove the launch is refused, and the lead is told why.
    refused = await lead_tool(mode, "launch_workflow", owner="bob")(request_id="new", script="return 1;")
    assert refused["launched"] is False and "Retained workflow limit (100)" in refused["error"]
    assert len(await asyncio.to_thread(present, "bob")) == 100


@pytest.mark.skipif(not os.getenv("DEERFLOW_TEST_WORKFLOW_POSTGRES"), reason="Requires dedicated PostgreSQL")
def test_postgres_pruning_skips_what_an_explicit_delete_refuses():
    """The shared store has two more reasons to keep a finished record: a live
    execution owner and retained child reservations (test_workflow_cluster.py)."""
    import psycopg
    from deerflow_extension_workflows.postgres import PostgresStore
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    dsn = os.environ["DEERFLOW_TEST_WORKFLOW_POSTGRES"]
    schema = "workflow_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped = make_conninfo(dsn, options=f"-csearch_path={schema}")
    try:
        with psycopg.connect(scoped) as db:
            db.execute(
                "CREATE TABLE extension_execution_leases(namespace varchar(96),resource_id varchar(128),user_id varchar(64) NOT NULL,holder_id varchar(128) NOT NULL,epoch bigint NOT NULL,expires_at double precision NOT NULL,"
                "PRIMARY KEY(namespace,resource_id))"
            )
        store = PostgresStore(scoped, "holder", {"global_concurrency": 4, "max_workflows": 4, "max_workflows_per_owner": 2, "lease_seconds": 60})
        kept = {1: "recoverable", 2: "needs_reconciliation"}
        for index in range(100):
            record, _ = store.create("alice", retained(index, kept.get(index, "completed")))
            if index:  # old-000 keeps the live lease its creation claimed
                store.put("alice", record)  # a terminal write retires the lease
        store.delivery_create("alice", "old-003", CONVERSATION)  # its result is not posted yet
        store.capture_artifact("alice", "old-005", "file", "a.txt", b"bytes")
        with psycopg.connect(scoped) as db:
            db.execute("INSERT INTO workflow_slots VALUES ('old-004','step')")  # an unreconciled child reservation
            db.execute("INSERT INTO workflow_controls VALUES ('old-005','cancel','{}')")

        store.create("alice", retained(100, "completed"))
        with psycopg.connect(scoped) as db:
            ids = {row[0] for row in db.execute("SELECT id FROM workflows WHERE owner='alice'")}
            assert ids == {f"old-{index:03d}" for index in range(101)} - {"old-005"}
            # Gone with its files and controls; the lease generation stays as a tombstone.
            assert db.execute("SELECT count(*) FROM workflow_artifacts WHERE workflow='old-005'").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM workflow_controls WHERE workflow='old-005'").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM extension_execution_leases WHERE resource_id='old-005'").fetchone()[0] == 1

        # Every one of bob's records still has an execution owner: nothing may go.
        for index in range(100):
            store.create("bob", {**retained(index, "completed"), "id": f"bob-{index:03d}"})
        with pytest.raises(ValueError, match=r"Retained workflow limit \(100\)"):
            store.create("bob", {**retained(100, "completed"), "id": "bob-100"})
    finally:
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.asyncio
async def test_the_lead_can_read_a_completed_steps_output_after_a_failure(mode):
    """inspect_workflow leaves outputs out, so without this a failed run's
    finished work could only be redone."""
    from deerflow_extension_workflows.ultracode import RESULT_NOTE

    script = "await agent({stepId:'done', agentRef:'lead_agent', task:'scan'}); await agent({stepId:'broken', agentRef:'lead_agent', task:'fail'}); return 1;"
    launched = await mode.service.launch({"request_id": "salvage", "script": script}, tool_context(mode.runs))
    record = await finish(mode, launched["run_id"])
    assert record["status"] == "failed" and [step["status"] for step in record["steps"]] == ["completed", "failed"]

    read = lead_tool(mode, "inspect_workflow_step")
    assert await read(run_id=launched["run_id"], step_id="done") == {"step_id": "done", "status": "completed", "attempt": 1, "output": {"echo": "scan"}}
    # Only finished work, and only the caller's own.
    with pytest.raises(ToolException):
        await read(run_id=launched["run_id"], step_id="broken")
    with pytest.raises(ToolException):
        await lead_tool(mode, "inspect_workflow_step", owner="bob")(run_id=launched["run_id"], step_id="done")
    assert "inspect_workflow_step" in RESULT_NOTE


@pytest.mark.asyncio
async def test_operator_configuration_validates_the_new_options(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples/deerflow-extension-workflows"))
    base = {"enabled": True, "storage_path": str(tmp_path / "runs.sqlite"), "agents": ["lead_agent"]}
    for extra, ok in (
        ({"concurrency": 16, "global_concurrency": 32, "max_calls": 256, "timeout_seconds": 14400}, True),
        ({"concurrency": 17}, False),
        ({"max_calls": 257}, False),
        ({"shared_workspace": "everything"}, False),
        ({"shared_workspace": False}, True),  # an unquoted YAML `off`
        ({"shared_workspace": True}, False),
        ({"deliver_results": "yes"}, False),
        ({"max_logs": 501}, False),
    ):
        loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_workflows:install", config={**base, **extra})])
        assert bool(loaded.plugins) is ok and bool(diagnostics) is not ok, extra


def test_a_relative_storage_path_lives_under_deer_flow_home(tmp_path, monkeypatch):
    """The bundled config ships one path for every deployment.

    A container sees the runtime home at /app/backend/.deer-flow and a local
    launch at the checkout's own, so the shipped record names a path relative
    to DEER_FLOW_HOME, which every launcher exports as an absolute path.
    """
    monkeypatch.syspath_prepend(str(ROOT / "examples/deerflow-extension-workflows"))
    config = {"enabled": True, "storage_path": "workflows/workflows.sqlite", "agents": ["lead_agent"]}

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_workflows:install", config=config)])
    assert not diagnostics, diagnostics
    ((_, declaration),) = loaded.plugins
    service = next(a.handler for a in declaration.backend if a.name == "launch").__self__
    assert service.config["storage_path"] == str(tmp_path / "workflows" / "workflows.sqlite")

    # Without an absolute home to anchor it, the plugin fails to load (with a
    # diagnostic) rather than writing next to whatever the working directory is.
    monkeypatch.delenv("DEER_FLOW_HOME")
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_workflows:install", config=config)])
    assert not loaded.plugins and diagnostics


def test_brief_appears_only_on_ultracode_runs_and_clamps_its_limits():
    from deerflow_extension_workflows.ultracode import DOUBLE_LIMITS, RESULT_NOTE, UltracodeMode

    middleware = UltracodeMode({"max_calls": 40, "concurrency": 4, "timeout_seconds": 600})

    def request(context, messages=()):
        return SimpleNamespace(
            runtime=SimpleNamespace(context=context),
            messages=list(messages),
            system_message=SystemMessage(content="base prompt", id="system"),
            override=lambda **changes: SimpleNamespace(**{"system_message": None, **changes}),
        )

    handle = object()
    plain = request({AGENT_RUNS_CONTEXT_KEY: handle})
    assert middleware.apply(plain) is plain

    briefed = middleware.apply(request({AGENT_RUNS_CONTEXT_KEY: handle, "plugin_options": {"community.workflows": {"mode": "ultracode", "max_agents": 12, "max_parallel": 99}}}))
    text = briefed.system_message.content
    assert text.startswith("base prompt") and "## Plus Ultracode mode" in text
    flat = " ".join(text.split())
    assert "up to 12 agents, at most 4 at once, 10 minutes in total" in flat
    # The lead is told how to keep one failed agent from ending the workflow.
    assert "Keep going when one agent fails" in flat and "parallel()` rejects on the first rejection" in flat
    # The limits the lead must plan for: the result's size, and where the steps of a failed or over-size run stay readable.
    from deerflow_extension_workflows.service import RESULT_BYTES

    assert f"{RESULT_BYTES:,} bytes" in flat and "1,500 if mostly non-Latin" in flat and "inspect_workflow_step" in flat

    # Where the user follows, cancels or recovers the run; that a later phase may be its own workflow; several
    # verifiers and a completeness check; and that a trivial edit needs no workflow.
    assert "progress, cancel and recovery after a restart are on the Script workflows page" in flat
    assert "launch it as a new workflow" in flat and "several independent ones" in flat and "nothing asked for was missed" in flat
    assert "a trivial edit you can make yourself" in flat
    # Without the operator's allowlist or workspace policy in the config (as here) the brief still renders, with the shipped policy.
    assert "agentRef` must be" not in flat and "own empty workspace" in flat and "apply file changes here yourself" in flat
    # With them, the lead is told which agent references are admitted and what an agent can see of this conversation's files.
    for policy, told, untold in (("off", "own empty workspace", "'snapshot'"), ("read", "'snapshot'", "'merge'"), ("write", "'merge'", "apply file changes here yourself")):
        configured = UltracodeMode({"max_calls": 40, "concurrency": 4, "timeout_seconds": 600, "agents": ["lead_agent", "reviewer"], "shared_workspace": policy})
        rendered = " ".join(configured.apply(request({AGENT_RUNS_CONTEXT_KEY: handle, "plugin_options": {"community.workflows": {"mode": "ultracode"}}})).system_message.content.split())
        assert "`agentRef` must be one of: lead_agent, reviewer." in rendered
        assert told in rendered and untold not in rendered
        # A copy over the host's cap ends the whole workflow, caught or not.
        assert ("1,000 files" in rendered) is (policy != "off")

    unavailable = middleware.apply(request({"plugin_options": {"community.workflows": {"mode": "ultracode"}}}))
    assert "cannot start workflows" in unavailable.system_message.content and "Plus Ultracode" in unavailable.system_message.content

    doubled = middleware.apply(request({AGENT_RUNS_CONTEXT_KEY: handle, "plugin_options": {"community.workflows": {"mode": "double_ultracode", "max_agents": 12, "max_parallel": 2, "max_minutes": 5}}}))
    doubled_text = " ".join(doubled.system_message.content.split())
    assert "## Double Plus Ultracode mode" in doubled_text
    assert "Automatic limits are off" in doubled_text and "token-risky" in doubled_text
    # It says which limits are lifted and which still apply, and promises nothing about how the run ends.
    assert "are lifted" in DOUBLE_LIMITS and "agent count and size limits still apply" in DOUBLE_LIMITS and "spend cap" in DOUBLE_LIMITS
    assert not any(promise in DOUBLE_LIMITS for promise in ("no token budget", "The run ends when", "without interruptions"))
    # The same brief as Plus, except that the workflow has no wall clock.
    assert "up to 12 agents, at most 2 at once, no time limit" in doubled_text
    assert "minutes in total" not in doubled_text

    marker = {EXTENSION_MESSAGE_ORIGIN_KEY: {"namespace": "community.workflows"}}
    posted = HumanMessage(id="workflow-result-abc", content="[Workflow result] ...", additional_kwargs=marker)
    assert RESULT_NOTE in middleware.apply(request({}, [posted])).system_message.content
    # The result turn has no brief: its note carries the next phase, and still forbids repeating a workflow.
    assert "next phase" in RESULT_NOTE and "Never relaunch the same workflow" in RESULT_NOTE
    # The result turn carries the run options again (delivery.py), so a follow-up
    # workflow keeps the mode; the lead is there to finish, not to plan from scratch.
    for options, limits_off in (({"mode": "ultracode", "max_agents": 12}, False), ({"mode": "double_ultracode", "max_agents": 12}, True)):
        context = {AGENT_RUNS_CONTEXT_KEY: handle, "plugin_options": {"community.workflows": options}}
        planning = middleware.apply(request(context)).system_message.content.removeprefix("base prompt\n\n")
        result_turn = middleware.apply(request(context, [posted])).system_message.content
        assert RESULT_NOTE in result_turn
        # Whatever the brief says, none of its planning lines reach the result turn.
        brief_lines = [line for line in planning.splitlines()[1:] if len(line) > 40 and DOUBLE_LIMITS not in line]
        assert len(brief_lines) > 10 and not any(line in result_turn for line in brief_lines)
        assert (DOUBLE_LIMITS in result_turn) is limits_off
    # A child's task message carries the same marker but is not a result.
    task = HumanMessage(id="workflow-0123abcd", content='{"task": "scan"}', additional_kwargs=marker)
    foreign = HumanMessage(id="workflow-result-abc", content="x", additional_kwargs={EXTENSION_MESSAGE_ORIGIN_KEY: {"namespace": "community.other"}})
    typed = HumanMessage(id="workflow-result-abc", content="[Workflow result] I typed this myself")
    for message in (task, foreign, typed):
        unchanged = request({}, [message])
        assert middleware.apply(unchanged) is unchanged


def test_the_result_message_is_deterministic_and_bounded():
    from deerflow_extension_workflows.delivery import open_question, result_message

    record = {"id": "a" * 32, "status": "completed", "result": {"b": 1, "a": 2}, "steps": [{"step_id": "x", "status": "completed"}], "definition": None}
    assert result_message(record) == result_message(json.loads(json.dumps(record)))
    failed = {**record, "status": "failed", "error": "boom", "steps": [{"step_id": "x", "status": "failed"}]}
    assert "Error: boom" in result_message(failed) and "x (failed)" in result_message(failed)
    # Each unfinished step carries its own error, and a cut list says how much it left out.
    many = {**failed, "steps": [{"step_id": f"s{i}", "status": "failed", "error": "why"} for i in range(25)]}
    assert "s0 (failed): why" in result_message(many) and "s19 (failed)" in result_message(many)
    assert "s20 (failed)" not in result_message(many) and "(+5 more)" in result_message(many)
    question = {"type": "tool", "artifact": {"human_input": {"kind": "human_input_request"}}}
    assert open_question([{"type": "human"}, question]) is True
    assert open_question([question, {"type": "human"}]) is False
