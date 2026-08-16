"""Currency-denominated spend caps — the Gateway's accounting half (fork feature).

``config.yaml -> spend_budget`` caps real money over a daily / weekly / monthly
window (see :mod:`deerflow.config.spend_budget_config` for why tokens are the
wrong unit in this fork). This module answers the one question every consumer
of that cap needs: **how much has been spent in each configured window, and how
much is left.**

Three consumers, one answer:

* **Run admission** (``services.py::start_run``) refuses a new run when a limit
  is already at the hard-stop threshold.
* **In-run enforcement** — the resolved status is handed to the agent as a
  *baseline*, and ``SpendBudgetMiddleware`` adds the live run's own spend to it,
  so a single long run cannot blow through a cap it started just under.
* **The chat header** shows the tightest remaining figure beside the cost.

Spend is summed from the same two sources the header already prices: persisted
runs (``runs.token_usage_by_model``, via ``run_cost``) and the durable
auxiliary counters (memory extraction / follow-up suggestions, via
``aux_usage_store``). Both go through :mod:`deerflow.pricing`, so there is no
second cost formula to drift.

**Unpriced models contribute zero**, which is deliberate and load-bearing: a
fully local Ollama run costs nothing, so a spend cap must never block it.

**No pricing configured disables the feature.** A budget denominated in a
currency nothing is priced in cannot mean anything, so rather than silently
enforcing a cap against a permanent 0 (which would never trigger) or against
nothing (which would block everything), the feature reports itself off with a
reason. ``make doctor`` surfaces that reason.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from deerflow.config.app_config import AppConfig
from deerflow.config.spend_budget_config import SpendBudgetConfig
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.pricing import ModelPricing, build_pricing_map, lookup_pricing, pricing_currency, run_cost, token_cost
from deerflow.runtime.aux_usage_store import get_aux_usage_store
from deerflow.runtime.spend_window import resolve_window_start

logger = logging.getLogger(__name__)

# Why the budget is not being enforced, when it is not.
DISABLED_NOT_CONFIGURED = "not_configured"
DISABLED_NO_PRICING = "no_pricing"
DISABLED_NO_DATABASE = "no_database"

_DISABLED_REASON_TEXT = {
    DISABLED_NOT_CONFIGURED: "spend_budget.enabled is false",
    DISABLED_NO_PRICING: "no model carries a price, so a currency budget has nothing to measure (add a pricing: block, or a ($in/out) pair in the display name)",
    DISABLED_NO_DATABASE: "database.backend is memory, so there is no persisted spend history to measure a window against",
}


def disabled_reason_text(reason: str | None) -> str | None:
    """Human-readable explanation for a ``disabled_reason`` code."""
    return _DISABLED_REASON_TEXT.get(reason) if reason else None


@dataclass(frozen=True)
class SpendLimitStatus:
    """One configured window's limit, spend so far, and headroom."""

    period: str
    limit: float
    spent: float

    @property
    def remaining(self) -> float:
        return max(self.limit - self.spent, 0.0)

    @property
    def fraction(self) -> float:
        return self.spent / self.limit if self.limit > 0 else 0.0


@dataclass(frozen=True)
class SpendBudgetStatus:
    """Resolved spend-cap state for one owner at one instant."""

    active: bool
    currency: str | None = None
    limits: tuple[SpendLimitStatus, ...] = ()
    warn_threshold: float = 0.8
    hard_stop_threshold: float = 1.0
    disabled_reason: str | None = None

    @property
    def exceeded(self) -> SpendLimitStatus | None:
        """The first limit at or over the hard-stop threshold, if any."""
        if not self.active:
            return None
        return next((limit for limit in self.limits if limit.fraction >= self.hard_stop_threshold), None)

    @property
    def warning(self) -> SpendLimitStatus | None:
        """The first limit at or over the warn threshold, if any."""
        if not self.active:
            return None
        return next((limit for limit in self.limits if limit.fraction >= self.warn_threshold), None)

    @property
    def tightest(self) -> SpendLimitStatus | None:
        """The limit with the least headroom — the one worth showing the user."""
        if not self.active or not self.limits:
            return None
        return min(self.limits, key=lambda limit: limit.remaining)

    def with_additional_spend(self, extra: float) -> SpendBudgetStatus:
        """This status plus *extra* spend applied to every window.

        The in-run middleware works this way: the Gateway resolves the baseline
        once at admission, and the run's own accumulating spend is added on top
        rather than re-queried on every model call.
        """
        if not self.active or extra <= 0:
            return self
        return SpendBudgetStatus(
            active=self.active,
            currency=self.currency,
            limits=tuple(SpendLimitStatus(limit.period, limit.limit, limit.spent + extra) for limit in self.limits),
            warn_threshold=self.warn_threshold,
            hard_stop_threshold=self.hard_stop_threshold,
            disabled_reason=self.disabled_reason,
        )

    def to_baseline(self) -> dict:
        """A JSON-safe snapshot for the agent's runtime context."""
        return {
            "currency": self.currency,
            "warn_threshold": self.warn_threshold,
            "hard_stop_threshold": self.hard_stop_threshold,
            "limits": [{"period": limit.period, "limit": limit.limit, "spent": limit.spent} for limit in self.limits],
        }


