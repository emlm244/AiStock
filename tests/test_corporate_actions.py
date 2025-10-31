"""
Tests for corporate actions tracking.

P1 Enhancement: Validate split/dividend adjustments.
"""

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from aistock.corporate_actions import (
    ActionType,
    CorporateActionTracker,
    create_dividend,
    create_split,
)


class CorporateActionsTests(unittest.TestCase):
    def test_split_backward_adjustment(self):
        """Test split backward adjustment (pre-split prices divided by ratio)."""
        tracker = CorporateActionTracker()
        tracker.add_action(create_split('AAPL', date(2024, 8, 31), Decimal('4.0')))

        # Price before split should be adjusted
        pre_split_price = Decimal('500.0')
        pre_split_time = datetime(2024, 8, 30, 14, 30, tzinfo=timezone.utc)
        adjusted = tracker.adjust_price('AAPL', pre_split_price, pre_split_time)
        self.assertEqual(adjusted, Decimal('500.0') * Decimal('4.0'))  # Backward: multiply

        # Price after split should NOT be adjusted
        post_split_price = Decimal('125.0')
        post_split_time = datetime(2024, 9, 1, 14, 30, tzinfo=timezone.utc)
        adjusted = tracker.adjust_price('AAPL', post_split_price, post_split_time)
        self.assertEqual(adjusted, Decimal('125.0'))  # No adjustment

    def test_dividend_backward_adjustment(self):
        """Test dividend backward adjustment (pre-dividend prices + dividend)."""
        tracker = CorporateActionTracker()
        tracker.add_action(create_dividend('MSFT', date(2024, 2, 21), Decimal('0.75')))

        # Price before ex-dividend should be adjusted
        pre_div_price = Decimal('415.0')
        pre_div_time = datetime(2024, 2, 20, 14, 30, tzinfo=timezone.utc)
        adjusted = tracker.adjust_price('MSFT', pre_div_price, pre_div_time)
        self.assertEqual(adjusted, Decimal('415.0') + Decimal('0.75'))  # Add back dividend

        # Price on/after ex-dividend should NOT be adjusted
        post_div_price = Decimal('414.25')
        post_div_time = datetime(2024, 2, 21, 14, 30, tzinfo=timezone.utc)
        adjusted = tracker.adjust_price('MSFT', post_div_price, post_div_time)
        self.assertEqual(adjusted, Decimal('414.25'))  # No adjustment

    def test_check_for_action_on_date(self):
        """Test checking if action exists on specific date."""
        tracker = CorporateActionTracker()
        tracker.add_action(create_split('NVDA', date(2024, 6, 10), Decimal('10.0')))

        # Should find action on ex-date
        action = tracker.check_for_action('NVDA', datetime(2024, 6, 10, 9, 30, tzinfo=timezone.utc))
        self.assertIsNotNone(action)
        if action:  # Type guard for optional member access
            self.assertEqual(action.action_type, ActionType.SPLIT)
            self.assertEqual(action.ratio, Decimal('10.0'))

        # Should NOT find action on other dates
        no_action = tracker.check_for_action('NVDA', datetime(2024, 6, 9, 9, 30, tzinfo=timezone.utc))
        self.assertIsNone(no_action)

    def test_save_and_load_csv(self):
        """Test CSV persistence round-trip."""
        import tempfile

        tracker = CorporateActionTracker()
        tracker.add_action(create_split('AAPL', date(2024, 8, 31), Decimal('4.0'), '4-for-1 split'))
        tracker.add_action(create_dividend('MSFT', date(2024, 2, 21), Decimal('0.75'), 'Q1 dividend'))

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = f.name

        tracker.save_to_csv(temp_path)

        # Load and verify
        loaded = CorporateActionTracker.load_from_csv(temp_path)
        aapl_actions = loaded.get_actions('AAPL')
        msft_actions = loaded.get_actions('MSFT')

        self.assertEqual(len(aapl_actions), 1)
        self.assertEqual(len(msft_actions), 1)
        self.assertEqual(aapl_actions[0].ratio, Decimal('4.0'))
        self.assertEqual(msft_actions[0].amount, Decimal('0.75'))


if __name__ == '__main__':
    unittest.main()
