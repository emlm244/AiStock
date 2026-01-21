"""
Exchange calendar utilities for market hours and holiday validation.

This module provides dependency-free calendar logic for NYSE/NASDAQ using
vendored holiday data. No third-party packages required.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, time, timedelta, timezone

# NYSE/NASDAQ holidays through 2030 (static, deterministic)
# Format: (year, month, day)
_NYSE_HOLIDAYS = {
    # 2024
    (2024, 1, 1),
    (2024, 1, 15),
    (2024, 2, 19),
    (2024, 3, 29),
    (2024, 5, 27),
    (2024, 6, 19),
    (2024, 7, 4),
    (2024, 9, 2),
    (2024, 11, 28),
    (2024, 12, 25),
    # 2025
    (2025, 1, 1),
    (2025, 1, 20),
    (2025, 2, 17),
    (2025, 4, 18),
    (2025, 5, 26),
    (2025, 6, 19),
    (2025, 7, 4),
    (2025, 9, 1),
    (2025, 11, 27),
    (2025, 12, 25),
    # 2026
    (2026, 1, 1),
    (2026, 1, 19),
    (2026, 2, 16),
    (2026, 4, 3),
    (2026, 5, 25),
    (2026, 6, 19),
    (2026, 7, 3),
    (2026, 9, 7),
    (2026, 11, 26),
    (2026, 12, 25),
    # 2027
    (2027, 1, 1),
    (2027, 1, 18),
    (2027, 2, 15),
    (2027, 3, 26),
    (2027, 5, 31),
    (2027, 6, 18),
    (2027, 7, 5),
    (2027, 9, 6),
    (2027, 11, 25),
    (2027, 12, 24),
    # 2028
    (2028, 1, 17),
    (2028, 2, 21),
    (2028, 4, 14),
    (2028, 5, 29),
    (2028, 6, 19),
    (2028, 7, 4),
    (2028, 9, 4),
    (2028, 11, 23),
    (2028, 12, 25),
    # 2029
    (2029, 1, 1),
    (2029, 1, 15),
    (2029, 2, 19),
    (2029, 3, 30),
    (2029, 5, 28),
    (2029, 6, 19),
    (2029, 7, 4),
    (2029, 9, 3),
    (2029, 11, 22),
    (2029, 12, 25),
    # 2030
    (2030, 1, 1),
    (2030, 1, 21),
    (2030, 2, 18),
    (2030, 4, 19),
    (2030, 5, 27),
    (2030, 6, 19),
    (2030, 7, 4),
    (2030, 9, 2),
    (2030, 11, 28),
    (2030, 12, 25),
}

# Early close days (1:00 PM ET close) - day before or after major holidays
_NYSE_EARLY_CLOSE = {
    (2024, 7, 3),
    (2024, 11, 29),
    (2024, 12, 24),
    (2025, 7, 3),
    (2025, 11, 28),
    (2025, 12, 24),
    (2026, 11, 27),
    (2026, 12, 24),
    (2027, 11, 26),
    (2028, 7, 3),
    (2028, 11, 24),
    (2028, 12, 22),
    (2029, 7, 3),
    (2029, 11, 23),
    (2029, 12, 24),
    (2030, 7, 3),
    (2030, 11, 29),
    (2030, 12, 24),
}


def _is_dst(dt: datetime) -> bool:
    """
    Check if a datetime falls within US Daylight Saving Time.

    DST rules: Second Sunday in March 2am to first Sunday in November 2am.
    """
    year = dt.year
    # Find second Sunday in March
    march_1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    days_to_sunday = (6 - march_1.weekday()) % 7
    first_sunday_march = march_1 + timedelta(days=days_to_sunday)
    dst_start = first_sunday_march + timedelta(days=7, hours=7)  # 2am ET = 7am UTC

    # Find first Sunday in November
    nov_1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    days_to_sunday = (6 - nov_1.weekday()) % 7
    first_sunday_nov = nov_1 + timedelta(days=days_to_sunday)
    dst_end = first_sunday_nov + timedelta(hours=6)  # 2am EST = 6am UTC (1am EDT = 6am UTC)

    return dst_start <= dt < dst_end


def _utc_to_et(dt: datetime) -> datetime:
    """Convert UTC datetime to US Eastern Time (accounting for DST)."""
    offset = timedelta(hours=-4) if _is_dst(dt) else timedelta(hours=-5)
    return dt + offset


def is_nyse_holiday(dt: datetime) -> bool:
    """Check if a date is a NYSE holiday."""
    date_tuple = (dt.year, dt.month, dt.day)
    return date_tuple in _NYSE_HOLIDAYS


def is_nyse_early_close(dt: datetime) -> bool:
    """Check if a date is a NYSE early close day (1:00 PM ET close)."""
    date_tuple = (dt.year, dt.month, dt.day)
    return date_tuple in _NYSE_EARLY_CLOSE


def is_weekend(dt: datetime) -> bool:
    """Check if datetime falls on Saturday (5) or Sunday (6)."""
    return dt.weekday() >= 5


def nyse_trading_hours(dt: datetime) -> tuple[time, time]:
    """
    Return (open_time, close_time) in ET for a given date.

    Regular hours: 9:30 AM - 4:00 PM ET
    Early close: 9:30 AM - 1:00 PM ET
    """
    if is_nyse_early_close(dt):
        return (time(9, 30), time(13, 0))  # 1:00 PM ET
    return (time(9, 30), time(16, 0))  # 4:00 PM ET


def is_trading_time(
    dt: datetime,
    exchange: str = 'NYSE',
    allow_extended_hours: bool = False,
) -> bool:
    """
    Check if a UTC timestamp falls within regular trading hours.

    Args:
        dt: UTC datetime to check
        exchange: Exchange name (currently only NYSE/NASDAQ supported)
        allow_extended_hours: If True, allow pre-market (4am-9:30am) and after-hours (4pm-8pm)

    Returns:
        True if market is open for trading at this time
    """
    if exchange.upper() not in {'NYSE', 'NASDAQ'}:
        raise ValueError(f'Unsupported exchange: {exchange}')

    # Convert to Eastern Time
    et_time = _utc_to_et(dt)

    # Check if it's a weekend
    if is_weekend(dt):
        return False

    # Check if it's a holiday
    if is_nyse_holiday(dt):
        return False

    # Get trading hours for this day
    open_time, close_time = nyse_trading_hours(dt)
    current_time = et_time.time()

    if allow_extended_hours:
        # Extended hours: 4am - 8pm ET
        extended_open = time(4, 0)
        extended_close = time(20, 0)
        return extended_open <= current_time <= extended_close

    # Regular hours check
    return open_time <= current_time <= close_time


def is_within_open_close_buffer(
    dt: datetime,
    minutes_from_open: int,
    minutes_from_close: int,
    exchange: str = 'NYSE',
) -> bool:
    """Check if a time is within the open/close avoidance buffer (regular session only)."""
    if minutes_from_open <= 0 and minutes_from_close <= 0:
        return False
    if exchange.upper() not in {'NYSE', 'NASDAQ'}:
        raise ValueError(f'Unsupported exchange: {exchange}')
    if is_weekend(dt) or is_nyse_holiday(dt):
        return False

    et_time = _utc_to_et(dt)
    open_time, close_time = nyse_trading_hours(dt)
    current_time = et_time.time()
    if not (open_time <= current_time <= close_time):
        return False

    session_date = et_time.date()
    open_dt = datetime.combine(session_date, open_time)
    close_dt = datetime.combine(session_date, close_time)
    return (minutes_from_open > 0 and current_time < (open_dt + timedelta(minutes=minutes_from_open)).time()) or (
        minutes_from_close > 0 and current_time > (close_dt - timedelta(minutes=minutes_from_close)).time()
    )


def next_trading_day(dt: datetime, exchange: str = 'NYSE') -> datetime:
    """
    Find the next trading day after the given datetime.

    Returns datetime at market open (9:30 AM ET in UTC).
    """
    candidate = dt + timedelta(days=1)
    candidate = candidate.replace(hour=14, minute=30, second=0, microsecond=0)  # 9:30 AM ET in UTC (approximate)

    # Adjust for DST
    candidate = candidate.replace(hour=13, minute=30) if _is_dst(candidate) else candidate.replace(hour=14, minute=30)

    max_attempts = 10
    for _ in range(max_attempts):
        if is_weekend(candidate):
            # Skip to Monday
            days_to_monday = (7 - candidate.weekday()) % 7
            if days_to_monday == 0:
                days_to_monday = 1
            candidate += timedelta(days=days_to_monday)
        elif is_nyse_holiday(candidate):
            candidate += timedelta(days=1)
        else:
            return candidate

    # Fallback
    return candidate


def is_trading_day(d: _date, exchange: str = 'NYSE') -> bool:
    """Return True if the given date is a regular trading day (not weekend/holiday)."""
    # Normalize to UTC midnight for checks that expect datetime
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if exchange.upper() not in {'NYSE', 'NASDAQ'}:
        raise ValueError(f'Unsupported exchange: {exchange}')
    if is_weekend(dt):
        return False
    return not is_nyse_holiday(dt)


def filter_trading_hours(
    timestamps: list[datetime],
    exchange: str = 'NYSE',
    allow_extended_hours: bool = False,
) -> list[datetime]:
    """
    Filter a list of timestamps to only include trading hours.

    Useful for cleaning backtest data to exclude weekends/holidays/off-hours.
    """
    return [ts for ts in timestamps if is_trading_time(ts, exchange, allow_extended_hours)]
