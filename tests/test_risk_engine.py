import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aistock.config import RiskLimits
from aistock.portfolio import Portfolio
from aistock.risk import RiskEngine, RiskViolation


class RiskEngineTests(unittest.TestCase):
    def test_daily_loss_limit_trips_halt(self):
        portfolio = Portfolio(cash=Decimal("100000"))
        limits = RiskLimits(max_daily_loss_pct=0.01, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        equity = Decimal("100000")
        last_prices = {"AAPL": Decimal("100")}
        risk.register_trade(Decimal("-2000"), Decimal("0"), timestamp, equity + Decimal("-2000"), last_prices)
        self.assertTrue(risk.is_halted())
        self.assertIn("Daily loss", risk.halt_reason())

    def test_pre_trade_position_limit(self):
        portfolio = Portfolio(cash=Decimal("100000"))
        limits = RiskLimits(max_position_fraction=0.10, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        last_prices = {"AAPL": Decimal("100")}
        risk._ensure_reset(timestamp, Decimal("100000"))
        with self.assertRaises(RiskViolation):
            risk.check_pre_trade("AAPL", Decimal("20"), Decimal("1000"), Decimal("100000"), last_prices)

    def test_halt_allows_flattening_only(self):
        portfolio = Portfolio(cash=Decimal("100000"))
        limits = RiskLimits(max_position_fraction=0.5, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        last_prices = {"AAPL": Decimal("100")}
        risk._ensure_reset(timestamp, Decimal("100000"))
        portfolio.apply_fill("AAPL", Decimal("10"), Decimal("100"), Decimal("0"), timestamp)
        risk.halt("Triggered for test")

        # Flattening trades should pass.
        try:
            risk.check_pre_trade("AAPL", Decimal("-10"), Decimal("100"), Decimal("100000"), last_prices)
        except RiskViolation as exc:  # pragma: no cover - explicit failure path
            self.fail(f"Flattening trade should be allowed while halted: {exc}")

        # Increasing exposure must still be blocked.
        with self.assertRaises(RiskViolation):
            risk.check_pre_trade("AAPL", Decimal("5"), Decimal("100"), Decimal("100000"), last_prices)

        # Reversals are also blocked.
        with self.assertRaises(RiskViolation):
            risk.check_pre_trade("AAPL", Decimal("-20"), Decimal("100"), Decimal("100000"), last_prices)

    def test_daily_loss_uses_start_of_day_equity(self):
        portfolio = Portfolio(cash=Decimal("100000"))
        limits = RiskLimits(max_daily_loss_pct=0.01, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
        last_prices = {}
        risk._ensure_reset(timestamp, Decimal("100000"))
        risk.state.peak_equity = Decimal("120000")  # prior high-water mark

        risk.register_trade(Decimal("-1100"), Decimal("0"), timestamp, Decimal("98800"), last_prices)
        self.assertTrue(risk.is_halted())
        self.assertIn("Daily loss", risk.halt_reason())

    def test_max_position_fraction_applies_to_projected_position(self):
        portfolio = Portfolio(cash=Decimal("100000"))
        limits = RiskLimits(max_position_fraction=0.20, max_drawdown_pct=0.5)
        risk = RiskEngine(limits, portfolio, bar_interval=timedelta(minutes=1))
        timestamp = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        last_prices = {"AAPL": Decimal("100")}

        risk._ensure_reset(timestamp, Decimal("100000"))
        portfolio.apply_fill("AAPL", Decimal("190"), Decimal("100"), Decimal("0"), timestamp)
        equity = portfolio.total_equity(last_prices)
        self.assertEqual(equity, Decimal("100000"))

        with self.assertRaises(RiskViolation):
            risk.check_pre_trade("AAPL", Decimal("20"), Decimal("100"), equity, last_prices)

        # Exactly to the cap (200 shares) should remain allowed.
        risk.check_pre_trade("AAPL", Decimal("10"), Decimal("100"), equity, last_prices)


if __name__ == "__main__":
    unittest.main()
