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
    _pricing_lookup_candidates,
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


# --- Provider-reported model id resolution -------------------------------
#
# ``token_usage_by_model`` buckets are keyed by what the *provider* reported
# (``response_metadata.model_name``), which routinely differs from the id in
# ``config.yaml``: Anthropic resolves an undated alias to a dated snapshot,
# OpenRouter appends ``:variant`` tags, and a routed slug carries a
# ``vendor/`` prefix. Without normalization every bucket looks unpriced and the
# thread cost overview renders "—" forever.


def _anthropic_map():
    return build_pricing_map(
        [
            _model("claude-opus-5", "claude-opus-5", {"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            _model("claude-opus-4-8", "claude-opus-4-8", {"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            _model("claude-haiku-4-5", "claude-haiku-4-5", {"currency": "USD", "input_per_million": 1, "output_per_million": 5}),
        ],
    )


def test_lookup_resolves_anthropic_dated_snapshot_id():
    """The reported id is the dated snapshot the API resolved the alias to."""
    pricing = _anthropic_map()
    assert lookup_pricing(pricing, "claude-opus-5-20260115") is lookup_pricing(pricing, "claude-opus-5")
    assert lookup_pricing(pricing, "claude-haiku-4-5-20251001") is lookup_pricing(pricing, "claude-haiku-4-5")


def test_lookup_resolves_openai_style_dashed_date_suffix():
    pricing = build_pricing_map(
        [_model("gpt-5.6-sol", "gpt-5.6-sol", {"currency": "USD", "input_per_million": 2, "output_per_million": 8})],
    )
    assert lookup_pricing(pricing, "gpt-5.6-sol-2026-01-15") is not None


def test_lookup_resolves_vertex_style_at_date_suffix():
    pricing = _anthropic_map()
    assert lookup_pricing(pricing, "claude-opus-5@20260115") is not None


def test_lookup_resolves_openrouter_variant_suffix():
    pricing = build_pricing_map(
        [_model("openrouter-glm-5.2", "z-ai/glm-5.2", {"currency": "USD", "input_per_million": 1.15, "output_per_million": 3.6})],
    )
    assert lookup_pricing(pricing, "z-ai/glm-5.2:free") is not None
    assert lookup_pricing(pricing, "z-ai/glm-5.2:nitro") is not None


def test_lookup_resolves_routed_slug_against_a_direct_home_entry():
    """Only the direct entry is configured; a vendor-prefixed report still prices."""
    pricing = _anthropic_map()
    assert lookup_pricing(pricing, "anthropic/claude-opus-5") is not None
    assert lookup_pricing(pricing, "anthropic/claude-opus-5-20260115") is not None


def test_exact_routed_entry_wins_over_the_prefix_stripped_direct_entry():
    """A configured OpenRouter copy must be billed at its own (routed) price."""
    pricing = build_pricing_map(
        [
            _model("claude-opus-5", "claude-opus-5", {"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            _model("openrouter-claude-opus-5", "anthropic/claude-opus-5", {"currency": "USD", "input_per_million": 6, "output_per_million": 30}),
        ],
    )
    routed = lookup_pricing(pricing, "anthropic/claude-opus-5")
    assert routed is not None and routed.input_per_million == 6
    direct = lookup_pricing(pricing, "claude-opus-5")
    assert direct is not None and direct.input_per_million == 5
    # A dated routed report still prefers the routed entry over the direct one.
    dated_routed = lookup_pricing(pricing, "anthropic/claude-opus-5-20260115")
    assert dated_routed is not None and dated_routed.input_per_million == 6


def test_lookup_does_not_confuse_sibling_models_sharing_a_prefix():
    """``claude-opus-4-8`` must never be billed at ``claude-opus-5``'s rate."""
    pricing = _anthropic_map()
    opus48 = lookup_pricing(pricing, "claude-opus-4-8-20260101")
    haiku = lookup_pricing(pricing, "claude-haiku-4-5-20251001")
    assert opus48 is not None and haiku is not None
    assert opus48.output_per_million == 25
    assert haiku.output_per_million == 5


def test_lookup_never_invents_a_price_for_an_unconfigured_model():
    """A local Ollama tag (or any unknown id) still resolves to None."""
    pricing = _anthropic_map()
    assert lookup_pricing(pricing, "qwen3:8b") is None
    assert lookup_pricing(pricing, "unknown") is None
    # A partial/sibling id whose suffix is not a version stamp is NOT a match.
    assert lookup_pricing(pricing, "claude-opus-5-turbo") is None


def test_lookup_candidates_are_ordered_most_specific_first():
    candidates = _pricing_lookup_candidates("Anthropic/Claude-Opus-5-20260115")
    assert candidates[0] == "Anthropic/Claude-Opus-5-20260115"
    # The bare, undated form is the least specific and therefore tried last.
    assert candidates.index("claude-opus-5") > candidates.index("anthropic/claude-opus-5")


def test_run_cost_prices_provider_reported_ids_across_a_model_switch():
    """The lever this fork exposes: turns on different models, priced per model."""
    pricing = _anthropic_map()
    cost = run_cost(
        pricing,
        model_name="claude-opus-5",
        total_input_tokens=0,
        total_output_tokens=0,
        token_usage_by_model={
            "claude-opus-5-20260115": {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "total_tokens": 2_000_000},
            "claude-haiku-4-5-20251001": {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "total_tokens": 2_000_000},
        },
    )
    # opus: 5 + 25 = 30 ; haiku: 1 + 5 = 6 ; total 36.
    assert cost == pytest.approx(36.0)


def test_same_currency_case_insensitive_does_not_trip_guard():
    pricing = build_pricing_map(
        [
            _model("a", "model-a", {"currency": "USD", "input_per_million": 1, "output_per_million": 4}),
            _model("b", "model-b", {"currency": "usd", "input_per_million": 2, "output_per_million": 8}),
        ],
    )
    assert pricing_currency(pricing) == "USD"
    assert lookup_pricing(pricing, "model-b") is not None
