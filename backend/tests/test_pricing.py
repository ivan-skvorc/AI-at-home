"""Unit tests for the shared model-pricing helpers (``app.gateway.pricing``).

These pin the cost math the chat sidebar's cost overview and the ops console
both rely on: per-million pricing, cache-hit accounting, the multi-model
(subagent) run cost, unpriced-model handling, and the one-currency rule.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.gateway.pricing import (
    build_pricing_map,
    lookup_pricing,
    pricing_currency,
    run_cost,
    token_cost,
)


def _model(name, model, pricing):
    return SimpleNamespace(name=name, model=model, pricing=pricing)


def test_build_pricing_map_keys_by_name_and_model_and_lowercase():
    pricing = build_pricing_map(
        [
            _model("Opus", "claude-opus", {"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
        ],
    )
    assert lookup_pricing(pricing, "Opus") is not None
    assert lookup_pricing(pricing, "opus") is not None
    assert lookup_pricing(pricing, "claude-opus") is not None
    assert lookup_pricing(pricing, "CLAUDE-OPUS") is not None
    assert lookup_pricing(pricing, "nope") is None
    assert pricing_currency(pricing) == "USD"


def test_unpriced_and_zero_priced_models_are_skipped():
    pricing = build_pricing_map(
        [
            _model("free", "local-ollama", None),
            _model("zero", "zero-model", {"currency": "USD", "input_per_million": 0, "output_per_million": 0}),
            _model("paid", "paid-model", {"currency": "USD", "input_per_million": 1, "output_per_million": 4}),
        ],
    )
    assert lookup_pricing(pricing, "local-ollama") is None
    assert lookup_pricing(pricing, "zero-model") is None
    assert lookup_pricing(pricing, "paid-model") is not None


def test_empty_map_currency_and_lookup():
    assert pricing_currency({}) is None
    assert lookup_pricing({}, "anything") is None
    assert lookup_pricing({"x": object()}, None) is None


def test_token_cost_basic():
    pricing = build_pricing_map([_model("m", "m", {"currency": "USD", "input_per_million": 5, "output_per_million": 25})])
    price = lookup_pricing(pricing, "m")
    # 1M input @ $5 + 1M output @ $25 = $30.
    assert token_cost(1_000_000, 1_000_000, price) == pytest.approx(30.0)
    # 200k input @ $5 + 100k output @ $25 = $1 + $2.5 = $3.5.
    assert token_cost(200_000, 100_000, price) == pytest.approx(3.5)


def test_token_cost_cache_hits_billed_at_hit_price():
    pricing = build_pricing_map(
        [_model("m", "m", {"currency": "USD", "input_per_million": 10, "output_per_million": 20, "input_cache_hit_per_million": 1})],
    )
    price = lookup_pricing(pricing, "m")
    # 1000 input of which 800 are cache hits: 200 @ $10/M + 800 @ $1/M + 500 out @ $20/M.
    expected = 200 * 10e-6 + 800 * 1e-6 + 500 * 20e-6
    assert token_cost(1000, 500, price, cache_read_tokens=800) == pytest.approx(expected)


def test_token_cost_cache_hits_billed_at_miss_price_without_hit_price():
    pricing = build_pricing_map([_model("m", "m", {"currency": "USD", "input_per_million": 10, "output_per_million": 20})])
    price = lookup_pricing(pricing, "m")
    # No hit price configured → all input billed at the miss price (conservative).
    expected = 1000 * 10e-6 + 500 * 20e-6
    assert token_cost(1000, 500, price, cache_read_tokens=800) == pytest.approx(expected)


def test_token_cost_clamps_cache_read_into_range():
    pricing = build_pricing_map(
        [_model("m", "m", {"currency": "USD", "input_per_million": 10, "output_per_million": 20, "input_cache_hit_per_million": 1})],
    )
    price = lookup_pricing(pricing, "m")
    # cache_read > input is clamped to input; a negative value clamps to 0.
    assert token_cost(1000, 0, price, cache_read_tokens=5000) == pytest.approx(1000 * 1e-6)
    assert token_cost(1000, 0, price, cache_read_tokens=-5) == pytest.approx(1000 * 10e-6)


def test_run_cost_prefers_per_model_breakdown_including_subagent():
    """A run with a cheap subagent model must be priced per model, not lumped."""
    pricing = build_pricing_map(
        [
            _model("lead", "lead-model", {"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            _model("sub", "sub-model", {"currency": "USD", "input_per_million": 1, "output_per_million": 4}),
        ],
    )
    cost = run_cost(
        pricing,
        model_name="lead-model",
        total_input_tokens=999,
        total_output_tokens=999,
        token_usage_by_model={
            "lead-model": {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "total_tokens": 2_000_000},
            "sub-model": {"input_tokens": 2_000_000, "output_tokens": 1_000_000, "total_tokens": 3_000_000},
        },
    )
    # lead: 5 + 25 = 30 ; sub: 2*1 + 1*4 = 6 ; total 36.
    assert cost == pytest.approx(36.0)


def test_run_cost_falls_back_to_run_totals_for_legacy_rows():
    pricing = build_pricing_map([_model("lead", "lead-model", {"currency": "USD", "input_per_million": 5, "output_per_million": 25})])
    cost = run_cost(
        pricing,
        model_name="lead-model",
        total_input_tokens=1_000_000,
        total_output_tokens=1_000_000,
        token_usage_by_model={},
    )
    assert cost == pytest.approx(30.0)


def test_run_cost_none_when_no_priced_model():
    pricing = build_pricing_map([_model("lead", "lead-model", {"currency": "USD", "input_per_million": 5, "output_per_million": 25})])
    assert run_cost(pricing, model_name="other", total_input_tokens=10, total_output_tokens=10, token_usage_by_model={}) is None
    assert run_cost(pricing, model_name=None, total_input_tokens=0, total_output_tokens=0, token_usage_by_model={"unpriced": {"input_tokens": 5, "output_tokens": 5}}) is None


def test_mixed_currencies_disable_pricing_with_warning(caplog):
    logger = logging.getLogger("pricing-test")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        pricing = build_pricing_map(
            [
                _model("model-a", "prov-a", {"currency": "USD", "input_per_million": 1, "output_per_million": 4}),
                _model("model-b", "prov-b", {"currency": "CNY", "input_per_million": 8, "output_per_million": 32}),
            ],
            logger=logger,
        )
    assert pricing == {}
    # The warning names both offending models (by config name) so operators can locate the misconfig.
    assert any("model-a" in rec.getMessage() and "model-b" in rec.getMessage() for rec in caplog.records)


def test_same_currency_case_insensitive_does_not_trip_guard():
    pricing = build_pricing_map(
        [
            _model("a", "model-a", {"currency": "USD", "input_per_million": 1, "output_per_million": 4}),
            _model("b", "model-b", {"currency": "usd", "input_per_million": 2, "output_per_million": 8}),
        ],
    )
    assert pricing_currency(pricing) == "USD"
    assert lookup_pricing(pricing, "model-b") is not None
