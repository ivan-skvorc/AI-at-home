"""Tests for the explicit `price:` / `discount:` model fields (with expiry).

Why these exist at all: the fork's cost display was driven by two implicit
sources — a `pricing:` block, and failing that, a `($in/out)` pair parsed out of
`display_name`. Both work, but neither is a field an operator can *see* and set,
which is how a model ends up silently unpriced and the chat header renders "—"
with no explanation. `price:` and `discount:` are the explicit surface.

The behaviours worth pinning are the ones that are silent when wrong:

- an **expired** discount must stop being applied on its own, because the whole
  point of the field is that nobody has to remember to delete it. FORK.md names
  the failure directly: an expired promo leaves the header advertising a
  discount nobody is getting;
- an **unknown current date** must drop the discount rather than keep it. Over
  -stating cost is recoverable; claiming a phantom discount is the bug;
- a **malformed** expiry must not silently mean "never expires";
- and the legacy `pricing:` block plus display-name derivation must keep
  working, because existing installs are full of both.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace

from deerflow.pricing import build_pricing_map, lookup_pricing, parse_discount_expiry, token_cost

NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)


def _model(name: str, model: str | None = None, **fields):
    return SimpleNamespace(name=name, model=model or name, display_name=fields.pop("display_name", None), **fields)


def _price(**over):
    base = {"currency": "USD", "input": 3.0, "output": 15.0}
    base.update(over)
    return base


class TestExplicitPriceField:
    def test_price_field_is_used(self):
        pricing = build_pricing_map([_model("m", price=_price())], now=NOW)
        entry = lookup_pricing(pricing, "m")
        assert entry is not None
        assert (entry.input_per_million, entry.output_per_million, entry.currency) == (3.0, 15.0, "USD")

    def test_cache_hit_is_optional_and_honoured(self):
        pricing = build_pricing_map([_model("m", price=_price(cache_hit=0.3))], now=NOW)
        entry = lookup_pricing(pricing, "m")
        # 1M cache-read tokens at the hit price rather than the miss price.
        assert token_cost(1_000_000, 0, entry, cache_read_tokens=1_000_000) == 0.3

    def test_currency_defaults_to_usd(self):
        pricing = build_pricing_map([_model("m", price={"input": 1.0, "output": 2.0})], now=NOW)
        assert lookup_pricing(pricing, "m").currency == "USD"

    def test_price_wins_over_a_legacy_pricing_block(self):
        # An operator who writes the explicit field means it; the legacy block is
        # the thing being migrated away from.
        cfg = _model("m", price=_price(input=1.0), pricing={"currency": "USD", "input_per_million": 99.0, "output_per_million": 99.0})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").input_per_million == 1.0

    def test_price_wins_over_the_display_name(self):
        cfg = _model("m", display_name="M ($99/99)", price=_price(input=2.0))
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").input_per_million == 2.0

    def test_a_malformed_price_is_ignored_rather_than_guessed(self):
        cfg = _model("m", price={"currency": "USD", "input": "not-a-number", "output": 15.0})
        assert build_pricing_map([cfg], now=NOW) == {}

    def test_a_zero_price_is_not_a_price(self):
        # A local model priced at 0 must stay *unpriced*, not "free", or it would
        # silently vanish from the unpriced-models warning.
        assert build_pricing_map([_model("m", price={"input": 0, "output": 0})], now=NOW) == {}


class TestExplicitDiscountField:
    def test_discount_is_exposed_as_a_promo_price(self):
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5})
        entry = lookup_pricing(build_pricing_map([cfg], now=NOW), "m")
        promo = entry.promo()
        assert promo is not None
        assert (promo.input_per_million, promo.output_per_million) == (1.5, 7.5)

    def test_the_standard_rate_is_still_what_is_billed(self):
        # The discount is additive: `token_cost` against the entry itself must
        # keep using the standard rate, so an estimate can never come in under
        # what the provider actually charges.
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5})
        entry = lookup_pricing(build_pricing_map([cfg], now=NOW), "m")
        assert token_cost(1_000_000, 0, entry) == 3.0

    def test_a_discount_above_the_standard_rate_is_refused(self):
        cfg = _model("m", price=_price(), discount={"input": 99.0, "output": 99.0})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is None

    def test_a_half_specified_discount_is_refused_whole(self):
        cfg = _model("m", price=_price(), discount={"input": 1.5})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is None


class TestDiscountExpiry:
    def test_a_future_expiry_keeps_the_discount(self):
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": "2026-12-31"})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is not None

    def test_a_past_expiry_drops_the_discount_by_itself(self):
        # The entire reason the field exists: nobody has to remember to delete it.
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": "2026-01-01"})
        entry = lookup_pricing(build_pricing_map([cfg], now=NOW), "m")
        assert entry.promo() is None
        assert entry.input_per_million == 3.0  # standard price survives

    def test_an_absent_expiry_never_expires(self):
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is not None

    def test_the_expiry_day_is_inclusive(self):
        # "until: 2026-08-16" reads as "through the 16th", not "until it starts".
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": "2026-08-16"})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is not None

    def test_a_yaml_date_object_is_accepted(self):
        # PyYAML parses a bare `until: 2026-12-31` into a `date`, not a string,
        # so the string path alone would reject the most natural spelling.
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": date(2026, 12, 31)})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is not None

    def test_a_yaml_datetime_object_is_accepted(self):
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": datetime(2026, 12, 31, 10, 0)})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is not None

    def test_a_timezone_aware_expiry_is_compared_correctly(self):
        just_past = NOW.astimezone(timezone(timedelta(hours=-8))) - timedelta(hours=1)
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": just_past.isoformat()})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is None

    def test_the_expiry_is_reported_for_display(self):
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": "2026-12-31"})
        entry = lookup_pricing(build_pricing_map([cfg], now=NOW), "m")
        assert entry.discount_until is not None
        assert entry.discount_until.year == 2026

    def test_an_unknown_current_time_drops_the_discount(self):
        """Fail closed when the clock is unavailable.

        Over-stating cost is recoverable by looking at the provider's bill.
        Advertising a discount that may have lapsed is the exact failure this
        field exists to prevent, so "I don't know what time it is" must not
        resolve to "the discount is still on".
        """
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": "2026-12-31"})
        entry = lookup_pricing(build_pricing_map([cfg], now=None), "m")
        assert entry is not None  # the standard price is unaffected
        assert entry.input_per_million == 3.0
        assert entry.promo() is None

    def test_an_unknown_current_time_keeps_a_discount_that_cannot_expire(self):
        # With no `until`, there is nothing a clock could tell us -- dropping it
        # would punish the common case for a problem it does not have.
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5})
        assert lookup_pricing(build_pricing_map([cfg], now=None), "m").promo() is not None

    def test_a_malformed_expiry_drops_the_discount(self):
        # "never expires" is the one meaning an unparseable date must not take.
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": "next tuesday"})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is None

    def test_a_malformed_expiry_is_logged(self, caplog):
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": "31/12/2026"})
        with caplog.at_level(logging.WARNING):
            build_pricing_map([cfg], now=NOW, logger=logging.getLogger("t"))
        assert any("expiry" in r.message.lower() or "until" in r.message.lower() for r in caplog.records)

    def test_a_legacy_promo_block_can_carry_an_expiry_too(self):
        # Existing configs use `pricing.promo_*`; they get expiry for free rather
        # than having to migrate to reach it.
        cfg = _model(
            "m",
            pricing={
                "currency": "USD",
                "input_per_million": 3.0,
                "output_per_million": 15.0,
                "promo_input_per_million": 1.5,
                "promo_output_per_million": 7.5,
                "promo_until": "2026-01-01",
            },
        )
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").promo() is None


class TestParseDiscountExpiry:
    def test_none_means_no_expiry_and_is_valid(self):
        assert parse_discount_expiry(None) == (None, True)

    def test_a_date_becomes_end_of_that_day_utc(self):
        expiry, ok = parse_discount_expiry("2026-08-31")
        assert ok
        assert (expiry.year, expiry.month, expiry.day, expiry.hour) == (2026, 8, 31, 23)
        assert expiry.tzinfo is not None

    def test_a_naive_datetime_is_read_as_utc(self):
        expiry, ok = parse_discount_expiry("2026-08-31T10:00:00")
        assert ok and expiry.tzinfo == UTC

    def test_a_trailing_z_is_accepted(self):
        expiry, ok = parse_discount_expiry("2026-08-31T10:00:00Z")
        assert ok and expiry.tzinfo is not None

    def test_garbage_is_invalid_rather_than_never_expiring(self):
        for value in ("next tuesday", "", "  ", 12345, [], {}):
            expiry, ok = parse_discount_expiry(value)
            assert (expiry, ok) == (None, False), value


class TestNeverReachesTheProvider:
    """`ModelConfig` is `extra="allow"`, so a field the factory does not exclude
    is forwarded straight into the provider client's constructor and from there
    into the completion request payload. `pricing` and `fallback` are already
    excluded for exactly this reason; `price` and `discount` must be too, or a
    cost annotation becomes a malformed API request.
    """

    def test_price_and_discount_are_excluded_from_provider_kwargs(self):
        from deerflow.models import factory

        excluded = None
        for name in ("price", "discount"):
            # The exclude set is built inline in create_chat_model; assert against
            # the source of truth rather than re-deriving it here.
            source = factory.__file__
            with open(source, encoding="utf-8") as handle:
                text = handle.read()
            assert f'"{name}",' in text, f"{name} must be in the factory exclude set"
            excluded = True
        assert excluded

    def test_a_model_config_accepts_the_fields_without_extra_passthrough(self):
        from deerflow.config.model_config import ModelConfig

        cfg = ModelConfig(
            use="langchain_openai:ChatOpenAI",
            name="m",
            model="m",
            price={"currency": "USD", "input": 1.0, "output": 2.0},
            discount={"input": 0.5, "output": 1.0, "until": "2099-01-01"},
        )
        assert cfg.price is not None and cfg.discount is not None
        # Declared fields, not `extra` — so they are typed, documented, and
        # visible to anything that introspects the model.
        assert "price" not in (cfg.model_extra or {})
        assert "discount" not in (cfg.model_extra or {})


class TestBackwardCompatibility:
    def test_a_legacy_pricing_block_still_prices(self):
        cfg = _model("m", pricing={"currency": "USD", "input_per_million": 3.0, "output_per_million": 15.0})
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").input_per_million == 3.0

    def test_display_name_derivation_still_works(self):
        cfg = _model("m", display_name="M ($3/15)")
        assert lookup_pricing(build_pricing_map([cfg], now=NOW), "m").input_per_million == 3.0

    def test_build_pricing_map_still_works_without_a_now_argument(self):
        # Every existing caller passes only `models`; they must keep working and
        # must not silently lose a discount for want of a clock.
        cfg = _model("m", price=_price(), discount={"input": 1.5, "output": 7.5, "until": "2099-12-31"})
        assert lookup_pricing(build_pricing_map([cfg]), "m").promo() is not None
