"""The ``tool_result:`` acceptance leaf reads a host-stamped tool result.

A delegated deliverable that a plugin tool judges (a build that reports
``passed``) is accepted on the tool's own recorded answer, never on files the
subagent could have written itself. The executor harvests a bounded record of
the calls a criterion names, and the leaf lets the newest matching call
decide. Anything the record cannot prove stays UNVERIFIED.
"""

import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from deerflow.agents.middlewares.tool_transform_meta import append_tool_transform
from deerflow.config.app_config import AppConfig
from deerflow.extensions.plugin_tools import plugin_tool_name
from deerflow.subagents.acceptance_checks import check_acceptance_criteria, parse_tool_result_criterion, tool_result_harvest_plan
from deerflow.subagents.config import SubagentConfig

BUILD = plugin_tool_name("parts", "build_part")
CRITERION = 'tool_result:parts/build_part passed=true where name="bracket-a"'
PLAN = {BUILD: (frozenset({"passed"}), frozenset({"name"}))}


@pytest.fixture
def executor_module(monkeypatch, tmp_path):
    # conftest installs an executor stub. Load the production module separately
    # so the real subagent graph streams, harvests and merges the evidence.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_tool_result_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    yield module
    module._shutdown_isolated_subagent_loop()


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _call(call_id: str, name: str = "bracket-a", *, tool: str = BUILD, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": tool, "id": call_id, "args": {"name": name, **args}}])


def _answer(call_id: str, passed: bool, *, result_id: str | None = None, **fields) -> ToolMessage:
    return ToolMessage(content=json.dumps({"passed": passed, **fields}), tool_call_id=call_id, id=result_id)


def _verdict(criterion: str, tool_results):
    return check_acceptance_criteria([criterion], tool_results=tool_results)


def _leaf(criterion: str, tool_results):
    return _verdict(criterion, tool_results)["leaves"][0]


def _outcome(leaf) -> tuple[bool, bool]:
    return leaf["checked"], leaf["holds"]


async def _run_subagent(executor_module, monkeypatch, responses, tools, criteria):
    model = ScriptedModel(messages=iter(responses))
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: model)
    app_config = AppConfig.model_validate(
        {
            "models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "summarization": {"enabled": False},
        }
    )
    executor = executor_module.SubagentExecutor(
        config=SubagentConfig(name="builder", description="Offline part builder", skills=[]),
        tools=tools,
        parent_model="offline",
        app_config=app_config,
        thread_id="tool-result-thread",
        user_id="tool-result-user",
        acceptance_criteria=criteria,
    )
    return await executor._aexecute("Build the part")


def _build_tool(answers: list[bool], calls: list[str]) -> StructuredTool:
    outcomes = iter(answers)

    def build_part(name: str) -> str:
        """Build one part and measure it."""
        calls.append(name)
        return json.dumps({"passed": next(outcomes), "files": [f"{name}.step"]})

    return StructuredTool.from_function(build_part, name=BUILD)


# --- Through the real subagent graph ---------------------------------------


@pytest.mark.asyncio
async def test_holds_on_a_passed_result(executor_module, monkeypatch):
    calls = []
    result = await _run_subagent(
        executor_module,
        monkeypatch,
        [_call("call_0"), AIMessage(content="Built bracket-a.")],
        [_build_tool([True], calls)],
        [CRITERION],
    )

    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert calls == ["bracket-a"]
    verdict = _verdict(CRITERION, result.tool_results)
    leaf = verdict["leaves"][0]
    assert (leaf["family"], leaf["checked"], leaf["holds"], verdict["all_hold"]) == ("tool_result", True, True, True), verdict


@pytest.mark.asyncio
async def test_a_later_failure_overrides_an_earlier_pass(executor_module, monkeypatch):
    calls = []
    result = await _run_subagent(
        executor_module,
        monkeypatch,
        [_call("call_0"), _call("call_1"), AIMessage(content="Rebuilt bracket-a.")],
        [_build_tool([True, False], calls)],
        [CRITERION],
    )

    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert calls == ["bracket-a", "bracket-a"]
    # The newest matching call decides: an earlier pass does not save it.
    assert _outcome(_leaf(CRITERION, result.tool_results)) == (True, False)


@pytest.mark.asyncio
@pytest.mark.parametrize(("build_first", "expected"), [(False, (False, False)), (True, (True, False))])
async def test_a_forged_report_file_without_a_passing_call_does_not_hold(executor_module, monkeypatch, build_first, expected):
    calls, writes = [], []

    def write_file(path: str, content: str) -> str:
        """Write a file."""
        writes.append(path)
        return "OK"

    forge = AIMessage(content="", tool_calls=[{"name": "write_file", "id": "call_w", "args": {"path": "/mnt/user-data/outputs/bracket-a.report.json", "content": json.dumps({"name": "bracket-a", "passed": True})}}])
    responses = ([_call("call_0")] if build_first else []) + [forge, AIMessage(content="bracket-a passed, see its report.")]
    result = await _run_subagent(
        executor_module,
        monkeypatch,
        responses,
        [_build_tool([False], calls), StructuredTool.from_function(write_file, name="write_file")],
        [CRITERION],
    )

    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert writes == ["/mnt/user-data/outputs/bracket-a.report.json"]
    # No call: UNVERIFIED. A failed call: a checked negative. Never a pass.
    assert _outcome(_leaf(CRITERION, result.tool_results)) == expected


