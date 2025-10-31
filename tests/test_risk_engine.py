import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aistock.config import RiskLimits
from aistock.portfolio import Portfolio
from aistock.risk import RiskEngine, RiskViolation


class RiskEngineTests(unittest.TestCase):
    def test_daily_loss_limit_trips_halt(self):
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(max_daily_loss_pct=0.01, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        equity = Decimal('100000')
        last_prices = {'AAPL': Decimal('100')}
        risk.register_trade(Decimal('-2000'), Decimal('0'), timestamp, equity + Decimal('-2000'), last_prices)
        self.assertTrue(risk.is_halted())
        self.assertIn('Daily loss', risk.halt_reason())

    def test_pre_trade_position_limit(self):
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(max_position_fraction=0.10, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        last_prices = {'AAPL': Decimal('100')}
        risk._ensure_reset(timestamp, Decimal('100000'))
        with self.assertRaises(RiskViolation):
            risk.check_pre_trade('AAPL', Decimal('20'), Decimal('1000'), Decimal('100000'), last_prices)

    def test_halt_allows_flattening_only(self):
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(max_position_fraction=0.5, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        last_prices = {'AAPL': Decimal('100')}
        risk._ensure_reset(timestamp, Decimal('100000'))
        portfolio.apply_fill('AAPL', Decimal('10'), Decimal('100'), Decimal('0'), timestamp)
        risk.halt('Triggered for test')

        # Flattening trades should pass.
        try:
            risk.check_pre_trade('AAPL', Decimal('-10'), Decimal('100'), Decimal('100000'), last_prices)
        except RiskViolation as exc:  # pragma: no cover - explicit failure path
            self.fail(f'Flattening trade should be allowed while halted: {exc}')

        # Increasing exposure must still be blocked.
        with self.assertRaises(RiskViolation):
            risk.check_pre_trade('AAPL', Decimal('5'), Decimal('100'), Decimal('100000'), last_prices)

        # Reversals are also blocked.
        with self.assertRaises(RiskViolation):
            risk.check_pre_trade('AAPL', Decimal('-20'), Decimal('100'), Decimal('100000'), last_prices)

    def test_daily_loss_uses_start_of_day_equity(self):
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(max_daily_loss_pct=0.01, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
        last_prices = {}
        risk._ensure_reset(timestamp, Decimal('100000'))
        risk.state.peak_equity = Decimal('120000')  # prior high-water mark

        risk.register_trade(Decimal('-1100'), Decimal('0'), timestamp, Decimal('98800'), last_prices)
        self.assertTrue(risk.is_halted())
        self.assertIn('Daily loss', risk.halt_reason())

    def test_max_position_fraction_applies_to_projected_position(self):
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(max_position_fraction=0.20, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        last_prices = {'AAPL': Decimal('100')}

        risk._ensure_reset(timestamp, Decimal('100000'))
        portfolio.apply_fill('AAPL', Decimal('190'), Decimal('100'), Decimal('0'), timestamp)
        equity = portfolio.total_equity(last_prices)
        self.assertEqual(equity, Decimal('100000'))

        with self.assertRaises(RiskViolation):
            risk.check_pre_trade('AAPL', Decimal('20'), Decimal('100'), equity, last_prices)

        # Exactly to the cap (200 shares) should remain allowed.
        risk.check_pre_trade('AAPL', Decimal('10'), Decimal('100'), equity, last_prices)

    def test_order_rate_limiting_per_minute(self):
        """P0 Fix: Test order rate limiting (per-minute limit)."""
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(
            max_orders_per_minute=3,
            max_orders_per_day=100,
            rate_limit_enabled=True,
        )
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        last_prices = {'AAPL': Decimal('100')}
        risk._ensure_reset(timestamp, Decimal('100000'))

        # First 3 orders should pass
        for i in range(3):
            ts = timestamp + timedelta(seconds=i * 10)
            risk.check_pre_trade('AAPL', Decimal('1'), Decimal('100'), Decimal('100000'), last_prices, timestamp=ts)
            risk._record_order_submission(ts)

        # 4th order within same minute should fail
        with self.assertRaises(RiskViolation) as ctx:
            ts = timestamp + timedelta(seconds=40)
            risk.check_pre_trade('AAPL', Decimal('1'), Decimal('100'), Decimal('100000'), last_prices, timestamp=ts)
        self.assertIn('rate limit', str(ctx.exception).lower())

        # After 1 minute, should be able to order again
        ts_after_minute = timestamp + timedelta(seconds=70)
        risk.check_pre_trade(
            'AAPL', Decimal('1'), Decimal('100'), Decimal('100000'), last_prices, timestamp=ts_after_minute
        )

    def test_order_rate_limiting_per_day(self):
        """P0 Fix: Test daily order limit."""
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(
            max_orders_per_minute=100,
            max_orders_per_day=5,
            rate_limit_enabled=True,
        )
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        last_prices = {'AAPL': Decimal('100')}
        risk._ensure_reset(timestamp, Decimal('100000'))

        # Simulate 5 orders (with sufficient spacing)
        for i in range(5):
            ts = timestamp + timedelta(minutes=i * 2)
            risk.check_pre_trade('AAPL', Decimal('1'), Decimal('100'), Decimal('100000'), last_prices, timestamp=ts)
            risk._record_order_submission(ts)

        # 6th order should fail (daily limit)
        with self.assertRaises(RiskViolation) as ctx:
            ts = timestamp + timedelta(minutes=20)
            risk.check_pre_trade('AAPL', Decimal('1'), Decimal('100'), Decimal('100000'), last_prices, timestamp=ts)
        self.assertIn('daily order limit', str(ctx.exception).lower())

    def test_order_rate_limiting_resets_daily(self):
        """P0 Fix: Test that order rate limits reset daily."""
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(
            max_orders_per_minute=10,
            max_orders_per_day=3,
            rate_limit_enabled=True,
        )
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        last_prices = {'AAPL': Decimal('100')}
        risk._ensure_reset(timestamp, Decimal('100000'))

        # Use up daily limit
        for i in range(3):
            ts = timestamp + timedelta(minutes=i * 2)
            risk.check_pre_trade('AAPL', Decimal('1'), Decimal('100'), Decimal('100000'), last_prices, timestamp=ts)
            risk._record_order_submission(ts)

        # Next day should reset
        next_day = datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc)
        risk._ensure_reset(next_day, Decimal('100000'))
        self.assertEqual(risk.state.daily_order_count, 0)
        self.assertEqual(len(risk.state.order_timestamps), 0)

        # Should be able to order again
        risk.check_pre_trade('AAPL', Decimal('1'), Decimal('100'), Decimal('100000'), last_prices, timestamp=next_day)

    def test_order_rate_limiting_disabled(self):
        """P0 Fix: Test that rate limiting can be disabled."""
        portfolio = Portfolio(cash=Decimal('100000'))
        limits = RiskLimits(
            max_orders_per_minute=1,
            max_orders_per_day=1,
            rate_limit_enabled=False,  # Disabled
        )
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        last_prices = {'AAPL': Decimal('100')}
        risk._ensure_reset(timestamp, Decimal('100000'))

        # Should allow unlimited orders when disabled
        for i in range(10):
            ts = timestamp + timedelta(seconds=i)
            risk.check_pre_trade('AAPL', Decimal('1'), Decimal('100'), Decimal('100000'), last_prices, timestamp=ts)
            risk._record_order_submission(ts)


if __name__ == '__main__':
    unittest.main()
