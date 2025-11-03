"""Regression tests for TradingEngine realized P&L calculation.

CRITICAL BUG FIX:
The original implementation ignored entry price and just calculated closed_qty * price,
which is the dollar value of the close, NOT the actual profit/loss. This invalidated
all backtesting and trading analytics.

These tests verify the corrected cost-basis tracking and P&L calculation.
"""

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from aistock.engine import TradingEngine


class RealizedPnLRegressionTests(unittest.TestCase):
    """Regression tests for realized P&L calculation bug fix."""

    def test_long_position_profit(self):
        """Verify long position realizes profit correctly."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Buy 100 shares at $50
        trade1 = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('50'),
            timestamp=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(trade1.realised_pnl, Decimal('0'))  # Opening position
        self.assertEqual(engine.cost_basis['AAPL'], Decimal('50'))

        # Sell 100 shares at $60 (profit = (60-50)*100 = $1000)
        trade2 = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-100'),
            price=Decimal('60'),
            timestamp=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        )

        # CRITICAL: Should realize $1000 profit, not $6000 (60*100)
        self.assertEqual(trade2.realised_pnl, Decimal('1000'))
        self.assertNotIn('AAPL', engine.cost_basis)  # Fully closed

    def test_long_position_loss(self):
        """Verify long position realizes loss correctly."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Buy 100 shares at $50
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('50'),
            timestamp=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
        )

        # Sell 100 shares at $45 (loss = (45-50)*100 = -$500)
        trade = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-100'),
            price=Decimal('45'),
            timestamp=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        )

        # Should realize $500 loss, not $4500 (45*100)
        self.assertEqual(trade.realised_pnl, Decimal('-500'))

    def test_short_position_profit(self):
        """Verify short position realizes profit correctly."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Sell short 100 shares at $50
        trade1 = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-100'),
            price=Decimal('50'),
            timestamp=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(trade1.realised_pnl, Decimal('0'))  # Opening position
        self.assertEqual(engine.cost_basis['AAPL'], Decimal('50'))

        # Cover short at $40 (profit = (50-40)*100 = $1000)
        trade2 = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('40'),
            timestamp=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        )

        # Should realize $1000 profit (short gains when price drops)
        self.assertEqual(trade2.realised_pnl, Decimal('1000'))

    def test_short_position_loss(self):
        """Verify short position realizes loss correctly."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Sell short 100 shares at $50
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-100'),
            price=Decimal('50'),
            timestamp=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
        )

        # Cover short at $60 (loss = (50-60)*100 = -$1000)
        trade = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('60'),
            timestamp=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        )

        # Should realize $1000 loss (short loses when price rises)
        self.assertEqual(trade.realised_pnl, Decimal('-1000'))

    def test_weighted_average_cost_basis(self):
        """Verify cost basis updates correctly when adding to positions."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Buy 100 shares at $50
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('50'),
            timestamp=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(engine.cost_basis['AAPL'], Decimal('50'))

        # Buy 100 more shares at $60
        # Weighted avg = (100*50 + 100*60) / 200 = 11000 / 200 = $55
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('60'),
            timestamp=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(engine.cost_basis['AAPL'], Decimal('55'))

        # Sell 200 shares at $65 (profit = (65-55)*200 = $2000)
        trade = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-200'),
            price=Decimal('65'),
            timestamp=datetime(2025, 1, 1, 11, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(trade.realised_pnl, Decimal('2000'))

    def test_partial_close(self):
        """Verify partial position closes calculate P&L correctly."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Buy 200 shares at $50
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('200'),
            price=Decimal('50'),
            timestamp=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
        )

        # Sell 100 shares at $60 (profit = (60-50)*100 = $1000)
        trade = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-100'),
            price=Decimal('60'),
            timestamp=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(trade.realised_pnl, Decimal('1000'))
        # Cost basis should remain $50 (reducing position doesn't change basis)
        self.assertEqual(engine.cost_basis['AAPL'], Decimal('50'))
        # Position should be 100
        self.assertEqual(engine.positions['AAPL'], Decimal('100'))

    def test_old_bug_comparison(self):
        """Document the old bug vs. corrected behavior."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Buy 100 shares at $50
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('50'),
            timestamp=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
        )

        # Sell 100 shares at $60
        trade = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-100'),
            price=Decimal('60'),
            timestamp=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        )

        # OLD BUG: realised_pnl = closed_qty * price = 100 * 60 = $6000 ❌
        # CORRECT: realised_pnl = (exit - entry) * qty = (60-50)*100 = $1000 ✅
        self.assertEqual(trade.realised_pnl, Decimal('1000'))
        self.assertNotEqual(trade.realised_pnl, Decimal('6000'))  # Old bug value


if __name__ == '__main__':
    unittest.main()
