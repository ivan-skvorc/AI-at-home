"""Shared model-pricing helpers — real spend estimation from config.

Both the operations console (``routers/console.py``, cross-thread reporting)
and the per-thread token-usage endpoint (``routers/thread_runs.py``, the chat
sidebar cost overview) price runs the same way, so the pricing logic lives here
once instead of being copied. Prices come from the optional
``models[*].pricing`` block in ``config.yaml``:

.. code-block:: yaml

    models:
      - name: Claude Opus 4.8 ($5/25) (Anthropic)
        model: claude-opus-4-8
        pricing:
          currency: USD
          input_per_million: 5.0
          output_per_million: 25.0
          input_cache_hit_per_million: 0.5   # optional
          promo_input_per_million: 2.5       # optional; a live discount
          promo_output_per_million: 12.5     # (see ModelPricing.promo)

``ModelConfig`` is ``extra="allow"``, so the block needs no schema change.
Models without a ``pricing`` block (e.g. local Ollama) contribute ``0`` /
``None`` — they are assumed free even though local inference still costs
electricity. All priced models must share one currency; a mix disables cost
reporting rather than producing an invalid aggregate.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any, NamedTuple

from deerflow.model_ids import normalize_reported_model_name

_module_logger = logging.getLogger(__name__)

# Distinguishes "caller did not pass a clock" (resolve the real one) from an
# explicit ``now=None`` ("the current time is genuinely unknown"), which must
# fail closed on time-limited discounts rather than silently using wall clock.
_NOW_UNSET: Any = object()

# A provider-appended version stamp: Anthropic/OpenAI resolve an undated alias
# to a dated snapshot (``claude-opus-5`` -> ``claude-opus-5-20260115``,
# ``gpt-5.6-sol`` -> ``gpt-5.6-sol-2026-01-15``), and Vertex spells the same
# thing with ``@``. Deliberately narrow — only a terminal date-shaped token is
# stripped — so a genuinely different sibling model (``claude-opus-5-turbo``)
# is never billed at its neighbour's rate.
_VERSION_SUFFIX_RE = re.compile(r"[-_@](?:\d{4}-\d{2}-\d{2}|\d{8}|\d{6})$")

# The price a bundled model already carries in its ``display_name``
# (``Grok 4.5 ($2/6) (OpenRouter) (p)``), optionally with a starred promo pair
# (``($1.15/3.6 → $0.28/0.87*)``). Deliberately anchored on the ``$`` and the
# bracket so a bare version number (``Gemini 3.6 Flash``) is never read as a
# price. Kept in step with ``scripts/wizard/providers.py::pricing_for_display_name``
# by ``test_pricing.py::test_derived_and_shipped_prices_agree_for_every_bundled_model``.
_DISPLAY_NAME_PRICE_RE = re.compile(r"\(\$(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)(?:\s*→\s*\$(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\*)?\)")

# Anthropic publishes prompt-cache reads at 0.1x the input price. Other
# providers differ or publish none, so their derived blocks omit the hit price
# and cache reads fall back to the miss price (the conservative upper bound).
_ANTHROPIC_CACHE_HIT_RATIO = 0.1


def derive_pricing_from_display_name(display_name: str | None) -> dict | None:
    """A ``pricing:``-shaped dict read off a model's display name, or None.

    Every bundled model's name already states its price, and the shipped
    ``pricing:`` blocks are generated from exactly that pair — the block is a
    machine-readable copy, not independent data. Treating it as *required*
    is what left existing installs unpriced: shipping the blocks in
    ``config.example.yaml`` only reaches a brand-new ``config.yaml``, because
    ``sync-api-key-models.py`` skips a provider block whose models are already
    active and ``config_upgrade.py``'s dict-based ``merge_missing`` cannot add a
    key inside an existing list entry. Deriving from the name makes the block
    optional, so a config written before the blocks existed prices correctly
    with no migration, and a hand-added model that follows the naming
    convention is priced for free.

    An explicit ``pricing:`` block always wins — see ``build_pricing_map``.
    """
    if not display_name:
        return None
    match = _DISPLAY_NAME_PRICE_RE.search(display_name)
    if match is None:
        return None
    is_anthropic = display_name.rstrip().endswith("(Anthropic)")
    input_per_million = float(match.group(1))
    pricing: dict = {
        "currency": "USD",
        "input_per_million": input_per_million,
        "output_per_million": float(match.group(2)),
    }
    if is_anthropic:
        pricing["input_cache_hit_per_million"] = round(input_per_million * _ANTHROPIC_CACHE_HIT_RATIO, 6)
    if match.group(3) is not None and match.group(4) is not None:
        promo_input = float(match.group(3))
        pricing["promo_input_per_million"] = promo_input
        pricing["promo_output_per_million"] = float(match.group(4))
        if is_anthropic:
            pricing["promo_input_cache_hit_per_million"] = round(promo_input * _ANTHROPIC_CACHE_HIT_RATIO, 6)
    return pricing


# An OpenRouter routing variant appended to the slug (``:free``, ``:nitro``,
# ``:floor``, ``:online``, ...). Tried only after the exact lookup, so an Ollama
# tag (``qwen3:8b``, the same shape) still matches its own configured entry.
_VARIANT_SUFFIX_RE = re.compile(r":[A-Za-z0-9._-]+$")


def parse_discount_expiry(value: Any) -> tuple[datetime | None, bool]:
    """``(expiry, valid)`` for a discount's ``until``.

    ``(None, True)`` means "no expiry configured" — the discount runs until the
    operator removes it. ``(None, False)`` means the value was present but
    unreadable, which callers must treat as *expired* rather than eternal: a
    date nobody can parse is exactly the state in which a stale discount would
    otherwise be advertised forever.

    A bare ``until: 2026-08-31`` is inclusive — it reads as "through the 31st",
    not "until the 31st begins" — so a plain date resolves to the last instant
    of that day. PyYAML hands us a real ``date``/``datetime`` for an unquoted
    value and a ``str`` for a quoted one; all three spellings are accepted
    because which one an operator writes is an accident of quoting.
    """
    if value is None:
        return None, True
    if isinstance(value, bool):  # `until: true` is not a date
        return None, False
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):  # after datetime: datetime subclasses date
        parsed = datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=UTC)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None, False
        try:
            if len(text) == 10:
                day = date.fromisoformat(text)
                parsed = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC)
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None, False
    else:
        return None, False
    if parsed.tzinfo is None:
        # A naive timestamp is read as UTC rather than local time: the server's
        # zone is not a property of the provider's promotion.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed, True


class ModelPricing(NamedTuple):
    input_per_million: float
    output_per_million: float
    currency: str
    # Price for prompt-cache-hit input tokens. None → hits are billed at the
    # full input price (conservative upper bound for providers that don't
    # discount, or when the operator hasn't configured the hit price).
    input_cache_hit_per_million: float | None = None
    # Temporary promotional / introductory rates, when the provider is currently
    # discounting this model (an OpenRouter promo, an Anthropic intro window).
    # These are strictly additive: the standard rates above stay what cost
    # reporting bills against, because a promo can end at any time and a
    # silently-too-low estimate is worse than a slightly-high one. They exist so
    # the UI can show what a conversation costs *now* beside what it costs once
    # the discount lapses.
    promo_input_per_million: float | None = None
    promo_output_per_million: float | None = None
    promo_input_cache_hit_per_million: float | None = None
    # When the discount lapses, purely for display ("promo rate through Aug 31").
    # Enforcement does not read this: an expired discount is dropped in
    # ``build_pricing_map`` and never reaches a ``ModelPricing`` at all, so every
    # consumer stays correct without repeating the expiry check.
    discount_until: datetime | None = None

    def promo(self) -> ModelPricing | None:
        """This model's promotional rates as a standalone price, or None.

        Returned as an ordinary ``ModelPricing`` so ``token_cost`` prices a
        promo exactly the way it prices a standard rate — there is no second
        cost formula to keep in step.
        """
        if self.promo_input_per_million is None or self.promo_output_per_million is None:
            return None
        return ModelPricing(
            self.promo_input_per_million,
            self.promo_output_per_million,
            self.currency,
            self.promo_input_cache_hit_per_million,
        )


def _parse_promo_rates(raw: dict, input_price: float, output_price: float, *, model_name: str, log: logging.Logger) -> tuple[float | None, float | None, float | None]:
    """Optional promotional rates from a ``pricing:`` block.

    Both directions must be present, positive, and no higher than the standard
    rate. A half-specified or above-list "promo" is a config error, and honouring
    part of it would under-report spend against a price the provider never
    offered, so the whole promo is dropped with a warning. An invalid *cache-hit*
    rate is narrower — it degrades to the promo miss price, the same conservative
    fallback the standard block already uses.
    """
    raw_input = raw.get("promo_input_per_million")
    raw_output = raw.get("promo_output_per_million")
    raw_hit = raw.get("promo_input_cache_hit_per_million")
    if raw_input is None and raw_output is None and raw_hit is None:
        return None, None, None
    try:
        promo_input = float(raw_input) if raw_input is not None else None
        promo_output = float(raw_output) if raw_output is not None else None
        promo_hit = float(raw_hit) if raw_hit is not None else None
    except (TypeError, ValueError):
        log.warning("pricing: ignoring malformed promo pricing on model %s", model_name)
        return None, None, None
    if promo_input is None or promo_output is None:
        log.warning("pricing: ignoring incomplete promo pricing on model %s (needs both promo_input_per_million and promo_output_per_million)", model_name)
        return None, None, None
    if not (0 < promo_input <= input_price) or not (0 < promo_output <= output_price):
        log.warning("pricing: ignoring promo pricing on model %s because it is not a positive discount below the standard rate", model_name)
        return None, None, None
    if promo_hit is not None and not (0 <= promo_hit <= promo_input):
        log.warning("pricing: ignoring promo cache-hit price on model %s (must be between 0 and the promo input price)", model_name)
        promo_hit = None
    return promo_input, promo_output, promo_hit


def _raw_from_price_fields(model_cfg: Any) -> dict | None:
    """A ``pricing:``-shaped dict from the explicit ``price:`` / ``discount:`` fields.

    These are the operator-facing surface: short, flat keys (``input`` /
    ``output`` / ``cache_hit``) instead of the ``*_per_million`` spelling, and a
    ``discount:`` block that carries its own ``until``. Normalizing here means
    the rest of this module keeps one internal shape, so the legacy block, the
    display-name fallback, and the new fields cannot drift into three different
    cost paths.
    """
    price = getattr(model_cfg, "price", None)
    if not isinstance(price, dict):
        return None
    raw: dict = {
        "currency": price.get("currency") or "USD",
        "input_per_million": price.get("input"),
        "output_per_million": price.get("output"),
    }
    if price.get("cache_hit") is not None:
        raw["input_cache_hit_per_million"] = price.get("cache_hit")
    discount = getattr(model_cfg, "discount", None)
    if isinstance(discount, dict):
        raw["promo_input_per_million"] = discount.get("input")
        raw["promo_output_per_million"] = discount.get("output")
        if discount.get("cache_hit") is not None:
            raw["promo_input_cache_hit_per_million"] = discount.get("cache_hit")
        if "until" in discount:
            raw["promo_until"] = discount.get("until")
    return raw


def _resolve_discount_window(raw: dict, *, now: datetime | None, model_name: str, log: logging.Logger) -> tuple[bool, datetime | None]:
    """``(keep_discount, expiry)`` for a parsed pricing dict.

    Fails closed in both unknown cases — an unreadable ``until`` and an unknown
    current time. A cost estimate that is too high is corrected by the provider's
    bill; one that advertises a discount the provider has stopped offering is the
    silent failure this whole field exists to remove.
    """
    expiry, valid = parse_discount_expiry(raw.get("promo_until"))
    if not valid:
        log.warning(
            "pricing: ignoring the discount on model %s because its `until` expiry could not be read (%r); an unreadable date must not mean 'never expires'",
            model_name,
            raw.get("promo_until"),
        )
        return False, None
    if expiry is None:
        return True, None
    if now is None:
        log.warning(
            "pricing: ignoring the discount on model %s because the current time is unavailable and the discount expires (%s); billing at the standard rate",
            model_name,
            expiry.isoformat(),
        )
        return False, expiry
    return now <= expiry, expiry


def build_pricing_map(models: Any, *, logger: logging.Logger | None = None, now: datetime | None = _NOW_UNSET) -> dict[str, ModelPricing]:
    """Collect per-model prices from an iterable of model configs.

    Entries are keyed by both the config ``name`` and the provider ``model``
    id (plus lowercase variants), because ``token_usage_by_model`` buckets
    carry the provider-reported model name. Returns an empty map (cost
    reporting disabled) when priced models mix currencies.
    """
    log = logger or _module_logger
    if now is _NOW_UNSET:
        # Resolving the clock here rather than at import time keeps a long-lived
        # process from freezing a discount window at startup. A clock that cannot
        # be read at all becomes an explicit "unknown", which fails closed below
        # rather than raising out of cost reporting.
        try:
            now = datetime.now(UTC)
        except (OSError, OverflowError, ValueError):  # pragma: no cover - platform clock failure
            log.warning("pricing: system clock unavailable; time-limited discounts will be ignored")
            now = None
    pricing: dict[str, ModelPricing] = {}
    pricing_currency_value: str | None = None
    pricing_currency_model: str | None = None
    for model_cfg in models or []:
        # Precedence: the explicit fields an operator can see and set, then the
        # legacy block, then the price the display name already states.
        raw = _raw_from_price_fields(model_cfg)
        if raw is None:
            raw = getattr(model_cfg, "pricing", None)
        if not isinstance(raw, dict):
            # No explicit block: fall back to the price the name already states.
            # A malformed *explicit* block deliberately does not reach here — it
            # is an operator error worth surfacing (below), not something to
            # paper over with a different number.
            raw = derive_pricing_from_display_name(getattr(model_cfg, "display_name", None))
            if raw is None:
                continue
            log.debug("pricing: derived price for %s from its display name (no pricing: block configured)", getattr(model_cfg, "name", "?"))
        try:
            input_price = float(raw.get("input_per_million") or 0)
            output_price = float(raw.get("output_per_million") or 0)
            raw_hit_price = raw.get("input_cache_hit_per_million")
            cache_hit_price = float(raw_hit_price) if raw_hit_price is not None else None
        except (TypeError, ValueError):
            log.warning("pricing: ignoring malformed pricing on model %s", getattr(model_cfg, "name", "?"))
            continue
        if input_price <= 0 and output_price <= 0:
            continue
        model_currency = str(raw.get("currency") or "USD").strip().upper() or "USD"
        if pricing_currency_value is None:
            pricing_currency_value = model_currency
            pricing_currency_model = model_cfg.name
        elif model_currency != pricing_currency_value:
            log.warning(
                "pricing: disabling cost reporting because model pricing mixes currencies (%s on %s, %s on %s)",
                pricing_currency_value,
                pricing_currency_model,
                model_currency,
                model_cfg.name,
            )
            return {}
        entry_name = str(getattr(model_cfg, "name", "?"))
        promo_input, promo_output, promo_hit = _parse_promo_rates(raw, input_price, output_price, model_name=entry_name, log=log)
        discount_until: datetime | None = None
        if promo_input is not None or promo_output is not None:
            keep_discount, discount_until = _resolve_discount_window(raw, now=now, model_name=entry_name, log=log)
            if not keep_discount:
                # Dropped here, so an expired discount never reaches a
                # ``ModelPricing`` and no consumer has to re-check the window.
                promo_input = promo_output = promo_hit = None
        entry = ModelPricing(input_price, output_price, model_currency, cache_hit_price, promo_input, promo_output, promo_hit, discount_until if promo_input is not None else None)
        for key in (model_cfg.name, getattr(model_cfg, "model", None)):
            if key:
                pricing.setdefault(key, entry)
                pricing.setdefault(key.lower(), entry)
    return pricing


def pricing_currency(pricing: dict[str, ModelPricing]) -> str | None:
    """Display currency: the first configured entry's (one currency per deployment)."""
    return next(iter(pricing.values())).currency if pricing else None