@pytest.mark.asyncio
async def test_a_harvest_exception_leaves_the_run_outcome_unchanged(executor_module, monkeypatch):
    fired = []

    def explode(*args, **kwargs):
        fired.append(True)
        raise RuntimeError("injected harvest failure")

    monkeypatch.setattr(executor_module, "_tool_result_entry", explode)
    calls = []
    result = await _run_subagent(
        executor_module,
        monkeypatch,
        [_call("call_0"), AIMessage(content="Built bracket-a.")],
        [_build_tool([True], calls)],
        [CRITERION],
    )

    assert fired, "the injected failure never ran"
    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert result.result == "Built bracket-a."
    # Chunks before the call published an empty record; the failing ones added nothing.
    assert not result.tool_results
    assert _outcome(_leaf(CRITERION, result.tool_results)) == (False, False)


@pytest.mark.asyncio
async def test_a_run_without_tool_result_criteria_harvests_nothing(executor_module, monkeypatch):
    calls = []
    result = await _run_subagent(
        executor_module,
        monkeypatch,
        [_call("call_0"), AIMessage(content="Built bracket-a.")],
        [_build_tool([True], calls)],
        ["file:../outputs/bracket-a.step exists"],
    )

    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert result.tool_results is None


@pytest.mark.asyncio
async def test_the_harvest_plan_resolves_once_off_the_event_loop(executor_module, monkeypatch):
    # Resolving a plugin tool name imports the extension stack (jsonschema
    # lists its schema files on import), which must not run on the loop.
    from deerflow.subagents import acceptance_checks

    threads = []
    plan = acceptance_checks.tool_result_harvest_plan

    def spy(criteria):
        threads.append(threading.get_ident())
        return plan(criteria)

    monkeypatch.setattr(acceptance_checks, "tool_result_harvest_plan", spy)
    calls = []
    result = await _run_subagent(
        executor_module,
        monkeypatch,
        [_call("call_0"), AIMessage(content="Built bracket-a.")],
        [_build_tool([True], calls)],
        [CRITERION],
    )

    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert len(threads) == 1 and threads[0] != threading.get_ident()
    assert _outcome(_leaf(CRITERION, result.tool_results)) == (True, True)


# --- The harvest on synthetic message streams --------------------------------


def test_a_pass_for_another_part_does_not_satisfy_where(executor_module):
    only_other = executor_module._harvest_tool_results({"messages": [_call("call_0", "bracket-b"), _answer("call_0", True)]}, PLAN)
    assert _outcome(_leaf(CRITERION, only_other)) == (False, False)

    other_after_fail = executor_module._harvest_tool_results(
        {"messages": [_call("call_0"), _answer("call_0", False), _call("call_1", "bracket-b"), _answer("call_1", True)]},
        PLAN,
    )
    # bracket-a's own newest call failed; bracket-b's later pass is not its evidence.
    assert _outcome(_leaf(CRITERION, other_after_fail)) == (True, False)


def test_the_tool_resolves_through_the_plugin_tool_name(executor_module):
    plan = tool_result_harvest_plan([CRITERION])
    assert plan == PLAN
    messages = [
        _call("call_0", tool=plugin_tool_name("other", "build_part")),
        _answer("call_0", True),
        _call("call_1", tool="build_part"),
        _answer("call_1", True),
    ]
    entries = executor_module._harvest_tool_results({"messages": messages}, plan)
    # Neither another namespace's tool nor the bare declaration name is the criterion's tool.
    assert entries == []
    assert _outcome(_leaf(CRITERION, entries)) == (False, False)


def _single(executor_module, answer) -> list[dict]:
    messages = [_call("call_0")] + ([answer] if answer is not None else [])
    return executor_module._harvest_tool_results({"messages": messages}, PLAN)


