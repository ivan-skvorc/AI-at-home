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

``ModelConfig`` is ``extra="allow"``, so the block needs no schema change.
Models without a ``pricing`` block (e.g. local Ollama) contribute ``0`` /
``None`` — they are assumed free even though local inference still costs
electricity. All priced models must share one currency; a mix disables cost
reporting rather than producing an invalid aggregate.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, NamedTuple

_module_logger = logging.getLogger(__name__)

# A provider-appended version stamp: Anthropic/OpenAI resolve an undated alias
# to a dated snapshot (``claude-opus-5`` -> ``claude-opus-5-20260115``,
# ``gpt-5.6-sol`` -> ``gpt-5.6-sol-2026-01-15``), and Vertex spells the same
# thing with ``@``. Deliberately narrow — only a terminal date-shaped token is
# stripped — so a genuinely different sibling model (``claude-opus-5-turbo``)
# is never billed at its neighbour's rate.
_VERSION_SUFFIX_RE = re.compile(r"[-_@](?:\d{4}-\d{2}-\d{2}|\d{8}|\d{6})$")

# An OpenRouter routing variant appended to the slug (``:free``, ``:nitro``,
# ``:floor``, ``:online``, ...). Tried only after the exact lookup, so an Ollama
# tag (``qwen3:8b``, the same shape) still matches its own configured entry.
_VARIANT_SUFFIX_RE = re.compile(r":[A-Za-z0-9._-]+$")


class ModelPricing(NamedTuple):
    input_per_million: float
    output_per_million: float
    currency: str
    # Price for prompt-cache-hit input tokens. None → hits are billed at the
    # full input price (conservative upper bound for providers that don't
    # discount, or when the operator hasn't configured the hit price).
    input_cache_hit_per_million: float | None = None


def build_pricing_map(models: Any, *, logger: logging.Logger | None = None) -> dict[str, ModelPricing]:
    """Collect per-model prices from an iterable of model configs.

    Entries are keyed by both the config ``name`` and the provider ``model``
    id (plus lowercase variants), because ``token_usage_by_model`` buckets
    carry the provider-reported model name. Returns an empty map (cost
    reporting disabled) when priced models mix currencies.
    """
    log = logger or _module_logger
    pricing: dict[str, ModelPricing] = {}
    pricing_currency_value: str | None = None
    pricing_currency_model: str | None = None
    for model_cfg in models or []:
        raw = getattr(model_cfg, "pricing", None)
        if not isinstance(raw, dict):
            continue
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
        entry = ModelPricing(input_price, output_price, model_currency, cache_hit_price)
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
    """
    bases: list[str] = [model]
    # ``anthropic/claude-opus-5`` -> also try ``claude-opus-5``.
    if "/" in model:
        bases.append(model.split("/", 1)[1])
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
