"""Democracy panels — multi-model deliberation (fork feature).

A Democracy run is one *organizer* model dispatching one identical assignment to
several deliberately different *panelist* models, then synthesizing what came
back. Four properties carry the design, and each is pinned here because each one
fails **silently** when broken — the run still produces a confident answer, it is
just no longer the answer the user paid for:

* **A per-call ``model=`` beats everything else and cannot fall back.** The
  per-thread subagent dropdown and the cost-aware routing policy (FORK.md §15)
  both exist to push subagents onto one cheap model. Either one winning over an
  explicit panelist selection would quietly run N panelists on one model and
  report N independent opinions.
* **The panel is filtered against the model catalog, not trusted.** A roster
  entry that is not a configured model is dropped, and a panel below quorum
  renders no organizer section at all.
* **The organizer collects shared facts once.** The naive reading of "ask five
  models" is five retrievals of the same data — 5x the cost, and five slightly
  different datasets for the panel to disagree about.
* **The synthesis reports the distribution, including dissent.** Flattening 4-1
  into "the panel concluded" is the failure mode that makes a panel worse than
  a single model, because it launders a disagreement into false confidence.
"""

from __future__ import annotations

import asyncio
import importlib
from enum import Enum
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.agents.lead_agent.democracy import (
    MAX_DEMOCRACY_PARTICIPANTS,
    MIN_DEMOCRACY_PARTICIPANTS,
    build_democracy_section,
    normalize_democracy_grading,
    normalize_democracy_participants,
)
from deerflow.subagents.config import SubagentConfig

task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

PANEL = ["premium", "cheap-cloud", "local-tools"]


# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------


class TestPanelRoster:
    def test_keeps_the_users_order(self):
        assert normalize_democracy_participants(["c", "a", "b"], configured_models=["a", "b", "c"]) == ["c", "a", "b"]

    def test_deduplicates_without_reordering(self):
        # One model listed twice is one opinion at twice the price, so the
        # duplicate is dropped rather than dispatched.
        panel = normalize_democracy_participants(["a", "b", "a"], configured_models=["a", "b"])
        assert panel == ["a", "b"]

    def test_drops_models_that_are_not_configured(self):
        panel = normalize_democracy_participants(["a", "ghost", "b"], configured_models=["a", "b"])
        assert panel == ["a", "b"]

    def test_a_panel_below_quorum_is_no_panel(self):
        # Filtering can take a real roster below two models; the result must be
        # "no panel" rather than a one-model panel that still claims consensus.
        assert normalize_democracy_participants(["a", "ghost"], configured_models=["a", "b"]) == []
        assert normalize_democracy_participants(["a"], configured_models=["a"]) == []
        assert MIN_DEMOCRACY_PARTICIPANTS == 2

    def test_roster_is_capped(self):
        names = [f"m{i}" for i in range(MAX_DEMOCRACY_PARTICIPANTS + 5)]
        panel = normalize_democracy_participants(names, configured_models=names)
        assert len(panel) == MAX_DEMOCRACY_PARTICIPANTS

    def test_no_catalog_skips_the_membership_filter(self):
        # The embedded client and tests have no readable catalog; that must not
        # turn every panel into an empty one.
        assert normalize_democracy_participants(["a", "b"], configured_models=None) == ["a", "b"]

    def test_an_empty_catalog_is_a_real_catalog_and_drops_everything(self):
        assert normalize_democracy_participants(["a", "b"], configured_models=[]) == []

    @pytest.mark.parametrize("raw", [None, "a,b", 5, {"a": 1}])
    def test_malformed_context_is_not_a_panel(self, raw):
        assert normalize_democracy_participants(raw, configured_models=["a", "b"]) == []

    def test_non_string_and_blank_entries_are_skipped(self):
        panel = normalize_democracy_participants(["a", "", None, 7, "  b  "], configured_models=["a", "b"])
        assert panel == ["a", "b"]


# ---------------------------------------------------------------------------
# The organizer section
# ---------------------------------------------------------------------------


def _flat(text: str) -> str:
    """Collapse whitespace so an assertion pins the wording, not the wrapping.

    The section is hand-wrapped prose; re-flowing a paragraph must not fail a
    test that is really about what the organizer is told to do.
    """
    return " ".join(text.split())