def _transformed(kind: str) -> ToolMessage:
    message = _answer("call_0", True)
    append_tool_transform(message.additional_kwargs, kind, by="test")
    return message


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (ToolMessage(content="Error: Plugin tool unavailable or input rejected.", tool_call_id="call_0"), "not a JSON object"),
        (ToolMessage(content=json.dumps([{"passed": True}]), tool_call_id="call_0"), "not a JSON object"),
        (ToolMessage(content='{"passed": true, "volume": NaN}', tool_call_id="call_0"), "not a JSON object"),
        (ToolMessage(content=[{"type": "text", "text": '{"passed": true}'}], tool_call_id="call_0"), "not a JSON object"),
        (_transformed("truncated"), "truncated"),
        (_transformed("externalized"), "truncated"),
        (_transformed("pii_redaction"), "rewritten"),
        (ToolMessage(content=json.dumps({"passed": True, "log": "x" * (64 * 1024)}), tool_call_id="call_0"), "64 KB"),
        (ToolMessage(content='{"passed": true}', tool_call_id="call_0", status="error"), "tool error"),
        (None, "no recorded result"),
    ],
)
def test_an_unusable_newest_result_is_unverified(executor_module, answer, reason):
    leaf = _leaf(CRITERION, _single(executor_module, answer))

    assert _outcome(leaf) == (False, False), leaf
    assert reason in leaf["detail"]


def test_an_unusable_newest_result_is_not_rescued_by_an_earlier_pass(executor_module):
    messages = [_call("call_0"), _answer("call_0", True), _call("call_1"), _transformed("truncated").model_copy(update={"tool_call_id": "call_1"})]
    leaf = _leaf(CRITERION, executor_module._harvest_tool_results({"messages": messages}, PLAN))

    assert _outcome(leaf) == (False, False)


def test_a_compacted_deciding_call_is_unverified(executor_module):
    before = {"messages": [HumanMessage(content="Build it"), _call("call_0"), _answer("call_0", True, result_id="r0")]}
    # Summarization replaced the history: the passing call is gone from the state.
    after = {"messages": [HumanMessage(content="Summary of earlier work"), AIMessage(content="Continuing.")]}
    result = executor_module.SubagentResult(task_id="task", trace_id="trace", status=executor_module.SubagentStatus.RUNNING)

    result.update_tool_results(executor_module._harvest_tool_results(before, PLAN))
    assert _outcome(_leaf(CRITERION, result.tool_results)) == (True, True)
    result.update_tool_results(executor_module._harvest_tool_results(after, PLAN))

    leaf = _leaf(CRITERION, result.tool_results)
    assert _outcome(leaf) == (False, False), leaf
    assert "compaction" in leaf["detail"]

    # A newer call that is still in the history decides again.
    later = {"messages": [*after["messages"], _call("call_1"), _answer("call_1", True, result_id="r1")]}
    result.update_tool_results(executor_module._harvest_tool_results(later, PLAN))
    assert _outcome(_leaf(CRITERION, result.tool_results)) == (True, True)


def test_a_result_arriving_in_a_later_chunk_completes_its_entry(executor_module):
    result = executor_module.SubagentResult(task_id="task", trace_id="trace", status=executor_module.SubagentStatus.RUNNING)
    pending = {"messages": [_call("call_0").model_copy(update={"id": "ai-0"})]}
    answered = {"messages": [*pending["messages"], _answer("call_0", True, result_id="r0")]}

    result.update_tool_results(executor_module._harvest_tool_results(pending, PLAN))
    assert _outcome(_leaf(CRITERION, result.tool_results)) == (False, False)
    result.update_tool_results(executor_module._harvest_tool_results(answered, PLAN))

    assert len(result.tool_results) == 1
    assert _outcome(_leaf(CRITERION, result.tool_results)) == (True, True)


def test_concurrent_calls_of_one_turn_that_disagree_are_unverified(executor_module):
    both = AIMessage(content="", tool_calls=[{"name": BUILD, "id": "call_0", "args": {"name": "bracket-a"}}, {"name": BUILD, "id": "call_1", "args": {"name": "bracket-a"}}])
    messages = [both, _answer("call_0", True), _answer("call_1", False)]
    leaf = _leaf(CRITERION, executor_module._harvest_tool_results({"messages": messages}, PLAN))

    # Calls of one turn ran concurrently, in no fixed order: neither is newer.
    assert _outcome(leaf) == (False, False), leaf
    assert "concurrent" in leaf["detail"]


