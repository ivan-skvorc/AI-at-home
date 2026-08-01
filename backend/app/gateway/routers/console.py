"""Read-only operations-console endpoints.

Aggregates observability data across all of the current user's threads: run
history, token spend over time, and asset counts — the data layer for an
operations dashboard or any external monitoring consumer.

This is a reporting layer, not a runtime path: it issues short-lived read-only
queries against the harness-owned ``runs`` / ``threads_meta`` tables instead of
widening the runtime ``RunStore`` surface. Requires a SQL database backend
(``database.backend: sqlite | postgres``); returns 503 on the memory backend,
which persists no run history to report on.
"""

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user
from app.gateway.pricing import ModelPricing, build_pricing_map, lookup_pricing, pricing_currency, run_cost, token_cost
from deerflow.config import get_app_config
from deerflow.config.agents_config import list_custom_agents
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/console", tags=["console"])

_ACTIVE_STATUSES = ("pending", "running")
_FAILED_STATUSES = ("error", "timeout")

# Cap the error excerpt in list responses; the full text stays on the run row.
_ERROR_EXCERPT_CHARS = 300


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ConsoleStatsResponse(BaseModel):
    """Headline counters for the console dashboard."""

    total_runs: int = Field(..., description="All recorded runs for the current user")
    active_runs: int = Field(..., description="Runs currently pending or running")
    failed_runs: int = Field(..., description="Runs that ended in error or timeout")
    total_threads: int = Field(..., description="Conversation threads owned by the current user")
    total_agents: int = Field(..., description="Custom agents owned by the current user")
    total_tokens: int = Field(..., description="Tokens consumed across all recorded runs")
    total_cost: float | None = Field(default=None, description="Estimated spend across priced runs; null when no models[*].pricing is configured")
    currency: str | None = Field(default=None, description="Display currency taken from the first configured pricing entry")


class ConsoleRunItem(BaseModel):
    """One run in the cross-thread run listing."""

    run_id: str
    thread_id: str
    thread_title: str | None = Field(default=None, description="Display name from threads_meta, if tracked")
    assistant_id: str | None = None
    status: str
    model_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, description="Wall-clock duration; live elapsed time for active runs")
    total_tokens: int = 0
    message_count: int = 0
    cost: float | None = Field(default=None, description="Estimated spend for this run; null when its models are unpriced")
    error: str | None = Field(default=None, description="Error excerpt for failed runs")


class ConsoleRunsResponse(BaseModel):
    """Paginated cross-thread run listing, newest first."""

    runs: list[ConsoleRunItem]
    has_more: bool


class ConsoleUsageDay(BaseModel):
    """Token usage aggregated over one local-time day."""

    date: str = Field(..., description="Local date (YYYY-MM-DD) per the requested tz offset")
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    runs: int = 0
    cost: float = Field(default=0.0, description="Estimated spend for the day across priced runs")


class ConsoleUsageModelBreakdown(BaseModel):
    """Token usage attributed to one model."""

    tokens: int = 0
    runs: int = Field(default=0, description="Runs that used this model (non-exclusive)")
    cost: float | None = Field(default=None, description="Estimated spend for this model; null when unpriced")
    input_tokens: int = Field(default=0, description="Input tokens attributed to this model")
    cache_read_tokens: int = Field(default=0, description="Prompt-cache-hit input tokens attributed to this model")


class ConsoleUsageResponse(BaseModel):
    """Daily token-usage series plus per-model breakdown for the window."""

    days: list[ConsoleUsageDay]
    by_model: dict[str, ConsoleUsageModelBreakdown]
    total_tokens: int
    total_runs: int
    total_cost: float | None = Field(default=None, description="Estimated spend for the window; null when no pricing is configured")
    currency: str | None = Field(default=None, description="Display currency taken from the first configured pricing entry")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_factory_or_503():
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(
            status_code=503,
            detail="Console requires a SQL database backend; set database.backend to sqlite or postgres in config.yaml.",
        )
    return sf


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize DB timestamps: SQLite round-trips them naive, Postgres aware."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


# ---------------------------------------------------------------------------
# Pricing — real spend estimation
# ---------------------------------------------------------------------------
#
# The pricing math itself lives in ``app.gateway.pricing`` so the per-thread
# token-usage endpoint (the chat sidebar cost overview) and this console share
# one implementation. Only ``_build_pricing_map`` stays here because it reads
# ``get_app_config()`` — kept module-local so tests can patch that seam and so
# the mixed-currency warning is logged under ``console``'s logger.

_ModelPricing = ModelPricing
_pricing_currency = pricing_currency
_lookup_pricing = lookup_pricing
_token_cost = token_cost
_run_cost = run_cost