class TestOrganizerSection:
    def test_no_section_below_quorum(self):
        assert build_democracy_section([], max_total=12) == ""
        assert build_democracy_section(["only-one"], max_total=12) == ""

    def test_names_every_panelist_in_the_exact_form_the_tool_takes(self):
        section = build_democracy_section(PANEL, max_total=12)
        for name in PANEL:
            # The organizer copies these lines into `task` calls, so the rendered
            # form must be the argument syntax, not prose naming the model.
            assert f'`model="{name}"`' in section

    def test_shared_facts_are_collected_once_by_the_organizer(self):
        section = build_democracy_section(PANEL, max_total=12)
        assert "you gather the shared facts, once" in _flat(section)
        assert "identical brief to every panelist" in _flat(section)
        assert f"{len(PANEL)}x for one dataset" in _flat(section)

    def test_facts_are_taken_as_given_and_not_re_verified(self):
        section = build_democracy_section(PANEL, max_total=12)
        assert "Treat gathered facts as given. Do not spend a round verifying them." in _flat(section)
        assert "Record the source alongside each fact" in _flat(section)

    def test_every_panelist_gets_the_same_wording(self):
        section = build_democracy_section(PANEL, max_total=12)
        assert "the same brief and the same question, word for word" in _flat(section)
        assert "measuring your prompts, not their judgement" in _flat(section)

    def test_cross_review_is_anonymized(self):
        section = build_democracy_section(PANEL, max_total=12)
        assert "anonymized" in section
        assert "defers to the name" in _flat(section)

    def test_synthesis_must_report_dissent_rather_than_flatten_it(self):
        section = build_democracy_section(PANEL, max_total=12)
        assert "including a lone dissenter" in _flat(section)
        assert 'flattened into "the panel concluded"' in _flat(section)
        assert "do not hold a vote as though model count were evidence" in _flat(section)
        assert "do not privilege your own Phase 1 hunch" in _flat(section)

    def test_budget_line_states_the_two_phase_arithmetic(self):
        section = build_democracy_section(PANEL, max_total=12)
        assert f"{len(PANEL)} panelists over two phases is {len(PANEL) * 2}" in _flat(section)
        assert "You have 12" in _flat(section)

    def test_budget_line_reports_the_clamped_total_not_the_request(self):
        # The run's real allowance is clamped; printing the unclamped request
        # would have the organizer plan against a budget it does not have.
        section = build_democracy_section(PANEL, max_total=9999)
        assert "You have 50" in _flat(section)


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


def _stub_prompt_environment(monkeypatch):
    config = SimpleNamespace(
        sandbox=SimpleNamespace(mounts=[]),
        skills=SimpleNamespace(container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: "/tmp/skills"),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr(prompt_module, "_get_enabled_skills", lambda: [])
    monkeypatch.setattr(prompt_module, "get_deferred_tools_prompt_section", lambda **kwargs: "")
    monkeypatch.setattr(prompt_module, "_build_acp_section", lambda **kwargs: "")
    monkeypatch.setattr(prompt_module, "_build_custom_mounts_section", lambda **kwargs: "")
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda agent_name=None, **kwargs: "")
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda agent_name=None, **kwargs: "")
    monkeypatch.setattr(prompt_module, "get_available_subagent_names", lambda **kwargs: ["general-purpose"])


class TestPromptWiring:
    def test_panel_renders_the_organizer_section(self, monkeypatch):
        _stub_prompt_environment(monkeypatch)
        prompt = prompt_module.apply_prompt_template(subagent_enabled=True, democracy_participants=PANEL)
        assert "<democracy_panel>" in prompt
        assert '`model="premium"`' in prompt

    def test_an_ordinary_ultra_run_is_untouched(self, monkeypatch):
        _stub_prompt_environment(monkeypatch)
        prompt = prompt_module.apply_prompt_template(subagent_enabled=True)
        assert "<democracy_panel>" not in prompt
        assert "<subagent_system>" in prompt

    def test_a_roster_without_the_organizer_brief_cannot_leak_in_from_a_client(self, monkeypatch):
        """The frontend clears the roster when the mode is not Democracy, but the
        run context is client-supplied — an IM channel or embedded caller can send
        anything. The prompt layer's own gate is that a sub-quorum roster renders
        nothing, so a partially-populated context degrades to Ultra rather than
        dispatching a one-model 'panel'.
        """
        _stub_prompt_environment(monkeypatch)
        prompt = prompt_module.apply_prompt_template(subagent_enabled=True, democracy_participants=["only-one"])
        assert "<democracy_panel>" not in prompt
        assert "<subagent_system>" in prompt

    def test_a_panel_without_subagents_is_not_a_panel(self, monkeypatch):
        # Every panelist is dispatched through `task`. Rendering organizer rules
        # for a run that has no `task` tool would instruct the model to call a
        # tool it was not given.
        _stub_prompt_environment(monkeypatch)
        prompt = prompt_module.apply_prompt_template(subagent_enabled=False, democracy_participants=PANEL)
        assert "<democracy_panel>" not in prompt

    def test_no_subagents_available_means_no_organizer_section(self, monkeypatch):
        _stub_prompt_environment(monkeypatch)
        monkeypatch.setattr(prompt_module, "get_available_subagent_names", lambda **kwargs: [])
        prompt = prompt_module.apply_prompt_template(subagent_enabled=True, democracy_participants=PANEL)
        assert "<democracy_panel>" not in prompt

    def test_the_section_rides_the_subagent_placeholder(self, monkeypatch):
        """An operator's saved SYSTEM_PROMPT.md (FORK.md §19) predates this
        feature and has no `{democracy_section}` of its own. Riding
        `{subagent_section}` is what keeps such a template working: a panel is
        dispatched entirely through `task`, so any template that can run a panel
        at all already carries that placeholder.
        """
        _stub_prompt_environment(monkeypatch)
        monkeypatch.setattr(prompt_module, "get_system_prompt_template", lambda: "ONLY:{subagent_section}")
        prompt = prompt_module.apply_prompt_template(subagent_enabled=True, democracy_participants=PANEL)
        assert prompt.startswith("ONLY:")
        assert "<democracy_panel>" in prompt


