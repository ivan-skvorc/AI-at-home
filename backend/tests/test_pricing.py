"""Unit tests for the shared model-pricing helpers (``app.gateway.pricing``).

These pin the cost math the chat sidebar's cost overview and the ops console
both rely on: per-million pricing, cache-hit accounting, the multi-model
(subagent) run cost, unpriced-model handling, and the one-currency rule.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from deerflow.pricing import (
    _pricing_lookup_candidates,
    build_pricing_map,
    lookup_pricing,
    pricing_currency,
    run_cost,
    token_cost,
)


def test_gateway_shim_re_exports_the_canonical_helpers():
    """``app.gateway.pricing`` is a re-export of ``deerflow.pricing``.

    The math lives in the harness so the in-graph spend-budget middleware can
    price tokens without importing ``app.*``. Gateway routers still import the
    old path, so the shim must keep exporting the same objects — one
    implementation, two import paths.
    """
    import app.gateway.pricing as shim
    import deerflow.pricing as canonical

    for name in ("ModelPricing", "build_pricing_map", "derive_pricing_from_display_name", "lookup_pricing", "pricing_currency", "run_cost", "token_cost"):
        assert getattr(shim, name) is getattr(canonical, name), name


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


def test_lookup_prices_a_model_id_that_stream_merging_duplicated():
    """A doubled id still prices — historical rows already carry the corrupt key.

    ``merge_dicts`` concatenates the ``model_name`` of two stream chunks that
    both carry a ``finish_reason``, and every run persisted before that was
    fixed at the source stored the doubled id in ``token_usage_by_model``.
    Reopening one of those threads must still show its cost.
    """
    pricing = build_pricing_map(
        [_model("openrouter-deepseek-v4-pro", "deepseek/deepseek-v4-pro", {"currency": "USD", "input_per_million": 0.44, "output_per_million": 0.87})],
    )
    doubled = lookup_pricing(pricing, "deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro")
    assert doubled is not None and doubled.output_per_million == 0.87
    # The collapsed form is tried after the exact one, so a (hypothetical)
    # configured entry for the doubled id itself would still win.
    candidates = _pricing_lookup_candidates("deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro")
    assert candidates[0] == "deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro"
    # Peeling the vendor prefix is applied to the collapsed form too, so a
    # direct DeepSeek entry would price an OpenRouter-routed doubled report.
    assert "deepseek-v4-pro" in candidates


def test_lookup_does_not_price_two_different_ids_that_were_concatenated():
    """Only an exact repetition collapses; a mismatched pair stays unpriced."""
    pricing = _anthropic_map()
    assert lookup_pricing(pricing, "claude-opus-5claude-haiku-4-5") is None


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


class TestPromoPricing:
    """Optional promotional / introductory rates alongside the standard price.

    A provider discount is temporary, so the standard rate stays what cost
    reporting bills against; the promo is additive and lets the UI show what the
    conversation costs *right now* beside what it costs once the promo ends.
    A half-specified or above-list promo is a config error and is dropped whole
    rather than partially honoured — silently billing an invalid promo would
    under-report spend.
    """

    @staticmethod
    def _priced(promo: dict) -> object:
        return _model("m", "model-m", {"currency": "USD", "input_per_million": 1.0, "output_per_million": 4.0, **promo})

    def test_promo_rates_are_exposed_as_a_standalone_price(self):
        pricing = build_pricing_map([self._priced({"promo_input_per_million": 0.25, "promo_output_per_million": 1.0})])
        price = lookup_pricing(pricing, "model-m")
        assert price is not None
        assert price.input_per_million == 1.0
        assert price.output_per_million == 4.0
        promo = price.promo()
        assert promo is not None
        assert (promo.input_per_million, promo.output_per_million, promo.currency) == (0.25, 1.0, "USD")

    def test_promo_cost_uses_the_discounted_rate(self):
        pricing = build_pricing_map([self._priced({"promo_input_per_million": 0.25, "promo_output_per_million": 1.0})])
        price = lookup_pricing(pricing, "model-m")
        assert token_cost(1_000_000, 1_000_000, price) == pytest.approx(5.0)
        assert token_cost(1_000_000, 1_000_000, price.promo()) == pytest.approx(1.25)

    def test_promo_cache_hit_price_is_carried_through(self):
        pricing = build_pricing_map(
            [
                self._priced(
                    {
                        "promo_input_per_million": 0.5,
                        "promo_output_per_million": 2.0,
                        "promo_input_cache_hit_per_million": 0.05,
                    }
                )
            ]
        )
        promo = lookup_pricing(pricing, "model-m").promo()
        # 1M input all cache-read at 0.05 + 1M output at 2.0
        assert token_cost(1_000_000, 1_000_000, promo, cache_read_tokens=1_000_000) == pytest.approx(2.05)

    def test_no_promo_configured_returns_none(self):
        pricing = build_pricing_map([self._priced({})])
        assert lookup_pricing(pricing, "model-m").promo() is None

    @pytest.mark.parametrize(
        "promo",
        [
            pytest.param({"promo_input_per_million": 0.25}, id="output-missing"),
            pytest.param({"promo_output_per_million": 1.0}, id="input-missing"),
            pytest.param({"promo_input_per_million": "cheap", "promo_output_per_million": 1.0}, id="malformed"),
            pytest.param({"promo_input_per_million": 0, "promo_output_per_million": 1.0}, id="zero-input"),
            pytest.param({"promo_input_per_million": -1.0, "promo_output_per_million": 1.0}, id="negative-input"),
            pytest.param({"promo_input_per_million": 2.0, "promo_output_per_million": 1.0}, id="input-above-list"),
            pytest.param({"promo_input_per_million": 0.25, "promo_output_per_million": 9.0}, id="output-above-list"),
        ],
    )
    def test_invalid_promo_is_dropped_whole_and_standard_price_survives(self, promo, caplog):
        with caplog.at_level(logging.WARNING, logger="app.gateway.pricing"):
            pricing = build_pricing_map([self._priced(promo)])
        price = lookup_pricing(pricing, "model-m")
        assert price is not None, "an invalid promo must not disable the model's standard price"
        assert (price.input_per_million, price.output_per_million) == (1.0, 4.0)
        assert price.promo() is None
        assert any("promo" in record.getMessage() for record in caplog.records)

    def test_promo_equal_to_list_price_is_accepted(self):
        # Not useful, but not invalid — only an *above-list* "promo" is a config error.
        pricing = build_pricing_map([self._priced({"promo_input_per_million": 1.0, "promo_output_per_million": 4.0})])
        assert lookup_pricing(pricing, "model-m").promo() is not None

    def test_invalid_promo_cache_hit_drops_only_the_cache_hit_rate(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.gateway.pricing"):
            pricing = build_pricing_map(
                [
                    self._priced(
                        {
                            "promo_input_per_million": 0.5,
                            "promo_output_per_million": 2.0,
                            "promo_input_cache_hit_per_million": 5.0,
                        }
                    )
                ]
            )
        promo = lookup_pricing(pricing, "model-m").promo()
        assert promo is not None
        # Falls back to the promo miss price, the same conservative rule the
        # standard block uses when no cache-hit price is configured.
        assert promo.input_cache_hit_per_million is None
        assert token_cost(1_000_000, 0, promo, cache_read_tokens=1_000_000) == pytest.approx(0.5)

    def test_run_cost_still_bills_the_standard_rate(self):
        pricing = build_pricing_map([self._priced({"promo_input_per_million": 0.25, "promo_output_per_million": 1.0})])
        cost = run_cost(
            pricing,
            model_name="model-m",
            total_input_tokens=0,
            total_output_tokens=0,
            token_usage_by_model={"model-m": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}},
        )
        assert cost == pytest.approx(5.0)


class TestPricingDerivedFromDisplayName:
    """A model with no ``pricing:`` block is priced from its display name.

    This is what makes the feature work for an **existing** install. Shipping
    `pricing:` blocks in `config.example.yaml` only ever reaches a *fresh*
    `config.yaml`: `sync-api-key-models.py` skips a block whose models are
    already active (correct — it must not duplicate them), and
    `config_upgrade.py`'s `merge_missing` is dict-based so it cannot add a key
    inside an existing list entry. So every user who ran DeerFlow before the
    blocks were added keeps active, unpriced models forever and the chat header
    stays on `—`.

    The price is not actually missing from those configs — it is right there in
    `display_name` (`Grok 4.5 ($2/6) (OpenRouter) (p)`), which is the same pair
    the shipped `pricing:` blocks are generated from. Deriving from it makes the
    redundant block optional rather than load-bearing.
    """

    @staticmethod
    def _named(display_name: str) -> object:
        # No `pricing` attribute at all — the shape of a pre-fix config entry.
        return SimpleNamespace(name="m", model="model-m", pricing=None, display_name=display_name)

    def test_unpriced_model_is_priced_from_its_display_name(self):
        pricing = build_pricing_map([self._named("Grok 4.5 ($2/6) (OpenRouter) (p)")])
        price = lookup_pricing(pricing, "model-m")
        assert price is not None
        assert (price.input_per_million, price.output_per_million, price.currency) == (2.0, 6.0, "USD")
        assert token_cost(1_000_000, 1_000_000, price) == pytest.approx(8.0)

    def test_derived_price_carries_the_promo_pair(self):
        pricing = build_pricing_map([self._named("GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)")])
        price = lookup_pricing(pricing, "model-m")
        assert (price.input_per_million, price.output_per_million) == (1.15, 3.6)
        promo = price.promo()
        assert promo is not None
        assert (promo.input_per_million, promo.output_per_million) == (0.28, 0.87)

    def test_derived_anthropic_price_includes_the_cache_hit_rate(self):
        # Anthropic publishes cache reads at 0.1x input; the same rule the
        # generated blocks use, so derived and shipped prices agree.
        pricing = build_pricing_map([self._named("Claude Opus 4.8 ($5/25) (Anthropic)")])
        price = lookup_pricing(pricing, "model-m")
        assert price.input_cache_hit_per_million == pytest.approx(0.5)

    def test_derived_non_anthropic_price_omits_the_cache_hit_rate(self):
        pricing = build_pricing_map([self._named("Grok 4.5 ($2/6) (OpenRouter) (p)")])
        assert lookup_pricing(pricing, "model-m").input_cache_hit_per_million is None

    def test_an_explicit_pricing_block_always_wins(self):
        # An operator who hand-wrote a price (a negotiated rate, a corrected
        # figure) must never have it silently replaced by the name's.
        model = SimpleNamespace(
            name="m",
            model="model-m",
            pricing={"currency": "USD", "input_per_million": 9.0, "output_per_million": 9.0},
            display_name="Grok 4.5 ($2/6) (OpenRouter) (p)",
        )
        price = lookup_pricing(build_pricing_map([model]), "model-m")
        assert (price.input_per_million, price.output_per_million) == (9.0, 9.0)

    def test_a_name_with_no_price_stays_unpriced(self):
        # Local Ollama and hand-added models must not be invented a price.
        for name in ["qwen3:32b (Ollama)", "Doubao-Seed-1.8", "", "Gemini 3.6 Flash"]:
            assert build_pricing_map([self._named(name)]) == {}, name

    def test_a_missing_display_name_attribute_is_tolerated(self):
        # Ollama entries are generated at runtime and may carry no display_name.
        assert build_pricing_map([SimpleNamespace(name="m", model="model-m", pricing=None)]) == {}

    def test_malformed_pricing_block_does_not_fall_back_to_the_name(self):
        # A broken explicit block is an operator error worth surfacing, not
        # something to paper over with a different number.
        model = SimpleNamespace(
            name="m",
            model="model-m",
            pricing={"currency": "USD", "input_per_million": "free", "output_per_million": 9.0},
            display_name="Grok 4.5 ($2/6) (OpenRouter) (p)",
        )
        assert build_pricing_map([model]) == {}

    def test_derived_and_shipped_prices_agree_for_every_bundled_model(self):
        """Derivation is now a *legacy* path, and must keep working as one.

        Bundled models no longer carry a price in `display_name` — the price is
        data in `price:`, and the wizard no longer derives one from the name.
        But a `config.yaml` written before that change still has the old names,
        and `config_upgrade.py` cannot add a key inside an existing list entry,
        so those installs are priced by this parser and nothing else. Removing
        it would silently un-price every pre-existing install.

        These are the exact name shapes the fork used to ship.
        """
        cases = {
            "Claude Opus 4.8 ($5/25) (Anthropic)": (5.0, 25.0, None),
            "Claude Sonnet 5 ($3/15 → $2/10*) (Anthropic)": (3.0, 15.0, (2.0, 10.0)),
            "GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)": (1.15, 3.6, (0.28, 0.87)),
            "MiniMax M3 ($0.6/2.4 → $0.24/0.96*) (OpenRouter) (p)": (0.6, 2.4, (0.24, 0.96)),
            "Grok 4.5 ($2/6) (OpenRouter) (p)": (2.0, 6.0, None),
            "GPT-5.6 Sol ($1.25/10) (OpenAI)": (1.25, 10.0, None),
        }
        for display_name, (want_in, want_out, want_promo) in cases.items():
            price = lookup_pricing(build_pricing_map([self._named(display_name)]), "model-m")
            assert price is not None, display_name
            assert price.input_per_million == pytest.approx(want_in), display_name
            assert price.output_per_million == pytest.approx(want_out), display_name
            promo = price.promo()
            if want_promo is None:
                assert promo is None, display_name
            else:
                assert promo is not None, display_name
                assert (promo.input_per_million, promo.output_per_million) == pytest.approx(want_promo), display_name

    def test_the_wizard_no_longer_derives_a_price_from_a_name(self):
        """The bundle's price is data, not a string to be re-parsed.

        Keeping a second derivation in the wizard is what allowed the name and
        the billed figure to drift apart, so its absence is the property worth
        pinning — not an implementation detail.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo_root / "scripts"))
        try:
            from wizard import providers
        finally:
            sys.path.pop(0)

        assert not hasattr(providers, "pricing_for_display_name")
        assert providers.MODEL_PRICES, "the wizard must ship an explicit price table"