def _build_pricing_map() -> dict[str, ModelPricing]:
    """Collect per-model prices from ``models[*].pricing`` in config.yaml."""
    try:
        models = get_app_config().models
    except Exception:  # pragma: no cover - defensive: cost display must not break the console
        logger.warning("console: failed to load model pricing from config", exc_info=True)
        return {}
    return build_pricing_map(models, logger=logger)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/stats",
    response_model=ConsoleStatsResponse,
    summary="Console Stats",
    description="Headline counters (runs, threads, agents, tokens) scoped to the current user.",
)
@require_permission("runs", "read")
async def console_stats(request: Request) -> ConsoleStatsResponse:
    """Return the dashboard's headline counters."""
    sf = _session_factory_or_503()
    user_id = await get_current_user(request)
    run_where = (RunRow.operation_kind == "run",)
    if user_id:
        run_where += (RunRow.user_id == user_id,)
    thread_where = (ThreadMetaRow.user_id == user_id,) if user_id else ()

    pricing = _build_pricing_map()

    async with sf() as session:
        total_runs = await session.scalar(select(func.count()).select_from(RunRow).where(*run_where)) or 0
        active_runs = await session.scalar(select(func.count()).select_from(RunRow).where(RunRow.status.in_(_ACTIVE_STATUSES), *run_where)) or 0
        failed_runs = await session.scalar(select(func.count()).select_from(RunRow).where(RunRow.status.in_(_FAILED_STATUSES), *run_where)) or 0
        total_tokens = await session.scalar(select(func.coalesce(func.sum(RunRow.total_tokens), 0)).where(*run_where)) or 0
        total_threads = await session.scalar(select(func.count()).select_from(ThreadMetaRow).where(*thread_where)) or 0

        total_cost: float | None = None
        if pricing:
            cost_rows = (
                await session.execute(
                    select(
                        RunRow.model_name,
                        RunRow.total_input_tokens,
                        RunRow.total_output_tokens,
                        RunRow.token_usage_by_model,
                    ).where(*run_where)
                )
            ).all()
            cost_sum = 0.0
            for model_name, input_tokens, output_tokens, usage_map in cost_rows:
                cost = _run_cost(
                    pricing,
                    model_name=model_name,
                    total_input_tokens=input_tokens,
                    total_output_tokens=output_tokens,
                    token_usage_by_model=usage_map,
                )
                if cost is not None:
                    cost_sum += cost
            total_cost = round(cost_sum, 6)

    try:
        # Filesystem scan; resolves the effective user internally (AuthMiddleware
        # sets the context for real requests, "default" in no-auth mode).
        agents = await asyncio.to_thread(list_custom_agents)
        total_agents = len(agents)
    except Exception:  # pragma: no cover - defensive: stats must not 500 on a bad agents dir
        logger.warning("console_stats: failed to list custom agents", exc_info=True)
        total_agents = 0

    return ConsoleStatsResponse(
        total_runs=total_runs,
        active_runs=active_runs,
        failed_runs=failed_runs,
        total_threads=total_threads,
        total_agents=total_agents,
        total_tokens=total_tokens,
        total_cost=total_cost,
        currency=_pricing_currency(pricing),
    )


@router.get(
    "/runs",
    response_model=ConsoleRunsResponse,
    summary="List Runs Across Threads",
    description="Cross-thread run history for the current user, newest first, joined with thread titles.",
)
@require_permission("runs", "read")
async def console_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, description="Filter by run status (e.g. running, success, error)"),
) -> ConsoleRunsResponse:
    """Return a page of the user's runs across all threads."""
    sf = _session_factory_or_503()
    user_id = await get_current_user(request)

    stmt = (
        select(RunRow, ThreadMetaRow.display_name)
        .join(ThreadMetaRow, ThreadMetaRow.thread_id == RunRow.thread_id, isouter=True)
        .where(RunRow.operation_kind == "run")
        .order_by(RunRow.created_at.desc(), RunRow.run_id.desc())
        .limit(limit + 1)
        .offset(offset)
    )
    if user_id:
        stmt = stmt.where(RunRow.user_id == user_id)
    if status:
        stmt = stmt.where(RunRow.status == status)

    async with sf() as session:
        rows = (await session.execute(stmt)).all()

    pricing = _build_pricing_map()
    has_more = len(rows) > limit
    now = datetime.now(UTC)
    items: list[ConsoleRunItem] = []
    for row, display_name in rows[:limit]:
        created = _as_utc(row.created_at)
        updated = _as_utc(row.updated_at)
        if row.status in _ACTIVE_STATUSES:
            duration = (now - created).total_seconds() if created else None
        else:
            duration = (updated - created).total_seconds() if created and updated else None
        cost = _run_cost(
            pricing,
            model_name=row.model_name,
            total_input_tokens=row.total_input_tokens,
            total_output_tokens=row.total_output_tokens,
            token_usage_by_model=row.token_usage_by_model,
        )
        items.append(
            ConsoleRunItem(
                run_id=row.run_id,
                thread_id=row.thread_id,
                thread_title=display_name,
                assistant_id=row.assistant_id,
                status=row.status,
                model_name=row.model_name,
                created_at=created,
                updated_at=updated,
                duration_seconds=max(duration, 0.0) if duration is not None else None,
                total_tokens=row.total_tokens or 0,
                message_count=row.message_count or 0,
                cost=round(cost, 6) if cost is not None else None,
                error=row.error[:_ERROR_EXCERPT_CHARS] if row.error else None,
            )
        )
    return ConsoleRunsResponse(runs=items, has_more=has_more)