# ---------------------------------------------------------------------------
# The per-call model on `task`
# ---------------------------------------------------------------------------


class _Model:
    def __init__(self, name):
        self.name = name


def _no_sleep(*_args, **_kwargs):
    async def _sleep():
        return None

    return _sleep()


def _make_runtime(*, app_config=None, subagent_model_name=None) -> SimpleNamespace:
    context = {"thread_id": "thread-1"}
    if app_config is not None:
        context["app_config"] = app_config
    if subagent_model_name is not None:
        context["subagent_model_name"] = subagent_model_name
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": {}},
        context=context,
        config={"metadata": {"model_name": "organizer-model", "trace_id": "trace-1"}},
    )


def _run_task_tool(**kwargs):
    coroutine = getattr(task_tool_module.task_tool, "coroutine", None)
    if coroutine is not None:
        return asyncio.run(coroutine(**kwargs))
    return task_tool_module.task_tool.func(**kwargs)


def _message(result) -> ToolMessage:
    assert isinstance(result, Command)
    messages = result.update["messages"]
    assert len(messages) == 1
    return messages[0]


@pytest.fixture()
def panel_task_tool(monkeypatch):
    """Drive the real `task_tool` with the executor and result polling stubbed."""
    captured: dict = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "task-1"

    class _Status(Enum):
        # Production logs `result.status.value` and compares against these
        # members, so the stub has to be a real enum, not sentinel strings.
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"
        TIMED_OUT = "timed_out"

    get_available_tools = MagicMock(return_value=[])
    captured["get_available_tools"] = get_available_tools

    monkeypatch.setattr(task_tool_module, "SubagentStatus", _Status)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(
        task_tool_module,
        "get_subagent_config",
        lambda *args, **kwargs: SubagentConfig(name="general-purpose", description="d", system_prompt="p", max_turns=5, timeout_seconds=5),
    )
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda *args, **kwargs: ["general-purpose"])
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _id: SimpleNamespace(
            status=_Status.COMPLETED,
            ai_messages=[],
            result="done",
            error=None,
            stop_reason=None,
            token_usage_records=[],
            usage_reported=False,
        ),
    )
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda *a, **k: None)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", get_available_tools)
    return captured


def _app_config(models, *, model_routing=None):
    return SimpleNamespace(models=[_Model(name) for name in models], model_routing=model_routing)


