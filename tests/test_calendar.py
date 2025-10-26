import unittest
from datetime import datetime, timezone

from aistock.calendar import (
    is_nyse_early_close,
    is_nyse_holiday,
    is_trading_time,
    is_weekend,
    next_trading_day,
)


class CalendarTests(unittest.TestCase):
    def test_christmas_is_holiday(self):
        christmas = datetime(2024, 12, 25, 14, 30, tzinfo=timezone.utc)
        self.assertTrue(is_nyse_holiday(christmas))

    def test_regular_trading_day(self):
        tuesday = datetime(2024, 7, 9, 14, 30, tzinfo=timezone.utc)  # 9:30 AM ET
        self.assertFalse(is_nyse_holiday(tuesday))
        self.assertTrue(is_trading_time(tuesday))

    def test_weekend_not_trading(self):
        saturday = datetime(2024, 7, 6, 14, 30, tzinfo=timezone.utc)
        self.assertTrue(is_weekend(saturday))
        self.assertFalse(is_trading_time(saturday))

    def test_early_close(self):
        day_before_christmas = datetime(2024, 12, 24, 10, 0, tzinfo=timezone.utc)
        self.assertTrue(is_nyse_early_close(day_before_christmas))

    def test_after_hours_not_trading(self):
        after_hours = datetime(2024, 7, 9, 21, 0, tzinfo=timezone.utc)  # 5 PM ET
        self.assertFalse(is_trading_time(after_hours, allow_extended_hours=False))

    def test_next_trading_day_skips_weekend(self):
        friday_close = datetime(2024, 7, 5, 20, 0, tzinfo=timezone.utc)
        next_day = next_trading_day(friday_close)
        # Should skip Saturday/Sunday and land on Monday
        self.assertEqual(next_day.weekday(), 0)  # Monday


if __name__ == "__main__":
    unittest.main()
