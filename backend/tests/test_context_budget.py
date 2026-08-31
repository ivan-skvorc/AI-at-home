"""Tests for context-window-aware size budgets (fork feature).

Every size limit that guards the model context — tool-output truncation and the
document chunk size — used to be a fixed character constant calibrated for a
200K-token cloud model. On a 32K local model a single 50,000-character
``read_file`` result is roughly 40% of the whole window, and on an 8K model it
is larger than the window itself.

Three properties carry the design, and each has tests here:
- the configured value is a *ceiling*, never raised — an unknown window leaves
  today's behaviour exactly as it was;
- the window is read from where it actually lives (Ollama's ``num_ctx``, a
  cloud entry's ``context_window``, or the provider profile), and the output
  reservation is subtracted because it is spent from the same window;
- a bigger window buys bigger chunks, which is what lets one code path serve
  both a local 8B and a frontier cloud model.
"""

from __future__ import annotations

import pytest

from deerflow.utils.context_budget import (
    CHARS_PER_TOKEN,
    ContextBudget,
    active_context_budget,
    chunk_chars_for,
    clamp_to_context,
    resolve_context_budget,
    use_context_budget,
)


class _Model:
    """Minimal stand-in for a chat model object."""

    def __init__(self, **attrs):
        for key, value in attrs.items():
            setattr(self, key, value)


class _ModelConfigEntry:
    def __init__(self, name, model=None, context_window=None, max_tokens=None):
        self.name = name
        self.model = model
        self.context_window = context_window
        self.max_tokens = max_tokens


class _AppConfig:
    def __init__(self, models):
        self.models = models


class TestContextBudget:
    def test_prompt_tokens_subtract_the_output_reservation(self):
        # Ollama's num_ctx covers prompt *and* generation, so a 32768 window
        # with num_predict 8192 leaves 24576 tokens of prompt space.
        budget = ContextBudget(context_window=32768, reserved_output=8192)
        assert budget.prompt_tokens == 24576

    def test_reservation_at_or_above_the_window_falls_back_to_half(self):
        budget = ContextBudget(context_window=8192, reserved_output=8192)
        assert budget.prompt_tokens == 4096

    def test_negative_reservation_is_ignored(self):
        assert ContextBudget(context_window=4096, reserved_output=-10).prompt_tokens == 4096

    def test_chars_converts_through_the_token_ratio(self):
        budget = ContextBudget(context_window=10_000, reserved_output=2_000)
        assert budget.chars(0.5) == 8_000 * CHARS_PER_TOKEN // 2

    def test_chars_never_returns_below_the_floor(self):
        budget = ContextBudget(context_window=512, reserved_output=0)
        assert budget.chars(0.01, minimum=2_000) == 2_000


class TestClampToContext:
    def test_small_window_lowers_the_configured_ceiling(self):
        # 24576 prompt tokens * 4 chars * 0.25 share = 24576 chars < 50000.
        budget = ContextBudget(context_window=32768, reserved_output=8192)
        assert clamp_to_context(50_000, budget, share=0.25) == 24_576

    def test_large_window_leaves_the_configured_ceiling_alone(self):
        budget = ContextBudget(context_window=200_000, reserved_output=32_000)
        assert clamp_to_context(50_000, budget, share=0.25) == 50_000

    def test_unknown_budget_is_a_no_op(self):
        assert clamp_to_context(50_000, None, share=0.25) == 50_000

    def test_an_explicit_disable_is_never_turned_back_on(self):
        # 0 is the documented "no limit" switch in both the sandbox and
        # tool-output configs. A budget may lower a limit, never impose one the
        # operator deliberately removed.
        budget = ContextBudget(context_window=8_192, reserved_output=2_048)
        assert clamp_to_context(0, budget, share=0.25) == 0
        assert clamp_to_context(0, None, share=0.25) == 0

    def test_never_clamps_below_the_floor(self):
        budget = ContextBudget(context_window=1_024, reserved_output=512)
        assert clamp_to_context(50_000, budget, share=0.1, minimum=2_000) == 2_000