class TestPerCallModel:
    def test_per_call_model_runs_the_subagent_on_that_model(self, panel_task_tool):
        runtime = _make_runtime(app_config=_app_config(PANEL))
        result = _run_task_tool(
            runtime=runtime,
            description="panelist",
            prompt="the brief",
            subagent_type="general-purpose",
            tool_call_id="tc-1",
            model="cheap-cloud",
        )

        assert _message(result).content == "Task Succeeded. Result: done"
        assert panel_task_tool["executor_kwargs"]["model_override"] == "cheap-cloud"
        assert panel_task_tool["executor_kwargs"]["parent_model"] == "cheap-cloud"
        # The tool set is gated on the model that will actually run, not on the
        # inherited one — a vision-only tool must follow the panelist.
        assert panel_task_tool["get_available_tools"].call_args.kwargs["model_name"] == "cheap-cloud"

    def test_per_call_model_beats_the_per_thread_subagent_dropdown(self, panel_task_tool):
        """The dropdown (FORK.md §3) is thread-wide; ``model=`` is this one
        delegation. The more specific selection wins, or every panelist in a
        thread with a dropdown selection would run on the dropdown's model.
        """
        runtime = _make_runtime(app_config=_app_config(PANEL), subagent_model_name="local-tools")
        _run_task_tool(
            runtime=runtime,
            description="panelist",
            prompt="the brief",
            subagent_type="general-purpose",
            tool_call_id="tc-2",
            model="premium",
        )

        assert panel_task_tool["executor_kwargs"]["model_override"] == "premium"

    def test_per_call_model_stands_the_routing_policy_down(self, panel_task_tool, monkeypatch):
        """Cost-aware routing (FORK.md §15) would otherwise rewrite panelists
        onto one cheap model, and the panel would report several independent
        opinions that all came from the same model.
        """
        routing = SimpleNamespace(enabled=True)
        monkeypatch.setattr(
            task_tool_module,
            "resolve_routed_model",
            lambda *args, **kwargs: task_tool_module.RoutingDecision("local-tools", "cheap-everything", "policy"),
        )
        runtime = _make_runtime(app_config=_app_config(PANEL, model_routing=routing))
        _run_task_tool(
            runtime=runtime,
            description="panelist",
            prompt="the brief",
            subagent_type="general-purpose",
            tool_call_id="tc-3",
            model="premium",
        )

        assert panel_task_tool["executor_kwargs"]["model_override"] == "premium"

    def test_routing_still_applies_when_no_per_call_model_is_given(self, panel_task_tool, monkeypatch):
        # The guard above must not disable the policy for ordinary delegations.
        monkeypatch.setattr(
            task_tool_module,
            "resolve_routed_model",
            lambda *args, **kwargs: task_tool_module.RoutingDecision("local-tools", "cheap-everything", "policy"),
        )
        runtime = _make_runtime(app_config=_app_config(PANEL, model_routing=SimpleNamespace(enabled=True)))
        _run_task_tool(
            runtime=runtime,
            description="ordinary",
            prompt="do a thing",
            subagent_type="general-purpose",
            tool_call_id="tc-4",
        )

        assert panel_task_tool["executor_kwargs"]["model_override"] == "local-tools"

    def test_an_unknown_model_fails_the_call_instead_of_falling_back(self, panel_task_tool):
        """Falling back would run the panelist on the inherited model and report
        it as an independent opinion from the model the user picked. Failing one
        delegation leaves the rest of the panel intact and is inspectable.
        """
        runtime = _make_runtime(app_config=_app_config(PANEL))
        result = _run_task_tool(
            runtime=runtime,
            description="panelist",
            prompt="the brief",
            subagent_type="general-purpose",
            tool_call_id="tc-5",
            model="gpt-nonexistent",
        )

        message = _message(result)
        assert "Unknown model 'gpt-nonexistent'" in message.content
        # The organizer has to be able to fix it, so the error names the catalog.
        for name in PANEL:
            assert name in message.content
        assert "executor_kwargs" not in panel_task_tool

    def test_an_unvalidatable_catalog_accepts_the_name(self, panel_task_tool):
        # No readable model catalog (embedded client, tests): there is nothing to
        # adjudicate against, so the delegation proceeds rather than failing.
        runtime = _make_runtime(app_config=_app_config([]))
        _run_task_tool(
            runtime=runtime,
            description="panelist",
            prompt="the brief",
            subagent_type="general-purpose",
            tool_call_id="tc-6",
            model="some-model",
        )

        assert panel_task_tool["executor_kwargs"]["model_override"] == "some-model"

    def test_omitting_the_model_inherits_as_before(self, panel_task_tool):
        runtime = _make_runtime(app_config=_app_config(PANEL))
        _run_task_tool(
            runtime=runtime,
            description="ordinary",
            prompt="do a thing",
            subagent_type="general-purpose",
            tool_call_id="tc-7",
        )

        assert panel_task_tool["executor_kwargs"]["model_override"] is None
        assert panel_task_tool["executor_kwargs"]["parent_model"] == "organizer-model"

    def test_the_model_argument_is_advertised_to_the_model(self):
        """The organizer can only build a panel if the tool schema exposes the
        argument, so the parameter and its description are part of the contract.
        """
        args = task_tool_module.task_tool.args
        assert "model" in args
        # The per-argument text is what the model actually sees in the schema;
        # `.description` stops at the Args block.
        model_description = args["model"]["description"]
        assert "deliberation panel" in model_description
        assert "fails the call rather than falling back" in model_description