@lru_cache(maxsize=1024)
def _pricing_lookup_candidates(model: str) -> tuple[str, ...]:
    """Normalized forms of a provider-reported model id, most specific first.

    ``token_usage_by_model`` buckets are keyed by what the provider reported
    (``response_metadata.model_name``), which is frequently *not* the id written
    in ``config.yaml``: LangChain records the API-resolved model, so an undated
    Anthropic alias comes back as its dated snapshot, OpenRouter appends a
    ``:variant`` routing tag, and a routed slug carries a ``vendor/`` prefix.
    Matching only on the exact string left every bucket unpriced.

    Each candidate is tried against the map by exact lookup (never a prefix
    scan), so a normalization can only ever hit a model the operator actually
    configured. Order matters: a configured OpenRouter copy must win over the
    direct entry its slug also reduces to, since the two carry different prices.

    A *duplicated* id is normalized here as well as at the source
    (``deerflow.model_ids``), because every run persisted before the source was
    fixed still carries the doubled key in its ``token_usage_by_model`` — those
    threads must keep pricing without a data migration.
    """
    bases: list[str] = [model]
    # ``deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro`` -> one copy.
    collapsed = normalize_reported_model_name(model)
    if collapsed and collapsed != model:
        bases.append(collapsed)
    # ``anthropic/claude-opus-5`` -> also try ``claude-opus-5``.
    for base in list(bases):
        if "/" in base:
            bases.append(base.split("/", 1)[1])
    for base in list(bases):
        without_variant = _VARIANT_SUFFIX_RE.sub("", base)
        if without_variant and without_variant != base:
            bases.append(without_variant)
    for base in list(bases):
        without_version = _VERSION_SUFFIX_RE.sub("", base)
        if without_version and without_version != base:
            bases.append(without_version)

    candidates: list[str] = []
    seen: set[str] = set()
    for base in bases:
        for form in (base, base.lower()):
            if form and form not in seen:
                seen.add(form)
                candidates.append(form)
    return tuple(candidates)


