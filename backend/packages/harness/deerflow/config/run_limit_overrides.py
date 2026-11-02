"""Run limits the Web UI may replace at runtime (fork feature, FORK.md §46).

``config.yaml`` sets every limit that can end a run early: the currency spend
cap, the tool-call loop limits, the per-run token budgets and the step limit of
runs that do not choose their own. Settings → Run limits lets an administrator
replace these server-wide without editing that file, which the UI never
rewrites. The replacements live under ``run_limits`` in ``runtime_settings.json``
(:mod:`deerflow.config.runtime_settings`), shared by every worker on the same
data directory.

Each section is either **absent** — ``config.yaml`` applies unchanged — or a
**complete replacement** of the fields the page edits, so what the page shows
is exactly what a run enforces:

* ``spend_budget``: on/off plus the three window amounts (an absent amount
  clears that window). Window kind, time zone and thresholds stay in YAML.
* ``loop_detection``: on/off plus the identical-repeat and per-tool limits.
  The per-tool limit then applies to **every** tool: YAML
  ``tool_freq_overrides`` are ignored while this section is set, otherwise a
  raised limit would still stop ``bash`` at an override the page never showed.
* ``token_budget`` / ``subagent_token_budget``: on/off plus ``max_tokens``.
  The separate input/output budgets and per-subagent YAML budgets are ignored
  while set, for the same reason.
* ``recursion_limit``: the step limit for runs that do not send their own
  (workflow agents, channels, API callers), still clamped to
  ``max_recursion_limit``. The web composer always sends that ceiling.

The ``effective_*`` helpers are called wherever a run reads the limit (lead
agent assembly, the subagent chain, spend admission and status, Gateway run
config), so a saved change applies to the next run with no restart. A stored
section that no longer validates is ignored with an error log, and that section
falls back to ``config.yaml``: a hand-edited file must never stop every run.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, ValidationError, model_validator

from deerflow.config.loop_detection_config import LoopDetectionConfig
from deerflow.config.runtime_settings import get_runtime_setting, set_runtime_setting
from deerflow.config.spend_budget_config import SpendBudgetConfig
from deerflow.config.token_budget_config import TokenBudgetConfig

logger = logging.getLogger(__name__)

RUN_LIMITS_KEY = "run_limits"

# Generous bounds: they reject typos and overflow, not deliberate choices.
_MAX_AMOUNT = 1_000_000.0
_MAX_TOOL_CALLS = 100_000
_MAX_TOKENS = 1_000_000_000
_MAX_STEPS = 100_000


class _Override(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpendCapOverride(_Override):
    enabled: StrictBool
    daily_limit: StrictFloat | None = Field(default=None, gt=0, le=_MAX_AMOUNT)
    weekly_limit: StrictFloat | None = Field(default=None, gt=0, le=_MAX_AMOUNT)
    monthly_limit: StrictFloat | None = Field(default=None, gt=0, le=_MAX_AMOUNT)

    @model_validator(mode="after")
    def _needs_a_cap(self) -> SpendCapOverride:
        if self.enabled and self.daily_limit is None and self.weekly_limit is None and self.monthly_limit is None:
            raise ValueError("Set at least one of daily_limit, weekly_limit or monthly_limit to turn the spend cap on")
        return self


class ToolCallLimitsOverride(_Override):
    enabled: StrictBool
    warn_threshold: StrictInt = Field(ge=1, le=_MAX_TOOL_CALLS)
    hard_limit: StrictInt = Field(ge=1, le=_MAX_TOOL_CALLS)
    tool_freq_warn: StrictInt = Field(ge=1, le=_MAX_TOOL_CALLS)
    tool_freq_hard_limit: StrictInt = Field(ge=1, le=_MAX_TOOL_CALLS)

    @model_validator(mode="after")
    def _stop_after_warning(self) -> ToolCallLimitsOverride:
        if self.hard_limit < self.warn_threshold:
            raise ValueError("hard_limit must be greater than or equal to warn_threshold")
        if self.tool_freq_hard_limit < self.tool_freq_warn:
            raise ValueError("tool_freq_hard_limit must be greater than or equal to tool_freq_warn")
        return self


class TokenBudgetOverride(_Override):
    enabled: StrictBool
    max_tokens: StrictInt = Field(ge=1000, le=_MAX_TOKENS)


class RunLimitOverrides(_Override):
    """Every override section; ``None`` means config.yaml applies."""

    spend_budget: SpendCapOverride | None = None
    loop_detection: ToolCallLimitsOverride | None = None
    token_budget: TokenBudgetOverride | None = None
    subagent_token_budget: TokenBudgetOverride | None = None
    recursion_limit: StrictInt | None = Field(default=None, ge=1, le=_MAX_STEPS)


def get_run_limit_overrides() -> RunLimitOverrides:
    """The stored overrides, validated section by section."""
    raw = get_runtime_setting(RUN_LIMITS_KEY)
    if not isinstance(raw, dict):
        if raw is not None:
            logger.error("runtime_settings: %s is not an object; every run limit uses config.yaml", RUN_LIMITS_KEY)
        return RunLimitOverrides()
    sections: dict[str, Any] = {}
    for name in RunLimitOverrides.model_fields:
        if raw.get(name) is None:
            continue
        try:
            RunLimitOverrides.model_validate({name: raw[name]})
        except ValidationError as exc:
            # Field names and error kinds only: the stored values are not secret,
            # but a hand-edited file may hold anything.
            logger.error("runtime_settings: ignoring invalid run limit %r (%s); config.yaml applies", name, ", ".join(sorted({err["type"] for err in exc.errors()})))
            continue
        sections[name] = raw[name]
    return RunLimitOverrides.model_validate(sections)


def set_run_limit_overrides(overrides: RunLimitOverrides) -> RunLimitOverrides:
    """Persist *overrides* (absent sections removed) and return what was stored."""
    payload = overrides.model_dump(exclude_none=True)
    set_runtime_setting(RUN_LIMITS_KEY, payload or None)
    return get_run_limit_overrides()


def _merge(model: type[BaseModel], base: BaseModel, update: dict[str, Any], section: str) -> Any:
    try:
        return model.model_validate({**base.model_dump(), **update})
    except ValidationError as exc:
        # Only a YAML value outside the override (e.g. thresholds) can make this
        # fail; keep runs going on config.yaml and say why.
        logger.error("Run limit override %r conflicts with config.yaml (%s); config.yaml applies", section, ", ".join(sorted({err["type"] for err in exc.errors()})))
        return base


def effective_spend_budget(base: SpendBudgetConfig) -> SpendBudgetConfig:
    override = get_run_limit_overrides().spend_budget
    if override is None:
        return base
    return _merge(SpendBudgetConfig, base, override.model_dump(), "spend_budget")


def effective_loop_detection(base: LoopDetectionConfig) -> LoopDetectionConfig:
    override = get_run_limit_overrides().loop_detection
    if override is None:
        return base
    return _merge(LoopDetectionConfig, base, {**override.model_dump(), "tool_freq_overrides": {}}, "loop_detection")


def _token_budget(base: TokenBudgetConfig, override: TokenBudgetOverride | None, section: str) -> TokenBudgetConfig:
    if override is None:
        return base
    return _merge(TokenBudgetConfig, base, {**override.model_dump(), "max_input_tokens": None, "max_output_tokens": None}, section)


def effective_token_budget(base: TokenBudgetConfig) -> TokenBudgetConfig:
    """The lead agent's per-run token budget."""
    return _token_budget(base, get_run_limit_overrides().token_budget, "token_budget")


def effective_subagent_token_budget(base: TokenBudgetConfig) -> TokenBudgetConfig:
    """Every subagent's per-run token budget (wins over per-agent YAML budgets)."""
    return _token_budget(base, get_run_limit_overrides().subagent_token_budget, "subagent_token_budget")


def effective_recursion_limit(base: int) -> int:
    """The step limit for runs that do not send one (callers clamp to the ceiling)."""
    override = get_run_limit_overrides().recursion_limit
    return base if override is None else override
