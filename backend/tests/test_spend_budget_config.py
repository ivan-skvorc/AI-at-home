"""Tests for the ``spend_budget:`` config section and its window math.

Roadmap item 2: a budget denominated in the configured pricing currency rather
than in tokens, because in a fork whose premise is mixing Opus, Haiku and free
local Ollama in one session a token is not a unit of cost.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from deerflow.config.spend_budget_config import SpendBudgetConfig, SpendLimit
from deerflow.runtime.spend_window import resolve_window_start


class TestSpendBudgetConfig:
    def test_defaults_are_off(self):
        cfg = SpendBudgetConfig()
        assert cfg.enabled is False
        assert cfg.limits() == ()

    def test_limits_are_ordered_shortest_window_first(self):
        cfg = SpendBudgetConfig(enabled=True, daily_limit=5, weekly_limit=20, monthly_limit=50)
        assert cfg.limits() == (
            SpendLimit("daily", 5.0),
            SpendLimit("weekly", 20.0),
            SpendLimit("monthly", 50.0),
        )

    def test_a_single_limit_is_enough(self):
        cfg = SpendBudgetConfig(enabled=True, monthly_limit=25)
        assert cfg.limits() == (SpendLimit("monthly", 25.0),)

    def test_enabled_without_any_limit_is_a_config_error(self):
        # Turning the feature on and configuring nothing to enforce is a
        # mistake worth failing loudly at startup, not a silent no-op.
        with pytest.raises(ValidationError, match="at least one of daily_limit"):
            SpendBudgetConfig(enabled=True)

    def test_hard_stop_cannot_precede_the_warning(self):
        with pytest.raises(ValidationError, match="hard_stop_threshold must be >= warn_threshold"):
            SpendBudgetConfig(enabled=True, daily_limit=1, warn_threshold=0.9, hard_stop_threshold=0.5)

    def test_limits_must_be_positive(self):
        with pytest.raises(ValidationError):
            SpendBudgetConfig(enabled=True, daily_limit=0)
        with pytest.raises(ValidationError):
            SpendBudgetConfig(enabled=True, daily_limit=-1)

    def test_disabled_config_ignores_missing_limits(self):
        # The shipped default: present in config.yaml, off, nothing to enforce.
        assert SpendBudgetConfig(enabled=False).limits() == ()

    def test_window_mode_is_validated(self):
        assert SpendBudgetConfig(enabled=True, daily_limit=1, window="calendar").window == "calendar"
        with pytest.raises(ValidationError):
            SpendBudgetConfig(enabled=True, daily_limit=1, window="fortnightly")


class TestRollingWindows:
    now = datetime(2026, 8, 13, 14, 30, tzinfo=UTC)  # a Thursday

    def test_daily_is_the_last_24_hours(self):
        assert resolve_window_start("daily", "rolling", self.now) == datetime(2026, 8, 12, 14, 30, tzinfo=UTC)

    def test_weekly_is_the_last_7_days(self):
        assert resolve_window_start("weekly", "rolling", self.now) == datetime(2026, 8, 6, 14, 30, tzinfo=UTC)

    def test_monthly_is_the_last_30_days(self):
        assert resolve_window_start("monthly", "rolling", self.now) == datetime(2026, 7, 14, 14, 30, tzinfo=UTC)

    def test_rolling_ignores_the_timezone_offset(self):
        # A rolling window is "the last N hours from now", which is the same
        # instant in every timezone.
        assert resolve_window_start("daily", "rolling", self.now, tz_offset_minutes=330) == resolve_window_start("daily", "rolling", self.now)


class TestCalendarWindows:
    now = datetime(2026, 8, 13, 14, 30, tzinfo=UTC)  # Thursday

    def test_daily_is_local_midnight(self):
        assert resolve_window_start("daily", "calendar", self.now) == datetime(2026, 8, 13, 0, 0, tzinfo=UTC)

    def test_weekly_starts_on_monday(self):
        assert resolve_window_start("weekly", "calendar", self.now) == datetime(2026, 8, 10, 0, 0, tzinfo=UTC)

    def test_monthly_starts_on_the_first(self):
        assert resolve_window_start("monthly", "calendar", self.now) == datetime(2026, 8, 1, 0, 0, tzinfo=UTC)

    def test_offset_shifts_the_local_day_boundary(self):
        # UTC+5:30 — 14:30Z is 20:00 local on the 13th, so the local day began
        # at 00:00 local = 18:30Z on the 12th.
        assert resolve_window_start("daily", "calendar", self.now, tz_offset_minutes=330) == datetime(2026, 8, 12, 18, 30, tzinfo=UTC)

    def test_negative_offset_can_still_be_the_previous_local_day(self):
        # UTC-8 — 02:00Z on the 13th is 18:00 local on the 12th.
        early = datetime(2026, 8, 13, 2, 0, tzinfo=UTC)
        assert resolve_window_start("daily", "calendar", early, tz_offset_minutes=-480) == datetime(2026, 8, 12, 8, 0, tzinfo=UTC)

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError, match="unknown spend budget period"):
            resolve_window_start("hourly", "calendar", self.now)