def lookup_pricing(pricing: dict[str, ModelPricing], model: str | None) -> ModelPricing | None:
    """Price for a model id, tolerating provider-reported id variations.

    Returns ``None`` for a model no configured entry can account for — an
    unpriced local model must stay unpriced rather than inherit a neighbour's
    rate (see ``_pricing_lookup_candidates`` for why exact-only matching is
    not enough in practice).
    """
    if not model or not pricing:
        return None
    for candidate in _pricing_lookup_candidates(model):
        price = pricing.get(candidate)
        if price is not None:
            return price
    return None


def token_cost(input_tokens: int, output_tokens: int, price: ModelPricing, cache_read_tokens: int = 0) -> float:
    """Cache-aware spend: cache-hit input tokens are billed at the hit price.

    ``cache_read_tokens`` is clamped into ``[0, input_tokens]``; the remainder
    is billed at the full (cache-miss) input price. Without a configured hit
    price all input is billed at the miss price.
    """
    cache_read = min(max(int(cache_read_tokens or 0), 0), max(int(input_tokens or 0), 0))
    uncached = max(int(input_tokens or 0), 0) - cache_read
    hit_price = price.input_cache_hit_per_million if price.input_cache_hit_per_million is not None else price.input_per_million
    return (uncached / 1_000_000) * price.input_per_million + (cache_read / 1_000_000) * hit_price + (output_tokens / 1_000_000) * price.output_per_million


