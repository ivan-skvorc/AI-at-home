"""Tests for in-run enforcement of currency-denominated spend caps.

Roadmap item 2's in-run half: warn at the warn threshold, force a final answer
at the hard stop, bill lead and subagent tokens at their own model's rate, and
never block a run that costs nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.spend_budget_middleware import (
    SPEND_BUDGET_BASELINE_KEY,
    STOP_REASON,
    SpendBudgetMiddleware,
    price_usage_by_model,
)
from deerflow.config.spend_budget_config import SpendBudgetConfig
from deerflow.pricing import build_pricing_map

# $10/M in, $50/M out on `premium-1`; `cheap-1` at a tenth; `qwen3:8b` unpriced.
MODELS = [
    MagicMock(name="premium", pricing={"currency": "USD", "input_per_million": 10.0, "output_per_million": 50.0}, display_name="Premium"),
    MagicMock(name="cheap", pricing={"currency": "USD", "input_per_million": 1.0, "output_per_million": 5.0}, display_name="Cheap"),
]
MODELS[0].name = "premium"
MODELS[0].model = "premium-1"
MODELS[1].name = "cheap"
MODELS[1].model = "cheap-1"

PRICING = build_pricing_map(MODELS)


def _runtime(baseline: dict | None = None, run_id: str = "run-1"):
    runtime = MagicMock()
    context: dict = {"thread_id": "t1", "run_id": run_id}
    if baseline is not None:
        context[SPEND_BUDGET_BASELINE_KEY] = baseline
    runtime.context = context
    runtime.config = {}
    return runtime


def _baseline(spent: float, limit: float = 10.0, period: str = "daily") -> dict:
    return {"currency": "USD", "limits": [{"period": period, "limit": limit, "spent": spent}]}


def _journal_runtime(usage_by_model: dict, baseline: dict | None = None, run_id: str = "run-1"):
    """A runtime whose callbacks carry a RunJournal-shaped usage accountant."""
    journal = MagicMock()
    journal.current_token_usage_by_model = lambda: usage_by_model
    runtime = _runtime(baseline, run_id)
    runtime.config = {"callbacks": [journal]}
    return runtime


def _ai(content: str = "hi", *, tool_calls=None, model: str | None = "premium-1", input_tokens: int = 0, output_tokens: int = 0) -> AIMessage:
    return AIMessage(
        id="m1",
        content=content,
        tool_calls=tool_calls or [],
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens},
        response_metadata={"model_name": model} if model else {},
    )


def _mw(**kwargs) -> SpendBudgetMiddleware:
    config = SpendBudgetConfig(enabled=True, daily_limit=10, **kwargs)
    return SpendBudgetMiddleware.from_config(config, PRICING)


class TestHardStop:
    def test_reaching_the_limit_strips_tool_calls_and_forces_an_answer(self):
        mw = _mw()
        # Baseline $9.50 + this run's $1 (100k in) = $10.50, over the $10 cap.
        runtime = _journal_runtime({"premium-1": {"input_tokens": 100_000, "output_tokens": 0, "total_tokens": 100_000}}, _baseline(9.5))
        state = {"messages": [_ai(tool_calls=[{"name": "bash", "args": {}, "id": "c1"}])]}

        result = mw._apply(state, runtime)

        assert result is not None
        stopped = result["messages"][0]
        assert stopped.tool_calls == []
        assert "SPEND BUDGET EXCEEDED" in stopped.content
        assert "daily" in stopped.content

    def test_hard_stop_records_a_consumable_stop_reason(self):
        mw = _mw()
        runtime = _journal_runtime({"premium-1": {"input_tokens": 2_000_000, "output_tokens": 0, "total_tokens": 2_000_000}}, _baseline(0.0))
        mw._apply({"messages": [_ai()]}, runtime)
        assert runtime.context["stop_reason"] == STOP_REASON
        assert mw.consume_stop_reason("run-1") == STOP_REASON
        # Popped, so a later read does not double-report.
        assert mw.consume_stop_reason("run-1") is None

    def test_finish_reason_is_normalized_away_from_tool_calls(self):
        mw = _mw()
        message = _ai(tool_calls=[{"name": "bash", "args": {}, "id": "c1"}])
        message.response_metadata = {"model_name": "premium-1", "finish_reason": "tool_calls"}
        runtime = _journal_runtime({"premium-1": {"input_tokens": 2_000_000, "output_tokens": 0, "total_tokens": 2_000_000}}, _baseline(0.0))
        result = mw._apply({"messages": [message]}, runtime)
        assert result["messages"][0].response_metadata["finish_reason"] == "stop"


class TestWarning:
    def test_warning_is_queued_once_and_injected_at_the_next_model_call(self):
        mw = _mw()
        # Baseline $7.50 + $1 = $8.50 → 85% of the $10 cap, past the 0.8 warn.
        runtime = _journal_runtime({"premium-1": {"input_tokens": 100_000, "output_tokens": 0, "total_tokens": 100_000}}, _baseline(7.5))

        assert mw._apply({"messages": [_ai()]}, runtime) is None
        assert mw._apply({"messages": [_ai()]}, runtime) is None  # only warns once

        request = MagicMock()
        request.messages = []
        request.runtime = runtime
        captured: list = []

        def override(messages=None, **_):
            captured.append(messages)
            return request

        request.override = override
        mw.wrap_model_call(request, lambda req: MagicMock())

        assert len(captured) == 1
        assert "SPEND BUDGET WARNING" in captured[0][-1].content
        assert captured[0][-1].name == "spend_budget_warning"

    def test_below_the_warn_threshold_does_nothing(self):
        mw = _mw()
        runtime = _journal_runtime({"premium-1": {"input_tokens": 100_000, "output_tokens": 0, "total_tokens": 100_000}}, _baseline(0.0))
        assert mw._apply({"messages": [_ai()]}, runtime) is None
        assert mw._drain_pending_warnings(runtime) == []


class TestLocalRunsAreNeverBlocked:
    def test_an_unpriced_model_cannot_trip_the_cap(self):
        mw = _mw()
        runtime = _journal_runtime({"qwen3:8b": {"input_tokens": 50_000_000, "output_tokens": 50_000_000, "total_tokens": 100_000_000}}, _baseline(0.0))
        assert mw._apply({"messages": [_ai(model="qwen3:8b")]}, runtime) is None

    def test_a_thread_already_at_the_cap_still_stops_a_local_run(self):
        # The baseline is what the window already cost; a local run adds nothing
        # to it, but if the window is already over the limit the cap still bites.
        # That is admission's job, not this middleware's — here we only assert
        # the local run itself contributes zero.
        mw = _mw()
        runtime = _journal_runtime({"qwen3:8b": {"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000}}, _baseline(9.0))
        assert mw._apply({"messages": [_ai(model="qwen3:8b")]}, runtime) is None


class TestPerModelAttribution:
    def test_a_cheap_subagent_is_billed_at_its_own_rate(self):
        mw = _mw()
        # 100k in on the lead ($1) + 1M in on the cheap subagent ($1) = $2.
        # Billing the subagent at the lead's rate would be $11 and trip the cap.
        runtime = _journal_runtime(
            {
                "premium-1": {"input_tokens": 100_000, "output_tokens": 0, "total_tokens": 100_000},
                "cheap-1": {"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000},
            },
            _baseline(0.0),
        )
        assert mw._apply({"messages": [_ai()]}, runtime) is None
        assert (
            price_usage_by_model(
                {
                    "premium-1": {"input_tokens": 100_000, "output_tokens": 0},
                    "cheap-1": {"input_tokens": 1_000_000, "output_tokens": 0},
                },
                PRICING,
            )
            == 2.0
        )

    def test_cache_hits_are_priced_through_the_shared_formula(self):
        priced = price_usage_by_model({"premium-1": {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 1_000_000}}, PRICING)
        # No cache-hit rate configured → cache reads bill at the miss price.
        assert priced == 10.0

    def test_unknown_models_are_skipped_rather_than_guessed(self):
        assert price_usage_by_model({"never-configured": {"input_tokens": 10_000_000, "output_tokens": 0}}, PRICING) == 0.0


class TestBaselineHandling:
    def test_a_missing_baseline_degrades_to_this_run_only(self):
        # No Gateway (embedded client / TUI): the cap still applies to the run
        # in front of us rather than silently doing nothing.
        mw = _mw()
        runtime = _journal_runtime({"premium-1": {"input_tokens": 2_000_000, "output_tokens": 0, "total_tokens": 2_000_000}})
        result = mw._apply({"messages": [_ai(tool_calls=[{"name": "bash", "args": {}, "id": "c1"}])]}, runtime)
        assert result is not None
        assert result["messages"][0].tool_calls == []

    def test_a_malformed_baseline_degrades_instead_of_disabling_the_cap(self):
        mw = _mw()
        runtime = _journal_runtime(
            {"premium-1": {"input_tokens": 2_000_000, "output_tokens": 0, "total_tokens": 2_000_000}},
            {"limits": ["not-a-dict", {"period": "daily"}]},
        )
        result = mw._apply({"messages": [_ai()]}, runtime)
        assert result is not None  # fell back to the configured limit, still enforced

    def test_the_tightest_configured_window_is_the_one_that_trips(self):
        mw = SpendBudgetMiddleware.from_config(SpendBudgetConfig(enabled=True, daily_limit=100, weekly_limit=10), PRICING)
        baseline = {"currency": "USD", "limits": [{"period": "daily", "limit": 100.0, "spent": 0.0}, {"period": "weekly", "limit": 10.0, "spent": 9.5}]}
        runtime = _journal_runtime({"premium-1": {"input_tokens": 100_000, "output_tokens": 0, "total_tokens": 100_000}}, baseline)
        result = mw._apply({"messages": [_ai()]}, runtime)
        assert "weekly" in result["messages"][0].content


class TestMessageFallback:
    """No RunJournal (embedded client / subagent graph) → price the messages."""

    def test_spend_is_summed_from_message_usage_when_no_journal_is_reachable(self):
        mw = _mw()
        runtime = _runtime(_baseline(9.5))
        runtime.config = {}  # no callbacks at all
        state = {"messages": [_ai(input_tokens=100_000, tool_calls=[{"name": "bash", "args": {}, "id": "c1"}])]}
        result = mw._apply(state, runtime)
        assert result is not None
        assert result["messages"][0].tool_calls == []

    def test_messages_from_an_unpriced_model_contribute_nothing(self):
        mw = _mw()
        runtime = _runtime(_baseline(9.5))
        runtime.config = {}
        state = {"messages": [_ai(model="qwen3:8b", input_tokens=50_000_000)]}
        assert mw._apply(state, runtime) is None


class TestDisabledPaths:
    def test_a_disabled_config_never_acts(self):
        mw = SpendBudgetMiddleware.from_config(SpendBudgetConfig(enabled=False), PRICING)
        runtime = _journal_runtime({"premium-1": {"input_tokens": 10_000_000, "output_tokens": 0, "total_tokens": 10_000_000}}, _baseline(9.9))
        assert mw._apply({"messages": [_ai()]}, runtime) is None

    def test_an_empty_pricing_map_never_acts(self):
        mw = SpendBudgetMiddleware.from_config(SpendBudgetConfig(enabled=True, daily_limit=1), {})
        runtime = _journal_runtime({"premium-1": {"input_tokens": 10_000_000, "output_tokens": 0, "total_tokens": 10_000_000}}, _baseline(0.0))
        assert mw._apply({"messages": [_ai()]}, runtime) is None

    def test_a_non_ai_tail_message_is_ignored(self):
        mw = _mw()
        runtime = _journal_runtime({"premium-1": {"input_tokens": 10_000_000, "output_tokens": 0, "total_tokens": 10_000_000}}, _baseline(0.0))
        assert mw._apply({"messages": []}, runtime) is None

    def test_after_agent_clears_per_run_state_but_keeps_the_stop_reason(self):
        mw = _mw()
        runtime = _journal_runtime({"premium-1": {"input_tokens": 2_000_000, "output_tokens": 0, "total_tokens": 2_000_000}}, _baseline(0.0))
        mw._apply({"messages": [_ai()]}, runtime)
        mw.after_agent({"messages": []}, runtime)
        # The executor consumes the stop reason *after* the run returns.
        assert mw.consume_stop_reason("run-1") == STOP_REASON