class TestGatewayContextForwarding:
    def test_the_panel_roster_reaches_the_run_config(self):
        """`democracy_participants` must be forwarded from ``body.context``, or
        the organizer prompt renders with an empty panel and the run silently
        degrades to an ordinary Ultra turn.
        """
        from app.gateway.services import _CONTEXT_CONFIGURABLE_KEYS

        assert "democracy_participants" in _CONTEXT_CONFIGURABLE_KEYS


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


class TestGradingScale:
    @pytest.mark.parametrize("scale", ["five_point", "boolean"])
    def test_the_two_supported_scales_survive(self, scale):
        assert normalize_democracy_grading(scale) == scale

    @pytest.mark.parametrize("raw", [None, "", "ten_point", "yes", 5, True, ["boolean"]])
    def test_anything_else_is_no_grading_rather_than_a_default(self, raw):
        # Inventing a scale for a malformed context would put a scoreboard in an
        # answer the user never asked to have scored.
        assert normalize_democracy_grading(raw) is None

    def test_no_grading_renders_no_grading_phase(self):
        section = build_democracy_section(PANEL, max_total=12)
        assert "Phase 5" not in section
        # ...and leaves no hole where the section would have been.
        assert "\n\n\n" not in section

    @pytest.mark.parametrize("scale", ["five_point", "boolean"])
    def test_grading_scores_the_contribution_not_agreement(self, scale):
        section = build_democracy_section(PANEL, max_total=12, grading=scale)
        assert "Phase 5" in section
        assert "Grade the **contribution**, never agreement with your conclusion" in _flat(section)
        # The two failure modes a naive grader falls into, named explicitly.
        assert "A dissent that turned out to be right is a high grade" in _flat(section)
        assert "Restating the majority view adds nothing" in _flat(section)

    def test_grading_is_per_turn_not_cumulative(self):
        section = build_democracy_section(PANEL, max_total=12, grading="five_point")
        assert "Grade only what happened this turn" in _flat(section)

    def test_five_point_asks_for_a_score_out_of_five(self):
        section = build_democracy_section(PANEL, max_total=12, grading="five_point")
        assert "out of **5**" in section
        assert "integers only" in section
        # A scale everyone scores 4 on has stopped carrying information.
        assert "Use the whole range" in _flat(section)
        assert "yes/no" not in section

    def test_boolean_asks_for_a_yes_or_no(self):
        section = build_democracy_section(PANEL, max_total=12, grading="boolean")
        assert "plain **yes/no**" in section
        assert "earn the tokens this\nturn" in section
        assert "out of **5**" not in section


# ---------------------------------------------------------------------------
# The standing panel
# ---------------------------------------------------------------------------


class TestStandingPanel:
    def test_a_follow_up_re_runs_the_panel(self):
        section = build_democracy_section(PANEL, max_total=12)
        flat = _flat(section)
        assert "The panel is standing. Every follow-up question runs it again." in flat
        assert "never answer a follow-up yourself while the panel sits idle" in flat

    def test_each_panelist_is_re_briefed_with_its_own_history(self):
        """Subagents get a fresh ThreadState per call and remember nothing, so
        continuity exists only because the organizer carries it into the dispatch
        prompt. All four items are load-bearing and named individually.
        """
        flat = _flat(build_democracy_section(PANEL, max_total=12))
        assert "Panelists remember nothing between turns" in flat
        assert "X's own previous answers**, in X's own words, not your paraphrase" in flat
        assert "what the review round argued about last turn" in flat
        assert "the final answer you gave the user last turn" in flat
        # And why each matters, so a future edit knows what it would be removing.
        assert "a panelist contradicts itself across turns without knowing it" in flat
        assert "pays for the same debate twice" in flat

    def test_the_user_sees_one_answer_not_a_pile_of_transcripts(self):
        flat = _flat(build_democracy_section(PANEL, max_total=12))
        assert "The user reads you, and only you." in flat
        assert "One question in, one synthesized answer out" in flat
        assert "do not split your answer into branches" in flat
        assert "Panelist positions belong *inside* that answer, attributed" in flat

    def test_the_budget_is_stated_per_turn_because_the_ledger_resets(self):
        # `max_total_per_run` is per run, and each user message is its own run —
        # so an organizer told it has one budget "for the conversation" would
        # ration a panel that actually gets a fresh allowance every turn.
        flat = _flat(build_democracy_section(PANEL, max_total=12))
        assert "`task` calls **per turn**" in flat
        assert "The allowance refreshes for each new user question" in flat