@router.get(
    "/usage",
    response_model=ConsoleUsageResponse,
    summary="Token Usage Over Time",
    description="Daily token-usage series (zero-filled) plus per-model breakdown over the requested window.",
)
@require_permission("runs", "read")
async def console_usage(
    request: Request,
    days: int = Query(default=14, ge=1, le=90),
    tz_offset_minutes: int = Query(default=0, ge=-840, le=840, description="Local-time offset from UTC for day bucketing"),
) -> ConsoleUsageResponse:
    """Aggregate token usage by local day and by model."""
    sf = _session_factory_or_503()
    user_id = await get_current_user(request)

    tz_delta = timedelta(minutes=tz_offset_minutes)
    today_local = (datetime.now(UTC) + tz_delta).date()
    start_local = today_local - timedelta(days=days - 1)
    window_start_utc = datetime.combine(start_local, time.min, tzinfo=UTC) - tz_delta

    stmt = select(RunRow).where(RunRow.operation_kind == "run", RunRow.created_at >= window_start_utc)
    if user_id:
        stmt = stmt.where(RunRow.user_id == user_id)

    async with sf() as session:
        rows = (await session.execute(stmt)).scalars().all()

    day_buckets: dict[str, ConsoleUsageDay] = {}
    for i in range(days):
        d = (start_local + timedelta(days=i)).isoformat()
        day_buckets[d] = ConsoleUsageDay(date=d)

    pricing = _build_pricing_map()
    by_model: dict[str, ConsoleUsageModelBreakdown] = {}
    total_tokens = 0
    total_runs = 0
    total_cost = 0.0 if pricing else None
    for row in rows:
        created = _as_utc(row.created_at)
        if created is None:
            continue
        local_date = ((created + tz_delta).date()).isoformat()
        bucket = day_buckets.get(local_date)
        if bucket is None:
            # Row sits just outside the local window (UTC-window over-fetch); skip.
            continue
        run_tokens = row.total_tokens or 0
        bucket.total_tokens += run_tokens
        bucket.input_tokens += row.total_input_tokens or 0
        bucket.output_tokens += row.total_output_tokens or 0
        bucket.runs += 1
        total_tokens += run_tokens
        total_runs += 1

        run_cost = _run_cost(
            pricing,
            model_name=row.model_name,
            total_input_tokens=row.total_input_tokens,
            total_output_tokens=row.total_output_tokens,
            token_usage_by_model=row.token_usage_by_model,
        )
        if run_cost is not None and total_cost is not None:
            bucket.cost = round(bucket.cost + run_cost, 6)
            total_cost = round(total_cost + run_cost, 6)

        usage_map = row.token_usage_by_model or {}
        if isinstance(usage_map, dict) and usage_map:
            for model, usage in usage_map.items():
                entry = by_model.setdefault(model, ConsoleUsageModelBreakdown())
                entry.runs += 1
                if not isinstance(usage, dict):
                    continue
                entry.tokens += int(usage.get("total_tokens", 0) or 0)
                entry.input_tokens += int(usage.get("input_tokens") or 0)
                entry.cache_read_tokens += int(usage.get("cache_read_tokens") or 0)
                price = _lookup_pricing(pricing, model)
                if price is not None:
                    model_cost = _token_cost(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), price, int(usage.get("cache_read_tokens") or 0))
                    entry.cost = round((entry.cost or 0.0) + model_cost, 6)
        elif row.model_name and run_tokens > 0:
            # Legacy rows predating token_usage_by_model: fall back to the run's model.
            entry = by_model.setdefault(row.model_name, ConsoleUsageModelBreakdown())
            entry.tokens += run_tokens
            entry.runs += 1
            if run_cost is not None:
                entry.cost = round((entry.cost or 0.0) + run_cost, 6)

    return ConsoleUsageResponse(
        days=list(day_buckets.values()),
        by_model=by_model,
        total_tokens=total_tokens,
        total_runs=total_runs,
        total_cost=total_cost,
        currency=_pricing_currency(pricing),
    )