def inactive_status(config: SpendBudgetConfig, reason: str) -> SpendBudgetStatus:
    return SpendBudgetStatus(
        active=False,
        warn_threshold=config.warn_threshold,
        hard_stop_threshold=config.hard_stop_threshold,
        disabled_reason=reason,
    )


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite round-trips timestamps naive; Postgres keeps them aware."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _aux_spend_rows(thread_ids: list[str] | None, since: float) -> list[tuple[str, dict[str, int]]]:
    """(model, totals) pairs for auxiliary calls since *since* (blocking IO)."""
    store = get_aux_usage_store()
    if store is None:
        return []
    return [(row.model_name, row.totals) for row in store.aggregate(since=since, thread_ids=thread_ids)]


def _price_aux_rows(rows: list[tuple[str, dict[str, int]]], pricing: dict[str, ModelPricing]) -> float:
    total = 0.0
    for model, totals in rows:
        price = lookup_pricing(pricing, model)
        if price is None:
            # Unpriced (local) auxiliary model: free, same rule as runs.
            continue
        total += token_cost(int(totals.get("input_tokens") or 0), int(totals.get("output_tokens") or 0), price, int(totals.get("cache_read_tokens") or 0))
    return total


async def resolve_spend_budget_status(
    *,
    app_config: AppConfig | None = None,
    user_id: str | None,
    now: datetime | None = None,
) -> SpendBudgetStatus:
    """Compute spend against each configured window for one owner.

    Returns an inactive status (with a ``disabled_reason``) when the feature is
    off, nothing is priced, or there is no SQL backend to read history from —
    all three are "do not enforce", never "block everything".
    """
    if app_config is None:
        from deerflow.config import get_app_config

        app_config = get_app_config()
    config: SpendBudgetConfig = app_config.spend_budget
    if not config.enabled or not config.limits():
        return inactive_status(config, DISABLED_NOT_CONFIGURED)

    pricing = build_pricing_map(app_config.models, logger=logger)
    if not pricing:
        return inactive_status(config, DISABLED_NO_PRICING)

    session_factory = get_session_factory()
    if session_factory is None:
        return inactive_status(config, DISABLED_NO_DATABASE)

    reference = (now or datetime.now(UTC)).astimezone(UTC)
    limits = config.limits()
    window_starts = {limit.period: resolve_window_start(limit.period, config.window, reference, config.tz_offset_minutes) for limit in limits}
    earliest = min(window_starts.values())

    run_where = [RunRow.operation_kind == "run", RunRow.created_at >= earliest]
    if user_id:
        run_where.append(RunRow.user_id == user_id)

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    RunRow.created_at,
                    RunRow.model_name,
                    RunRow.total_input_tokens,
                    RunRow.total_output_tokens,
                    RunRow.token_usage_by_model,
                ).where(*run_where)
            )
        ).all()
        thread_ids: list[str] | None = None
        if user_id:
            thread_ids = list((await session.execute(select(ThreadMetaRow.thread_id).where(ThreadMetaRow.user_id == user_id))).scalars().all())

    # Auxiliary usage lives in its own store and has no owner column, so it is
    # scoped by the owner's threads. A window's aux spend is read once per
    # distinct window start; the store is a local file, hence the offload.
    aux_by_start: dict[datetime, float] = {}
    for start in set(window_starts.values()):
        aux_rows = await asyncio.to_thread(_aux_spend_rows, thread_ids, start.timestamp())
        aux_by_start[start] = _price_aux_rows(aux_rows, pricing)

    statuses: list[SpendLimitStatus] = []
    for limit in limits:
        start = window_starts[limit.period]
        spent = aux_by_start.get(start, 0.0)
        for created_at, model_name, input_tokens, output_tokens, usage_map in rows:
            created = _as_utc(created_at)
            if created is None or created < start:
                continue
            cost = run_cost(
                pricing,
                model_name=model_name,
                total_input_tokens=input_tokens,
                total_output_tokens=output_tokens,
                token_usage_by_model=usage_map,
            )
            if cost is not None:
                spent += cost
        statuses.append(SpendLimitStatus(limit.period, limit.amount, round(spent, 6)))

    return SpendBudgetStatus(
        active=True,
        currency=pricing_currency(pricing),
        limits=tuple(statuses),
        warn_threshold=config.warn_threshold,
        hard_stop_threshold=config.hard_stop_threshold,
    )


async def resolve_run_spend_budget(request, *, owner_user_id: str | None) -> SpendBudgetStatus:
    """Spend-cap status for a run-creation request. Never raises.

    A failure to resolve the budget (a database hiccup, a malformed config) must
    not take down run creation: a broken cost counter refusing every message is
    worse than a cap that misses one turn, so this degrades to "inactive".
    """
    from app.gateway.deps import get_current_user

    try:
        user_id = owner_user_id or await get_current_user(request)
        return await resolve_spend_budget_status(user_id=user_id)
    except Exception:  # noqa: BLE001 - defensive: the cap must not break run admission
        logger.warning("spend budget: failed to resolve status for run admission; not enforcing for this run", exc_info=True)
        from deerflow.config import get_app_config

        try:
            config = get_app_config().spend_budget
        except Exception:  # noqa: BLE001 - config already failed; fall back to defaults
            config = SpendBudgetConfig()
        return inactive_status(config, DISABLED_NOT_CONFIGURED)


def exhausted_message(limit: SpendLimitStatus, currency: str | None) -> str:
    """Operator-facing text for a refused run."""
    unit = f" {currency}" if currency else ""
    return f"Spend budget exhausted: the {limit.period} cap of {limit.limit:g}{unit} is already at {limit.spent:g}{unit}. Raise or clear spend_budget in config.yaml, or wait for the window to roll over."
