"""Small shared helpers (time windows, TTL helpers, etc.)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Periods with a defined calendar window in :func:`get_period_window` (used for TTL and Redis).
_KNOWN_PERIOD_WINDOWS = frozenset(
    {"secondly", "minutely", "hourly", "daily", "weekly", "monthly", "quarterly", "yearly"}
)
_MICROSTEP = timedelta(microseconds=1)


def get_period_window(period: str, now: datetime) -> tuple[datetime, datetime]:
    """Return aligned ``[start, end)`` bounds for the usage window that contains ``now``.

    ``end`` is exclusive (first instant *after* the last inclusive moment of the period).

    Used when persisting counters in Redis: if ``created_at`` is before ``start``, usage is
    reset for the current window. For unknown ``period`` values, falls back to a one-second
    window starting at ``now``.
    """
    if period == "secondly":
        start = now.replace(microsecond=0)
        end = start + timedelta(seconds=1)
    elif period == "minutely":
        start = now.replace(second=0, microsecond=0)
        end = start + timedelta(minutes=1)
    elif period == "hourly":
        start = now.replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
    elif period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "weekly":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
    elif period == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    elif period == "quarterly":
        quarter_start_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(
            month=quarter_start_month,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        if quarter_start_month == 10:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=quarter_start_month + 3)
    elif period == "yearly":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1)
    else:
        start = now
        end = now + timedelta(seconds=1)

    return start, end


def period_end_inclusive(period: str, now: datetime) -> datetime:
    """Return the last inclusive timestamp of the period containing ``now``.

    Derived from :func:`get_period_window` as ``end_exclusive - 1 microsecond``, which matches
    the historical TTL definition (e.g. Sunday 23:59:59.999999 for ISO weeks, last day of
    month at 23:59:59.999999). Only defined for the same period names as
    :func:`seconds_until_period_end` supports.
    """
    if period not in _KNOWN_PERIOD_WINDOWS:
        raise ValueError(f"Unsupported period '{period}'.")
    _, end_exclusive = get_period_window(period, now)
    return end_exclusive - _MICROSTEP


def seconds_until_period_end(
    period: str,
    timezone: ZoneInfo,
    now: datetime | None = None,
) -> int:
    """Return whole seconds from ``now`` until the inclusive end of ``period`` in ``timezone``.

    If ``now`` is omitted, :func:`datetime.now` is used. Pass a fixed timezone-aware ``now`` as the
    third argument in tests to avoid depending on the real clock.
    """
    if now is None:
        now = datetime.now(timezone)
    elif now.tzinfo is None:
        raise ValueError("'now' must be timezone-aware.")
    else:
        now = now.astimezone(timezone)

    period_end = period_end_inclusive(period, now)
    ttl_seconds = int((period_end - now).total_seconds())
    return max(ttl_seconds, 1)
