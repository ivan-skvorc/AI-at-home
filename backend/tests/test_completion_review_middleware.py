"""The one review before the lead agent's final answer (FORK.md §55).

Silent when broken, each in its own way:
- the verify line must fire only for *code* edited after the last command, or
  it becomes noise the model learns to ignore (a README edit, an edit followed
  by `pytest`, a failed write that changed nothing);
- the gate fires once per run, never on a capped/error/tool-intent response,
  and stands aside while to-dos are open, or it resumes runs a guard stopped;
- the reminder rides the next request hidden from the UI and survives a retry;
- the learning lines need skill evolution on and `skill_manage` bound;
- after the run, loaded skills reach the per-user ledger.
"""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.completion_review_middleware import (
    COMPLETION_REVIEW_MESSAGE_NAME,
    CompletionReviewMiddleware,
    build_completion_reminder,
    current_turn,
    skills_used,
)
from deerflow.agents.middlewares.skill_usage import SKILL_USAGE_KEY

TOOLS = frozenset({"bash", "write_file", "str_replace", "read_file", "skill_manage"})


def _call(tool: str, call_id: str, **args) -> dict:
    return {"name": tool, "args": args, "id": call_id, "type": "tool_call"}


def _turn(*steps: tuple[str, dict, str]) -> list:
    """steps: (tool name, args, result text) — one AI message + tool result each."""
    messages: list = [HumanMessage(content="fix the bug")]
    for index, (name, args, result) in enumerate(steps):
        call_id = f"c{index}"
        messages.append(AIMessage(content="", tool_calls=[_call(name, call_id, **args)]))
        messages.append(ToolMessage(content=result, tool_call_id=call_id, name=name))
    messages.append(AIMessage(content="Done."))
    return messages


def _reminder(messages, **overrides):
    kwargs = {"tool_names": TOOLS, "verify_code_edits": True, "skill_learning": False, "nudge_after_tool_calls": 8}
    kwargs.update(overrides)
    return build_completion_reminder(current_turn(messages), **kwargs)


class TestVerifyLine:
    def test_code_edited_and_never_run_is_reminded_with_the_file_names(self) -> None:
        text = _reminder(_turn(("str_replace", {"path": "/mnt/user-data/workspace/app/main.py"}, "OK"), ("write_file", {"path": "/w/util.ts"}, "OK")))
        assert text is not None and "main.py, util.ts" in text and "ran no command" in text
        assert text.startswith("<system_reminder>") and text.endswith("</system_reminder>")

    def test_a_command_after_the_last_edit_counts_as_verified(self) -> None:
        assert _reminder(_turn(("str_replace", {"path": "/w/a.py"}, "OK"), ("bash", {"command": "pytest"}, "1 passed"))) is None

    def test_a_command_before_the_last_edit_does_not(self) -> None:
        text = _reminder(_turn(("bash", {"command": "pytest"}, "1 failed"), ("str_replace", {"path": "/w/a.py"}, "OK")))
        assert text is not None and "a.py" in text

    @pytest.mark.parametrize("path", ["/w/README.md", "/w/data.json", "/w/config.yaml"])
    def test_docs_and_data_are_not_code(self, path: str) -> None:
        assert _reminder(_turn(("write_file", {"path": path}, "OK"))) is None

    def test_a_failed_edit_changed_nothing(self) -> None:
        assert _reminder(_turn(("str_replace", {"path": "/w/a.py"}, "Error: String to replace not found in file: /w/a.py"))) is None

    def test_no_bash_tool_means_nothing_to_ask_for(self) -> None:
        assert _reminder(_turn(("write_file", {"path": "/w/a.py"}, "OK")), tool_names=frozenset({"write_file"})) is None

    def test_only_the_current_turn_counts(self) -> None:
        earlier = _turn(("write_file", {"path": "/w/a.py"}, "OK"))
        later = [*earlier, HumanMessage(content="thanks, now explain it"), AIMessage(content="It works by...")]
        assert _reminder(later) is None


class TestLearningLines:
    def _long_turn(self, n: int = 9) -> list:
        return _turn(*[("read_file", {"path": f"/w/f{i}.txt"}, "text") for i in range(n)])

    def test_a_long_run_without_skill_manage_is_nudged(self) -> None:
        text = _reminder(self._long_turn(), skill_learning=True)
        assert text is not None and "9 tool calls" in text and "skill_manage" in text and "ask the user" in text

    def test_below_the_threshold_or_threshold_zero_is_not(self) -> None:
        assert _reminder(self._long_turn(7), skill_learning=True) is None
        assert _reminder(self._long_turn(20), skill_learning=True, nudge_after_tool_calls=0) is None

    def test_off_when_skill_evolution_is_off_or_the_tool_is_not_bound(self) -> None:
        assert _reminder(self._long_turn(), skill_learning=False) is None
        assert _reminder(self._long_turn(), skill_learning=True, tool_names=TOOLS - {"skill_manage"}) is None

    def test_a_run_that_already_called_skill_manage_is_not_nudged(self) -> None:
        messages = self._long_turn()
        messages.insert(-1, AIMessage(content="", tool_calls=[_call("skill_manage", "s1", action="patch", name="x")]))
        messages.insert(-1, ToolMessage(content="Patched", tool_call_id="s1", name="skill_manage"))
        assert _reminder(messages, skill_learning=True) is None

    def test_a_loaded_custom_skill_gets_a_patch_line(self) -> None:
        messages = _turn(("read_file", {"path": "/mnt/skills/custom/deploy/SKILL.md"}, "---"))
        messages[2].additional_kwargs[SKILL_USAGE_KEY] = {"name": "deploy", "category": "custom"}
        text = _reminder(messages, skill_learning=True)
        assert text is not None and "custom skill(s) deploy" in text and "patch it now" in text


