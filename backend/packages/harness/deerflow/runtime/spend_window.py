"""Window boundaries for currency-denominated spend caps.

Pure date math, kept out of the Gateway so the boundary rule is unit-testable
on its own and identical wherever spend is summed (admission check, in-run
middleware, header figure, spend report).

Two modes, both configured by ``spend_budget.window``:

* ``rolling`` — "the last 24 hours / 7 days / 30 days from now". The same
  instant everywhere, so the timezone offset is irrelevant.
* ``calendar`` — "since local midnight / local Monday / the local 1st". The
  boundary depends on the operator's timezone, which is config
  (``spend_budget.tz_offset_minutes``) rather than a request parameter, because
  enforcement runs server-side with no browser to ask.

Every returned value is timezone-aware UTC, so callers can compare it directly
against ``runs.created_at`` (normalized to UTC) without another conversion.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

# Rolling window lengths. "monthly" is 30 days rather than a calendar month —
# a rolling window has no month to be relative to; pick ``calendar`` mode for
# true month boundaries.
_ROLLING_SPANS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

VALID_PERIODS = tuple(_ROLLING_SPANS)


def resolve_window_start(period: str, mode: str, now: datetime, tz_offset_minutes: int = 0) -> datetime:
    """Return the UTC instant at which *period*'s current window opened.

    Args:
        period: ``"daily"``, ``"weekly"`` or ``"monthly"``.
        mode: ``"rolling"`` or ``"calendar"``.
        now: Reference instant (UTC-aware; naive input is read as UTC).
        tz_offset_minutes: Local offset from UTC, used only in calendar mode.

    Raises:
        ValueError: for an unknown *period*.
    """
    span = _ROLLING_SPANS.get(period)
    if span is None:
        raise ValueError(f"unknown spend budget period: {period!r} (expected one of {', '.join(VALID_PERIODS)})")

    reference = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    reference = reference.astimezone(UTC)

    if mode != "calendar":
        return reference - span

    offset = timedelta(minutes=tz_offset_minutes)
    local = reference + offset
    if period == "daily":
        local_start = datetime.combine(local.date(), time.min, tzinfo=UTC)
    elif period == "weekly":
        # ISO weeks start on Monday; ``weekday()`` is 0 for Monday.
        local_start = datetime.combine(local.date() - timedelta(days=local.weekday()), time.min, tzinfo=UTC)
    else:
        local_start = datetime.combine(local.date().replace(day=1), time.min, tzinfo=UTC)
    return local_start - offset