def run_cost(
    pricing: dict[str, ModelPricing],
    *,
    model_name: str | None,
    total_input_tokens: int | None,
    total_output_tokens: int | None,
    token_usage_by_model: dict | None,
) -> float | None:
    """Estimate one run's spend, or None when none of its models are priced.

    Prefers the per-model breakdown (accurate for multi-model runs, e.g.
    subagents on a different model); falls back to run-level totals priced at
    ``model_name`` for legacy rows. Buckets without an input/output split are
    skipped rather than guessed.
    """
    cost = 0.0
    priced = False
    if isinstance(token_usage_by_model, dict):
        for model, usage in token_usage_by_model.items():
            if not isinstance(usage, dict):
                continue
            price = lookup_pricing(pricing, model)
            if price is None:
                continue
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            if input_tokens == 0 and output_tokens == 0:
                continue
            cost += token_cost(input_tokens, output_tokens, price, int(usage.get("cache_read_tokens") or 0))
            priced = True
    if priced:
        return cost
    price = lookup_pricing(pricing, model_name)
    if price is None:
        return None
    input_tokens = int(total_input_tokens or 0)
    output_tokens = int(total_output_tokens or 0)
    if input_tokens == 0 and output_tokens == 0:
        return None
    return token_cost(input_tokens, output_tokens, price)
