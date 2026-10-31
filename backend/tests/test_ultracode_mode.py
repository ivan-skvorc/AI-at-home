"""Double Plus Ultracode on the script-workflows extension.

Covers what the mode adds on top of the workflow engine (test_workflow_plugin.py):
per-run limits from the user's settings, the lead's brief, phase()/pipeline(),
exactly-once result delivery into the launching conversation (including after
a restart), schema-checked outputs with re-asks, per-step models, shared
workspaces under the operator's policy, child-thread spend links and the spend
cap's clean refusal.
"""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from deerflow_extension_api import AGENT_RUNS_CONTEXT_KEY, EXTENSION_MESSAGE_ORIGIN_KEY, AgentRun, AgentRunError, ExtensionPrincipal, WorkspaceMerge, WorkspaceSnapshot
from deerflow_extension_api.plugins import ActionContext, ToolContext
from langchain_core.messages import HumanMessage, SystemMessage
from test_workflow_plugin import Runs

from deerflow.extensions.loader import ExtensionSpec, load_extensions

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Workflow worker execution requires POSIX")

ROOT = Path(__file__).resolve().parents[2]
CONVERSATION = "conversation-1"


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
        self.contexts = []
        self.copies = []
        self.merges = []
        self.answers = {}
        self.start_error = None
        self.delivery_error = None
        self.merge_result = WorkspaceMerge(applied=("workspace/a.py",), conflicts=("workspace/b.py",), skipped=())

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
    from deerflow_extension_workflows.ultracode import RESULT_NOTE, UltracodeMode

    middleware = UltracodeMode({"max_calls": 40, "concurrency": 4})

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
    assert text.startswith("base prompt") and "## Double Plus Ultracode mode" in text
    flat = " ".join(text.split())
    assert "up to 12 agents, at most 4 at once" in flat

    unavailable = middleware.apply(request({"plugin_options": {"community.workflows": {"mode": "ultracode"}}}))
    assert "cannot start workflows" in unavailable.system_message.content

    marker = {EXTENSION_MESSAGE_ORIGIN_KEY: {"namespace": "community.workflows"}}
    posted = HumanMessage(id="workflow-result-abc", content="[Workflow result] ...", additional_kwargs=marker)
    assert RESULT_NOTE in middleware.apply(request({}, [posted])).system_message.content
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
    question = {"type": "tool", "artifact": {"human_input": {"kind": "human_input_request"}}}
    assert open_question([{"type": "human"}, question]) is True
    assert open_question([question, {"type": "human"}]) is False