def test_harvest_bounds_hold(executor_module):
    plan = tool_result_harvest_plan(['tool_result:parts/build_part status="ok" where name="p-24"'])
    long_name = "n" * 121
    messages = []
    for index in range(25):
        name = f"p-{index}"
        messages.append(AIMessage(content="", tool_calls=[{"name": BUILD, "id": f"call_{index}", "args": {"name": name, "script": "s" * 50, "sizes": [1, 2]}}]))
        messages.append(ToolMessage(content=json.dumps({"status": "ok", "passed": True, "note": "n" * 121, "nested": {"a": 1}}), tool_call_id=f"call_{index}"))
    messages += [
        AIMessage(content="", tool_calls=[{"name": "web_search", "id": "call_s", "args": {"query": "q"}}]),
        ToolMessage(content=json.dumps({"status": "ok"}), tool_call_id="call_s"),
        AIMessage(content="", tool_calls=[{"name": BUILD, "id": "call_long", "args": {"name": long_name}}]),
        ToolMessage(content=json.dumps({"status": "x" * 121}), tool_call_id="call_long"),
    ]

    entries = executor_module._harvest_tool_results({"messages": messages}, plan)

    # The newest 20 calls of the named tools only.
    assert len(entries) == 20
    assert {entry["tool_name"] for entry in entries} == {BUILD}
    assert [entry["tool_call_id"] for entry in entries] == [f"call_{index}" for index in range(6, 25)] + ["call_long"]
    # Only the argument and field a criterion names, scalar and at most 120 characters.
    assert entries[-2]["args"] == {"name": "p-24"} and entries[-2]["fields"] == {"status": "ok"}
    assert entries[-1]["args"] == {} and entries[-1]["fields"] == {}
    assert _outcome(_leaf('tool_result:parts/build_part status="ok" where name="p-24"', entries)) == (True, True)
    # An expected value beyond the 120-character bound can never be proven.
    leaf = _leaf(f'tool_result:parts/build_part status="ok" where name="{long_name}"', entries)
    assert _outcome(leaf) == (False, False) and "120" in leaf["detail"]

    # Across chunks the record stays the newest 20: calls that fell out of the
    # harvest window are dropped, not kept as compacted entries.
    merged = executor_module.SubagentResult(task_id="task", trace_id="trace", status=executor_module.SubagentStatus.RUNNING)
    merged.update_tool_results(executor_module._harvest_tool_results({"messages": messages[:40]}, plan))
    merged.update_tool_results(entries)
    assert [entry["tool_call_id"] for entry in merged.tool_results] == [entry["tool_call_id"] for entry in entries]
    assert not any(entry["compacted"] for entry in merged.tool_results)


def test_parse_cap_is_measured_in_bytes(executor_module):
    # Under 64 KiB in characters, over it in UTF-8 bytes.
    content = json.dumps({"passed": True, "log": "é" * (40 * 1024)}, ensure_ascii=False)
    assert len(content) < 64 * 1024 < len(content.encode())
    leaf = _leaf(CRITERION, _single(executor_module, ToolMessage(content=content, tool_call_id="call_0")))

    assert _outcome(leaf) == (False, False) and "64 KB" in leaf["detail"]


# --- The leaf grammar ---------------------------------------------------------


@pytest.mark.parametrize(
    ("criterion", "fields", "expected"),
    [
        ("tool_result:parts/build_part passed=true", {"passed": True}, (True, True)),
        ("tool_result:parts/build_part passed=true", {"passed": 1}, (True, False)),
        ("tool_result:parts/build_part passed=1", {"passed": True}, (True, False)),
        ("tool_result:parts/build_part count=2", {"count": 2.0}, (True, True)),
        ("tool_result:parts/build_part error=null", {"error": None}, (True, True)),
        ("tool_result:parts/build_part error=null", {}, (True, False)),
        ('tool_result:parts/build_part status="ok"', {"status": "OK"}, (True, False)),
        ('TOOL_RESULT:parts/build_part passed=true WHERE name="bracket a"', {"passed": True}, (True, True)),
    ],
)
def test_json_scalars_compare_by_type_and_value(criterion, fields, expected):
    entry = {"tool_name": BUILD, "tool_call_id": "c", "turn": "t", "ordinal": 0, "result_id": None, "result": "ok", "args": {"name": "bracket a"}, "fields": fields, "compacted": False}

    assert _outcome(_leaf(criterion, [entry])) == expected


@pytest.mark.parametrize(
    "criterion",
    [
        "tool_result:parts/build_part passed",
        "tool_result:build_part passed=true",
        "tool_result:parts/build_part passed=[true]",
        "tool_result:parts/build_part passed=NaN",
        "tool_result:parts/build_part passed=true and more",
        "tool_result:parts/build_part passed=true where name=bracket-a",
        "tool_result:parts/build_part passed = true",
    ],
)
def test_a_malformed_criterion_is_unverified(criterion):
    assert parse_tool_result_criterion(criterion) is None
    leaf = _leaf(criterion, [])

    assert (leaf["family"], leaf["checked"], leaf["holds"]) == ("tool_result", False, False)
    assert "expected tool_result:" in leaf["detail"]


def test_no_harvested_evidence_is_unverified():
    leaf = _leaf(CRITERION, None)

    assert _outcome(leaf) == (False, False)
    assert "no tool-result evidence" in leaf["detail"]


def test_criteria_without_a_tool_result_leaf_plan_no_harvest():
    assert tool_result_harvest_plan(["tests_passed:pytest", "file:../outputs/a.md exists", "free text"]) == {}
    assert tool_result_harvest_plan(None) == {}
