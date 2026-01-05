import unittest
from datetime import datetime, timezone
from decimal import Decimal

from aistock.portfolio import Portfolio


class PortfolioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timestamp = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)

    def test_realised_pnl_on_long_close(self):
        portfolio = Portfolio(cash=Decimal('0'))
        portfolio.apply_fill('AAPL', Decimal('10'), Decimal('100'), Decimal('0'), self.timestamp)
        pnl = portfolio.apply_fill('AAPL', Decimal('-10'), Decimal('110'), Decimal('0'), self.timestamp)
        self.assertEqual(pnl, Decimal('100'))
        self.assertEqual(portfolio.position('AAPL').quantity, Decimal('0'))

    def test_partial_close_keeps_basis(self):
        portfolio = Portfolio(cash=Decimal('0'))
        portfolio.apply_fill('AAPL', Decimal('10'), Decimal('100'), Decimal('0'), self.timestamp)
        pnl = portfolio.apply_fill('AAPL', Decimal('-4'), Decimal('110'), Decimal('0'), self.timestamp)
        position = portfolio.position('AAPL')
        self.assertEqual(pnl, Decimal('40'))
        self.assertEqual(position.quantity, Decimal('6'))
        self.assertEqual(position.average_price, Decimal('100'))

    def test_short_cover_pnl_positive(self):
        portfolio = Portfolio(cash=Decimal('0'))
        portfolio.apply_fill('AAPL', Decimal('-10'), Decimal('100'), Decimal('0'), self.timestamp)
        pnl = portfolio.apply_fill('AAPL', Decimal('10'), Decimal('90'), Decimal('0'), self.timestamp)
        self.assertEqual(pnl, Decimal('100'))
        self.assertEqual(portfolio.position('AAPL').quantity, Decimal('0'))

    def test_reversal_sets_new_basis(self):
        portfolio = Portfolio(cash=Decimal('0'))
        portfolio.apply_fill('AAPL', Decimal('5'), Decimal('100'), Decimal('0'), self.timestamp)
        pnl = portfolio.apply_fill('AAPL', Decimal('-10'), Decimal('110'), Decimal('0'), self.timestamp)
        position = portfolio.position('AAPL')
        self.assertEqual(pnl, Decimal('50'))
        self.assertEqual(position.quantity, Decimal('-5'))
        self.assertEqual(position.average_price, Decimal('110'))


class FuturesMultiplierTests(unittest.TestCase):
    """Test futures P&L with contract multiplier."""

    def setUp(self) -> None:
        self.timestamp = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)

    def test_futures_pnl_with_multiplier(self):
        """Test that futures P&L uses contract multiplier correctly."""
        # Start with enough cash for ES futures (notional = 5200 * 50 = $260,000)
        portfolio = Portfolio(cash=Decimal('300000'))

        # Buy 1 ES at 5200, multiplier=50 → Notional = $260,000
        portfolio.apply_fill(
            'ES', Decimal('1'), Decimal('5200'), Decimal('0'), self.timestamp, multiplier=Decimal('50')
        )

        # Cash should decrease by notional
        self.assertEqual(portfolio.cash, Decimal('40000'))  # 300000 - 260000

        # Position avg_price should be original (not multiplied)
        self.assertEqual(portfolio.position('ES').average_price, Decimal('5200'))

        # Position should track multiplier
        self.assertEqual(portfolio.position('ES').multiplier, Decimal('50'))

    def test_futures_realized_pnl_with_multiplier(self):
        """Test realized P&L calculation with multiplier."""
        portfolio = Portfolio(cash=Decimal('300000'))

        # Buy 1 ES at 5200, multiplier=50
        portfolio.apply_fill(
            'ES', Decimal('1'), Decimal('5200'), Decimal('0'), self.timestamp, multiplier=Decimal('50')
        )

        # Sell at 5210 (10 point profit = 10 * 1 * 50 = $500)
        pnl = portfolio.apply_fill(
            'ES', Decimal('-1'), Decimal('5210'), Decimal('0'), self.timestamp, multiplier=Decimal('50')
        )

        # Realized P&L = (5210 - 5200) * 1 * 50 = $500
        self.assertEqual(pnl, Decimal('500'))

        # Cash should be: 300000 - 260000 (buy) + 260500 (sell) = 300500
        self.assertEqual(portfolio.cash, Decimal('300500'))

    def test_futures_equity_with_multiplier(self):
        """Test equity calculation uses position multiplier."""
        portfolio = Portfolio(cash=Decimal('300000'))

        # Buy 1 ES at 5200, multiplier=50
        portfolio.apply_fill(
            'ES', Decimal('1'), Decimal('5200'), Decimal('0'), self.timestamp, multiplier=Decimal('50')
        )

        # Cash = 40000, position notional at current price
        # If price moves to 5210, position value = 1 * 5210 * 50 = 260500
        last_prices = {'ES': Decimal('5210')}
        equity = portfolio.get_equity(last_prices)

        # Equity = cash + position_value = 40000 + 260500 = 300500
        self.assertEqual(equity, Decimal('300500'))

    def test_equities_default_multiplier(self):
        """Test that equities (no multiplier) work unchanged."""
        portfolio = Portfolio(cash=Decimal('10000'))

        # Buy 10 AAPL at 200 (no multiplier = default 1)
        portfolio.apply_fill('AAPL', Decimal('10'), Decimal('200'), Decimal('0'), self.timestamp)

        # Cash = 10000 - 2000 = 8000
        self.assertEqual(portfolio.cash, Decimal('8000'))

        # Position multiplier should be default 1
        self.assertEqual(portfolio.position('AAPL').multiplier, Decimal('1'))

        # Sell at 210 (10 point profit = 10 * 10 * 1 = $100)
        pnl = portfolio.apply_fill('AAPL', Decimal('-10'), Decimal('210'), Decimal('0'), self.timestamp)
        self.assertEqual(pnl, Decimal('100'))


if __name__ == '__main__':
    unittest.main()
