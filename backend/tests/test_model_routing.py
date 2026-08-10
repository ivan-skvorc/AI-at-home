"""Tests for cost-aware subagent routing (fork feature, roadmap item 5).

The fork exposes the cost lever but makes the user pull it every session.
FORK.md's worked example puts Sonnet-lead / Haiku-subagents at ~63% cheaper and
Sonnet-lead / local-subagents at ~95%; a policy turns that into a standing
saving.

Three properties carry the design, and each has tests here:
- no LLM classifies the task (the decision is deterministic and free);
- an explicit per-thread subagent selection always wins;
- a model is only routed to if it can actually do the job — trading a cost
  saving for a failed turn is not a trade.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.model_routing_config import ModelRoutingConfig
from deerflow.subagents.routing import RoutingDecision, TaskRequirements, resolve_routed_model


class _Model:
    def __init__(self, name, supports_tools=True, supports_vision=False, supports_thinking=False, context_window=None):
        self.name = name
        self.supports_tools = supports_tools
        self.supports_vision = supports_vision
        self.supports_thinking = supports_thinking
        self.context_window = context_window


MODELS = [
    _Model("premium", supports_vision=True, supports_thinking=True, context_window=200000),
    _Model("cheap-cloud", supports_vision=True, context_window=128000),
    _Model("local-small", supports_tools=False, context_window=32768),
    _Model("local-tools", context_window=32768),
]


def policy(**kwargs) -> ModelRoutingConfig:
    return ModelRoutingConfig.model_validate(kwargs)


# ---------------------------------------------------------------------------
# Requirements derivation
# ---------------------------------------------------------------------------


class TestTaskRequirements:
    def test_business_tools_mean_the_task_needs_tools(self):
        req = TaskRequirements.from_task(tool_names=["bash", "read_file"], prompt="do the thing")
        assert req.needs_tools is True

    def test_no_tools_means_no_tool_requirement(self):
        req = TaskRequirements.from_task(tool_names=[], prompt="summarize this")
        assert req.needs_tools is False

    def test_view_image_alone_is_a_vision_requirement_not_a_tool_one(self):
        # view_image is only bound when the model supports vision, so it is a
        # capability signal rather than business tool use.
        req = TaskRequirements.from_task(tool_names=["view_image"], prompt="what is in this picture")
        assert req.needs_vision is True
        assert req.needs_tools is False

    def test_estimated_context_grows_with_the_prompt(self):
        small = TaskRequirements.from_task(prompt="x" * 100)
        large = TaskRequirements.from_task(prompt="x" * 400_000)
        assert large.estimated_context > small.estimated_context
        assert large.estimated_context > 100_000

    def test_estimated_context_includes_overhead_for_an_empty_prompt(self):
        # System prompt, tool schemas and the answer all have to fit too.
        assert TaskRequirements.from_task(prompt="").estimated_context > 0

    def test_derivation_makes_no_model_call(self, monkeypatch):
        import deerflow.models.factory as factory

        def explode(*args, **kwargs):
            raise AssertionError("routing must not build or call a model to classify a task")

        monkeypatch.setattr(factory, "create_chat_model", explode)
        TaskRequirements.from_task(tool_names=["bash"], prompt="anything")


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


class TestResolveRoutedModel:
    def test_a_disabled_policy_routes_nothing(self):
        decision = resolve_routed_model(TaskRequirements.from_task(), ModelRoutingConfig(), MODELS)
        assert decision.model_name is None
        assert "disabled" in decision.reason

    def test_a_tool_free_subtask_routes_to_the_cheap_model(self):
        p = policy(enabled=True, rules=[{"name": "extraction", "when": {"needs_tools": False}, "prefer": ["local-small"]}])
        decision = resolve_routed_model(TaskRequirements.from_task(tool_names=[], prompt="extract the dates"), p, MODELS)
        assert decision.model_name == "local-small"
        assert decision.rule == "extraction"

    def test_a_tool_using_subtask_does_not_take_the_tool_free_rule(self):
        p = policy(enabled=True, rules=[{"name": "extraction", "when": {"needs_tools": False}, "prefer": ["local-small"]}])
        decision = resolve_routed_model(TaskRequirements.from_task(tool_names=["bash"], prompt="run the build"), p, MODELS)
        assert decision.model_name is None
        assert "no rule matched" in decision.reason

    def test_a_model_without_tool_support_is_skipped_for_a_tool_using_task(self):
        # The saving is not worth a failed turn.
        p = policy(enabled=True, rules=[{"name": "cheap-first", "prefer": ["local-small", "local-tools"]}])
        decision = resolve_routed_model(TaskRequirements.from_task(tool_names=["bash"]), p, MODELS)
        assert decision.model_name == "local-tools"
        assert "no tool support" in decision.reason

    def test_a_model_without_vision_is_skipped_for_a_vision_task(self):
        p = policy(enabled=True, rules=[{"name": "cheap-first", "prefer": ["local-tools", "cheap-cloud"]}])
        decision = resolve_routed_model(TaskRequirements.from_task(tool_names=["view_image"]), p, MODELS)
        assert decision.model_name == "cheap-cloud"
        assert "no vision support" in decision.reason

    def test_a_model_whose_context_window_is_too_small_is_skipped(self):
        p = policy(enabled=True, rules=[{"name": "cheap-first", "prefer": ["local-tools", "cheap-cloud"]}])
        requirements = TaskRequirements.from_task(prompt="x" * 400_000, tool_names=["bash"])
        decision = resolve_routed_model(requirements, p, MODELS)
        assert decision.model_name == "cheap-cloud"
        assert "context window" in decision.reason

    def test_an_unconfigured_model_name_is_reported_not_routed_to(self):
        p = policy(enabled=True, rules=[{"name": "cheap-first", "prefer": ["ghost-model", "local-tools"]}])
        decision = resolve_routed_model(TaskRequirements.from_task(tool_names=["bash"]), p, MODELS)
        assert decision.model_name == "local-tools"
        assert "not configured" in decision.reason

    def test_rules_are_evaluated_in_order(self):
        p = policy(
            enabled=True,
            rules=[
                {"name": "first", "prefer": ["cheap-cloud"]},
                {"name": "second", "prefer": ["local-tools"]},
            ],
        )
        assert resolve_routed_model(TaskRequirements.from_task(), p, MODELS).rule == "first"

    def test_a_matching_rule_with_no_capable_candidate_falls_through_to_the_next(self):
        p = policy(
            enabled=True,
            rules=[
                {"name": "too-cheap", "prefer": ["local-small"]},
                {"name": "workable", "prefer": ["local-tools"]},
            ],
        )
        decision = resolve_routed_model(TaskRequirements.from_task(tool_names=["bash"]), p, MODELS)
        assert decision.model_name == "local-tools"
        assert decision.rule == "workable"

    def test_routing_to_the_current_default_is_reported_as_unchanged(self):
        p = policy(enabled=True, rules=[{"name": "cheap", "prefer": ["cheap-cloud"]}])
        decision = resolve_routed_model(TaskRequirements.from_task(), p, MODELS, fallback_model="cheap-cloud")
        assert decision.model_name is None
        assert "already the default" in decision.reason

    def test_context_conditions_bound_a_rule(self):
        p = policy(enabled=True, rules=[{"name": "small-only", "when": {"max_context": 20000}, "prefer": ["local-tools"]}])
        assert resolve_routed_model(TaskRequirements.from_task(prompt="tiny"), p, MODELS).model_name == "local-tools"
        assert resolve_routed_model(TaskRequirements.from_task(prompt="x" * 400_000), p, MODELS).model_name is None

    def test_min_context_routes_a_big_job_up(self):
        p = policy(enabled=True, rules=[{"name": "big-job", "when": {"min_context": 100000}, "prefer": ["premium"]}])
        assert resolve_routed_model(TaskRequirements.from_task(prompt="x" * 500_000), p, MODELS).model_name == "premium"
        assert resolve_routed_model(TaskRequirements.from_task(prompt="small"), p, MODELS).model_name is None

    def test_a_decision_is_always_returned_so_the_reason_can_be_shown(self):
        decision = resolve_routed_model(TaskRequirements.from_task(), ModelRoutingConfig(), MODELS)
        assert isinstance(decision, RoutingDecision)
        assert decision.reason
        assert decision.as_dict()["reason"] == decision.reason


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestConfig:
    def test_off_by_default(self):
        assert ModelRoutingConfig().enabled is False

    def test_enabled_with_no_rules_is_a_load_time_error(self):
        with pytest.raises(ValidationError, match="no rules"):
            ModelRoutingConfig.model_validate({"enabled": True, "rules": []})

    def test_an_impossible_context_window_is_rejected(self):
        with pytest.raises(ValidationError, match="never match"):
            ModelRoutingConfig.model_validate({"enabled": True, "rules": [{"name": "bad", "when": {"min_context": 100, "max_context": 50}, "prefer": ["x"]}]})

    def test_a_rule_needs_a_name(self):
        with pytest.raises(ValidationError):
            ModelRoutingConfig.model_validate({"enabled": True, "rules": [{"prefer": ["x"]}]})

    def test_app_config_exposes_the_section_off_by_default(self):
        from deerflow.config.app_config import AppConfig

        config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "models": [{"name": "a", "use": "x:Y", "model": "a"}]})
        assert config.model_routing.enabled is False


# ---------------------------------------------------------------------------
# task_tool integration
# ---------------------------------------------------------------------------


class TestTaskToolIntegration:
    def test_an_explicit_per_thread_selection_wins_over_the_policy(self):
        from deerflow.tools.builtins.task_tool import apply_routing_policy

        p = policy(enabled=True, rules=[{"name": "cheap", "prefer": ["local-tools"]}])
        resolved, decision = apply_routing_policy(
            effective_model="premium",
            explicit_override="cheap-cloud",
            policy=p,
            models=MODELS,
            requirements=TaskRequirements.from_task(),
        )
        assert resolved == "cheap-cloud"
        assert decision.model_name is None
        assert "explicit" in decision.reason.lower()

    def test_the_policy_fills_the_default_when_there_is_no_override(self):
        from deerflow.tools.builtins.task_tool import apply_routing_policy

        p = policy(enabled=True, rules=[{"name": "cheap", "prefer": ["local-tools"]}])
        resolved, decision = apply_routing_policy(
            effective_model="premium",
            explicit_override=None,
            policy=p,
            models=MODELS,
            requirements=TaskRequirements.from_task(tool_names=["bash"]),
        )
        assert resolved == "local-tools"
        assert decision.rule == "cheap"

    def test_a_disabled_policy_leaves_the_resolved_model_alone(self):
        from deerflow.tools.builtins.task_tool import apply_routing_policy

        resolved, decision = apply_routing_policy(
            effective_model="premium",
            explicit_override=None,
            policy=ModelRoutingConfig(),
            models=MODELS,
            requirements=TaskRequirements.from_task(),
        )
        assert resolved == "premium"
        assert decision.model_name is None