class TestChunkSizing:
    def test_cloud_window_yields_a_bigger_chunk_than_a_local_one(self):
        local = ContextBudget(context_window=32_768, reserved_output=8_192)
        cloud = ContextBudget(context_window=200_000, reserved_output=32_000)
        assert chunk_chars_for(cloud) > chunk_chars_for(local)

    def test_unknown_budget_falls_back_to_the_supplied_default(self):
        assert chunk_chars_for(None, default=12_345) == 12_345

    def test_chunk_is_bounded_by_the_configured_maximum(self):
        cloud = ContextBudget(context_window=1_000_000, reserved_output=32_000)
        assert chunk_chars_for(cloud, maximum=40_000) == 40_000


class TestResolveContextBudget:
    def test_reads_ollama_num_ctx_and_num_predict(self):
        budget = resolve_context_budget(_Model(num_ctx=32768, num_predict=8192))
        assert budget == ContextBudget(context_window=32768, reserved_output=8192)

    def test_reads_context_window_attribute_with_max_tokens_reservation(self):
        budget = resolve_context_budget(_Model(context_window=200_000, max_tokens=32_000))
        assert budget == ContextBudget(context_window=200_000, reserved_output=32_000)

    def test_falls_back_to_the_config_entry_when_the_client_has_no_window(self):
        # Cloud clients never carry context_window: the factory strips it from
        # provider kwargs, so it only exists on the config entry.
        app_config = _AppConfig([_ModelConfigEntry("sonnet", model="claude-sonnet-5", context_window=200_000, max_tokens=32_000)])
        budget = resolve_context_budget(_Model(model="claude-sonnet-5", max_tokens=32_000), app_config=app_config)
        assert budget == ContextBudget(context_window=200_000, reserved_output=32_000)

    def test_matches_a_config_entry_by_its_configured_name(self):
        app_config = _AppConfig([_ModelConfigEntry("qwen3:8b", model="qwen3:8b", context_window=32768)])
        budget = resolve_context_budget(_Model(model="qwen3:8b"), app_config=app_config)
        assert budget is not None
        assert budget.context_window == 32768

    def test_falls_back_to_the_provider_profile_input_limit(self):
        model = _Model(profile={"max_input_tokens": 128_000})
        budget = resolve_context_budget(model)
        assert budget is not None
        assert budget.prompt_tokens == 128_000

    def test_unknown_window_resolves_to_none(self):
        assert resolve_context_budget(_Model(model="mystery"), app_config=_AppConfig([])) is None

    def test_non_numeric_values_are_ignored(self):
        assert resolve_context_budget(_Model(num_ctx="lots", context_window=None), app_config=_AppConfig([])) is None

    def test_zero_and_negative_windows_are_ignored(self):
        assert resolve_context_budget(_Model(num_ctx=0), app_config=_AppConfig([])) is None
        assert resolve_context_budget(_Model(num_ctx=-1), app_config=_AppConfig([])) is None

    def test_a_broken_app_config_never_raises(self):
        class _Exploding:
            @property
            def models(self):
                raise RuntimeError("boom")

        assert resolve_context_budget(_Model(model="x"), app_config=_Exploding()) is None


class TestActiveBudgetContextVar:
    def test_defaults_to_none(self):
        assert active_context_budget() is None

    def test_scope_publishes_and_restores(self):
        budget = ContextBudget(context_window=8_192, reserved_output=1_024)
        with use_context_budget(budget):
            assert active_context_budget() == budget
        assert active_context_budget() is None

    def test_nested_scopes_restore_the_outer_value(self):
        outer = ContextBudget(context_window=8_192, reserved_output=0)
        inner = ContextBudget(context_window=200_000, reserved_output=0)
        with use_context_budget(outer):
            with use_context_budget(inner):
                assert active_context_budget() == inner
            assert active_context_budget() == outer

    def test_scope_restores_on_exception(self):
        budget = ContextBudget(context_window=8_192, reserved_output=0)
        with pytest.raises(ValueError):
            with use_context_budget(budget):
                raise ValueError("boom")
        assert active_context_budget() is None