def _runtime(**context) -> SimpleNamespace:
    return SimpleNamespace(context={"thread_id": "t1", "run_id": "r1", **context})


def _middleware_with_tools(**kwargs) -> CompletionReviewMiddleware:
    mw = CompletionReviewMiddleware(**kwargs)
    mw._tool_names[("t1", "r1")] = TOOLS
    return mw


EDITED = _turn(("write_file", {"path": "/w/a.py"}, "OK"))


class TestGate:
    def test_jumps_back_once_per_run(self) -> None:
        mw = _middleware_with_tools()
        assert mw.after_model({"messages": EDITED}, _runtime()) == {"jump_to": "model"}
        assert mw.after_model({"messages": EDITED}, _runtime()) is None

    @pytest.mark.parametrize("stop", ["loop_capped", "token_capped", "spend_capped"])
    def test_a_capped_run_is_never_resumed(self, stop: str) -> None:
        assert _middleware_with_tools().after_model({"messages": EDITED}, _runtime(stop_reason=stop)) is None

    def test_tool_intent_and_error_fallbacks_are_left_alone(self) -> None:
        mw = _middleware_with_tools()
        intent = [*EDITED[:-1], AIMessage(content="", tool_calls=[_call("bash", "z", command="ls")])]
        assert mw.after_model({"messages": intent}, _runtime()) is None
        fallback = [*EDITED[:-1], AIMessage(content="sorry", additional_kwargs={"deerflow_error_fallback": True})]
        assert mw.after_model({"messages": fallback}, _runtime()) is None

    def test_open_todos_belong_to_the_todo_middleware(self) -> None:
        state = {"messages": EDITED, "todos": [{"content": "x", "status": "in_progress"}]}
        assert _middleware_with_tools().after_model(state, _runtime()) is None

    def test_subagents_are_not_gated(self) -> None:
        assert _middleware_with_tools().after_model({"messages": EDITED}, _runtime(is_subagent=True)) is None

    def test_the_reminder_rides_the_next_request_hidden_and_survives_a_retry(self) -> None:
        mw = _middleware_with_tools()
        mw.after_model({"messages": EDITED}, _runtime())
        seen = []

        class _Request:
            def __init__(self, messages):
                self.messages, self.tools, self.runtime = messages, [SimpleNamespace(name="bash")], _runtime()

            def override(self, messages):
                return _Request(messages)

        def failing(request):
            seen.append(request.messages)
            raise RuntimeError("provider down")

        with pytest.raises(RuntimeError):
            mw.wrap_model_call(_Request([]), failing)
        mw.wrap_model_call(_Request([]), lambda request: seen.append(request.messages) or "ok")

        assert len(seen) == 2
        for messages in seen:
            reminder = messages[-1]
            assert isinstance(reminder, HumanMessage) and reminder.name == COMPLETION_REVIEW_MESSAGE_NAME
            assert reminder.additional_kwargs["hide_from_ui"] is True
        # A reminder is drained once delivered: the third request carries none.
        mw.wrap_model_call(_Request([]), lambda request: seen.append(request.messages) or "ok")
        assert seen[-1] == []

    def test_a_persisted_reminder_does_not_start_a_new_turn(self) -> None:
        messages = [*EDITED[:-1], HumanMessage(content="r", name="todo_reminder"), AIMessage(content="Done.")]
        assert _reminder(messages) is not None


class TestFromAppConfig:
    def _config(self, *, guard=True, verify=True, learning=False):
        return SimpleNamespace(
            harness_guard=SimpleNamespace(enabled=guard, verify_before_finish=verify),
            skill_evolution=SimpleNamespace(enabled=learning, nudge_after_tool_calls=8, archive_unused_after_days=90),
        )

    def test_on_by_default_for_verification(self) -> None:
        mw = CompletionReviewMiddleware.from_app_config(self._config())
        assert mw is not None and mw.verify_code_edits and not mw.skill_learning and mw.archive_unused_after_days == 0

    def test_absent_when_both_checks_are_off(self) -> None:
        assert CompletionReviewMiddleware.from_app_config(self._config(verify=False)) is None
        assert CompletionReviewMiddleware.from_app_config(self._config(guard=False)) is None

    def test_learning_alone_builds_it_with_the_curator(self) -> None:
        mw = CompletionReviewMiddleware.from_app_config(self._config(verify=False, learning=True))
        assert mw is not None and not mw.verify_code_edits and mw.skill_learning and mw.archive_unused_after_days == 90

    def test_the_shipped_example_turns_verification_on(self) -> None:
        from deerflow.config.harness_guard_config import HarnessGuardConfig
        from deerflow.config.skill_evolution_config import SkillEvolutionConfig

        assert HarnessGuardConfig().verify_before_finish is True
        assert SkillEvolutionConfig().nudge_after_tool_calls == 8
        assert SkillEvolutionConfig().archive_unused_after_days == 90


