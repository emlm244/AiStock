import unittest
from decimal import Decimal

from aistock.config import RiskLimits
from aistock.sizing import target_quantity


class SizingTests(unittest.TestCase):
    def test_per_trade_cap(self):
        limits = RiskLimits(per_trade_risk_pct=0.02)
        qty = target_quantity(Decimal("1"), Decimal("10000"), Decimal("100"), limits, confidence=1.0)
        self.assertEqual(qty, Decimal("2"))


if __name__ == "__main__":
    unittest.main()
