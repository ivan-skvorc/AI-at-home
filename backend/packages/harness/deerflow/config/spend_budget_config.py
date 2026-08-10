"""Config for currency-denominated spend caps (fork feature).

``token_budget`` caps a *single run* in tokens. That is the wrong unit for this
fork: its whole premise is mixing a premium cloud lead with cheap or free local
subagents in one session, so 200k tokens can be five dollars or nothing at all
depending on which model burned them. ``spend_budget`` caps real money instead,
over a daily / weekly / monthly window, in whatever single currency
``models[*].pricing`` is written in.

The shape deliberately mirrors :class:`~deerflow.config.token_budget_config.TokenBudgetConfig`
(``enabled``, limits, ``warn_threshold``, ``hard_stop_threshold``) so the two
read the same way in ``config.yaml`` and the middleware behaviour is familiar:
warn in-context at the warn threshold, force a final answer at the hard stop.

The feature self-disables when no model is priced — there is nothing to
denominate a budget in — and ``make doctor`` says so.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from pydantic import BaseModel, Field, model_validator


class SpendLimit(NamedTuple):
    """One configured window limit: ``("daily", 5.0)``."""

    period: str
    amount: float


# Shortest window first: a daily cap is the one most likely to bite, and
# reporting it first makes the header show the tightest remaining figure.
_PERIOD_ORDER = ("daily", "weekly", "monthly")


class SpendBudgetConfig(BaseModel):
    """Configuration for currency-denominated spend caps."""

    enabled: bool = Field(default=False, description="startup-safe: whether to enforce spend caps. Self-disables when no model carries a price.")
    daily_limit: float | None = Field(default=None, gt=0, description="Maximum spend per day, in the configured pricing currency.")
    weekly_limit: float | None = Field(default=None, gt=0, description="Maximum spend per week, in the configured pricing currency.")
    monthly_limit: float | None = Field(default=None, gt=0, description="Maximum spend per month, in the configured pricing currency.")
    window: Literal["rolling", "calendar"] = Field(
        default="rolling",
        description="'rolling' counts the last 24h / 7d / 30d; 'calendar' counts since local midnight / Monday / the 1st.",
    )
    tz_offset_minutes: int = Field(
        default=0,
        ge=-840,
        le=840,
        description="Local-time offset from UTC used to place calendar window boundaries. Ignored for rolling windows. Enforcement runs server-side with no browser to ask, so the offset is config, not a request parameter.",
    )
    warn_threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="Fraction of the tightest limit at which an in-context warning is injected.")
    hard_stop_threshold: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Fraction of a limit at which tool calls are stripped and the agent is forced to produce a final answer, and at which new runs are refused.",
    )

    @model_validator(mode="after")
    def validate_budget(self) -> SpendBudgetConfig:
        if self.hard_stop_threshold < self.warn_threshold:
            raise ValueError("hard_stop_threshold must be >= warn_threshold")
        if self.enabled and not self.limits():
            raise ValueError("spend_budget.enabled is true but no cap is configured: set at least one of daily_limit / weekly_limit / monthly_limit")
        return self

    def limits(self) -> tuple[SpendLimit, ...]:
        """Configured limits, shortest window first."""
        amounts = {"daily": self.daily_limit, "weekly": self.weekly_limit, "monthly": self.monthly_limit}
        return tuple(SpendLimit(period, float(amounts[period])) for period in _PERIOD_ORDER if amounts[period] is not None)