class TestLedgerHandOff:
    def test_loaded_skills_reach_the_ledger_after_the_run(self, monkeypatch) -> None:
        recorded = {}
        mw = CompletionReviewMiddleware(verify_code_edits=False, skill_learning=True, archive_unused_after_days=0)
        monkeypatch.setattr(mw, "_record_and_curate", lambda user_id, names: recorded.update(user=user_id, names=names) or [])
        monkeypatch.setattr("deerflow.runtime.user_context.resolve_runtime_user_id", lambda runtime: "u1")
        messages = _turn(("read_file", {"path": "/mnt/skills/custom/deploy/SKILL.md"}, "---"))
        messages[2].additional_kwargs[SKILL_USAGE_KEY] = {"name": "deploy", "category": "custom"}

        mw.after_agent({"messages": messages}, _runtime())

        assert recorded == {"user": "u1", "names": ["deploy"]}

    def test_no_ledger_work_while_skill_evolution_is_off(self, monkeypatch) -> None:
        mw = CompletionReviewMiddleware(verify_code_edits=True, skill_learning=False)
        monkeypatch.setattr(mw, "_record_and_curate", lambda *a: pytest.fail("ledger touched"))
        mw.after_agent({"messages": EDITED}, _runtime())

    def test_a_ledger_failure_never_fails_the_run(self, monkeypatch) -> None:
        mw = CompletionReviewMiddleware(verify_code_edits=False, skill_learning=True)

        def boom(*_a):
            raise OSError("disk full")

        monkeypatch.setattr(mw, "_record_and_curate", boom)
        monkeypatch.setattr("deerflow.runtime.user_context.resolve_runtime_user_id", lambda runtime: "u1")
        assert mw.after_agent({"messages": EDITED}, _runtime()) is None


def test_skills_used_dedupes_and_filters_by_category() -> None:
    a = ToolMessage(content="x", tool_call_id="1", additional_kwargs={SKILL_USAGE_KEY: {"name": "deploy", "category": "custom"}})
    b = ToolMessage(content="x", tool_call_id="2", additional_kwargs={SKILL_USAGE_KEY: {"name": "deploy", "category": "custom"}})
    c = ToolMessage(content="x", tool_call_id="3", additional_kwargs={SKILL_USAGE_KEY: {"name": "deep-research", "category": "public"}})
    assert skills_used([a, b, c]) == ["deploy", "deep-research"]
    assert skills_used([a, b, c], category="custom") == ["deploy"]


class TestRealAgentGraph:
    """The jump back works inside a real agent graph, and the reminder is never persisted."""

    @pytest.mark.parametrize("invoke_async", [False, True], ids=["sync", "async"])
    def test_an_unverified_edit_gets_one_more_model_call_with_a_transient_reminder(self, invoke_async) -> None:
        import asyncio
        from typing import Any

        from langchain.agents import create_agent
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.tools import tool
        from pydantic import PrivateAttr

        class _Capturing(FakeMessagesListChatModel):
            _seen: list[list[Any]] = PrivateAttr(default_factory=list)

            def bind_tools(self, tools, *, tool_choice=None, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self._seen.append(list(messages))
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        @tool
        def write_file(path: str, content: str) -> str:
            """Write a file."""
            return "OK"

        @tool
        def bash(command: str) -> str:
            """Run a command."""
            return "1 passed"

        model = _Capturing(
            responses=[
                AIMessage(content="", tool_calls=[_call("write_file", "w1", path="/w/app.py", content="x = 1\n")]),
                AIMessage(content="Done, wrote app.py."),
                AIMessage(content="", tool_calls=[_call("bash", "b1", command="pytest -q")]),
                AIMessage(content="Done, and the tests pass."),
            ]
        )
        graph = create_agent(model=model, tools=[write_file, bash], middleware=[CompletionReviewMiddleware()])
        state = {"messages": [("user", "add app.py")]}
        context = {"thread_id": "graph-thread", "run_id": "graph-run"}

        result = asyncio.run(graph.ainvoke(state, context=context)) if invoke_async else graph.invoke(state, context=context)

        assert len(model._seen) == 4  # the held-back answer cost exactly one extra call, then the run ended
        reminders = [[m for m in seen if getattr(m, "name", None) == COMPLETION_REVIEW_MESSAGE_NAME] for seen in model._seen]
        assert [len(r) for r in reminders] == [0, 0, 1, 0]
        assert "app.py" in reminders[2][0].content
        assert not [m for m in result["messages"] if getattr(m, "name", None) == COMPLETION_REVIEW_MESSAGE_NAME]
        assert result["messages"][-1].content == "Done, and the tests pass."
