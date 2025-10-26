import unittest
from datetime import datetime, timezone
from decimal import Decimal

from aistock.portfolio import Portfolio


class PortfolioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timestamp = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)

    def test_realised_pnl_on_long_close(self):
        portfolio = Portfolio(cash=Decimal("0"))
        portfolio.apply_fill("AAPL", Decimal("10"), Decimal("100"), Decimal("0"), self.timestamp)
        pnl = portfolio.apply_fill("AAPL", Decimal("-10"), Decimal("110"), Decimal("0"), self.timestamp)
        self.assertEqual(pnl, Decimal("100"))
        self.assertEqual(portfolio.position("AAPL").quantity, Decimal("0"))

    def test_partial_close_keeps_basis(self):
        portfolio = Portfolio(cash=Decimal("0"))
        portfolio.apply_fill("AAPL", Decimal("10"), Decimal("100"), Decimal("0"), self.timestamp)
        pnl = portfolio.apply_fill("AAPL", Decimal("-4"), Decimal("110"), Decimal("0"), self.timestamp)
        position = portfolio.position("AAPL")
        self.assertEqual(pnl, Decimal("40"))
        self.assertEqual(position.quantity, Decimal("6"))
        self.assertEqual(position.average_price, Decimal("100"))

    def test_short_cover_pnl_positive(self):
        portfolio = Portfolio(cash=Decimal("0"))
        portfolio.apply_fill("AAPL", Decimal("-10"), Decimal("100"), Decimal("0"), self.timestamp)
        pnl = portfolio.apply_fill("AAPL", Decimal("10"), Decimal("90"), Decimal("0"), self.timestamp)
        self.assertEqual(pnl, Decimal("100"))
        self.assertEqual(portfolio.position("AAPL").quantity, Decimal("0"))

    def test_reversal_sets_new_basis(self):
        portfolio = Portfolio(cash=Decimal("0"))
        portfolio.apply_fill("AAPL", Decimal("5"), Decimal("100"), Decimal("0"), self.timestamp)
        pnl = portfolio.apply_fill("AAPL", Decimal("-10"), Decimal("110"), Decimal("0"), self.timestamp)
        position = portfolio.position("AAPL")
        self.assertEqual(pnl, Decimal("50"))
        self.assertEqual(position.quantity, Decimal("-5"))
        self.assertEqual(position.average_price, Decimal("110"))


if __name__ == "__main__":
    unittest.main()
