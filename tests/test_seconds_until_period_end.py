"""Unit tests for :func:`asyncbalancer.utils.seconds_until_period_end`.

Expected TTL values are fixed integers (golden numbers), not derived by reimplementing period logic.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from zoneinfo import ZoneInfo

from asyncbalancer.utils import seconds_until_period_end

UTC = ZoneInfo("UTC")
WARSAW = ZoneInfo("Europe/Warsaw")


def test_secondly_int_truncation_yields_zero_then_clamped_to_one() -> None:
    # 2024-06-01 12:34:56.500000 UTC → end of second 12:34:56.999999; int(delta seconds) == 0 → min 1
    now = datetime(2024, 6, 1, 12, 34, 56, 500_000, tzinfo=UTC)
    assert seconds_until_period_end("secondly", UTC, now) == 1


def test_secondly_another_subsecond_case_still_one() -> None:
    now = datetime(2024, 6, 1, 12, 34, 56, 1, tzinfo=UTC)
    assert seconds_until_period_end("secondly", UTC, now) == 1


def test_minutely_to_end_of_same_minute() -> None:
    now = datetime(2024, 6, 1, 12, 34, 5, 123_456, tzinfo=UTC)
    assert seconds_until_period_end("minutely", UTC, now) == 54


def test_minutely_last_fraction_of_last_second_clamped_to_one() -> None:
    now = datetime(2024, 6, 1, 12, 34, 59, 999_000, tzinfo=UTC)
    assert seconds_until_period_end("minutely", UTC, now) == 1


def test_hourly_to_end_of_same_hour() -> None:
    now = datetime(2024, 6, 1, 12, 5, 30, 0, tzinfo=UTC)
    assert seconds_until_period_end("hourly", UTC, now) == 3269


def test_hourly_last_second_of_hour_clamped_to_one() -> None:
    now = datetime(2024, 6, 1, 12, 59, 59, 0, tzinfo=UTC)
    assert seconds_until_period_end("hourly", UTC, now) == 1


def test_daily_end_same_calendar_day_utc() -> None:
    now = datetime(2024, 6, 15, 10, 30, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("daily", UTC, now) == 48599


def test_daily_now_converted_to_zone_for_day_boundary() -> None:
    # 2024-01-15 23:30 UTC → 2024-01-16 00:30 in Europe/Warsaw (CET); day ends 2024-01-16 23:59:59.999999 Warsaw
    now = datetime(2024, 1, 15, 23, 30, 0, tzinfo=UTC)
    assert seconds_until_period_end("daily", WARSAW, now) == 84599


def test_weekly_from_monday_noon_to_sunday_end() -> None:
    # 2024-01-01 is Monday UTC
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("weekly", UTC, now) == 561599


def test_weekly_from_sunday_morning_to_sunday_end_same_week() -> None:
    now = datetime(2024, 1, 7, 10, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("weekly", UTC, now) == 50399


def test_weekly_from_wednesday_morning_to_sunday_end() -> None:
    now = datetime(2024, 1, 3, 9, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("weekly", UTC, now) == 399599


def test_monthly_january_to_jan_31_end() -> None:
    now = datetime(2024, 1, 10, 8, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("monthly", UTC, now) == 1871999


def test_monthly_february_leap_year_to_feb_29_end() -> None:
    now = datetime(2024, 2, 10, 0, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("monthly", UTC, now) == 1727999


def test_monthly_december_to_dec_31_end() -> None:
    now = datetime(2024, 12, 1, 0, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("monthly", UTC, now) == 2678399


def test_quarterly_q1_jan_to_mar_31_end() -> None:
    now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("quarterly", UTC, now) == 6609599


def test_quarterly_q2_apr_to_jun_30_end() -> None:
    now = datetime(2024, 4, 1, 0, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("quarterly", UTC, now) == 7862399


def test_quarterly_q3_jul_to_sep_30_end() -> None:
    now = datetime(2024, 7, 10, 6, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("quarterly", UTC, now) == 7149599


def test_quarterly_q4_oct_to_dec_31_end() -> None:
    now = datetime(2024, 10, 5, 0, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("quarterly", UTC, now) == 7603199


def test_yearly_mid_year_to_dec_31_end() -> None:
    now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("yearly", UTC, now) == 17236799


def test_yearly_late_december_to_dec_31_end() -> None:
    now = datetime(2024, 12, 30, 0, 0, 0, tzinfo=UTC)
    assert seconds_until_period_end("yearly", UTC, now) == 172799


def test_uses_live_clock_when_now_omitted() -> None:
    # Only checks callability; value is not asserted (non-deterministic).
    assert seconds_until_period_end("secondly", UTC) >= 1


def test_unsupported_period_raises() -> None:
    now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="Unsupported period 'decadely'"):
        seconds_until_period_end("decadely", UTC, now)


def test_naive_now_raises() -> None:
    now = datetime(2024, 1, 1, 0, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        seconds_until_period_end("daily", UTC, now)
