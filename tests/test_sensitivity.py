"""
Tests for transaction cost sensitivity analysis.

P1 Enhancement: Validate sensitivity grid computation.
"""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aistock.config import BacktestConfig, DataSource, EngineConfig, ExecutionConfig, RiskLimits
from aistock.data import Bar
from aistock.sensitivity import run_sensitivity_analysis


class SensitivityTests(unittest.TestCase):
    def test_sensitivity_grid_computation(self):
        """Test sensitivity analysis runs across parameter grid."""
        # Create minimal synthetic data
        base_time = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(
                "AAPL",
                base_time + timedelta(minutes=i),
                Decimal("100"),
                Decimal("101"),
                Decimal("99"),
                Decimal(str(100 + i * 0.1)),
                1000,
            )
            for i in range(100)
        ]

        config = BacktestConfig(
            data=DataSource(
                path="data",
                symbols=["AAPL"],
                warmup_bars=20,
                enforce_trading_hours=False,  # Synthetic data
            ),
            engine=EngineConfig(
                initial_equity=10_000,
                commission_per_trade=1.0,
                slippage_bps=5.0,
                risk=RiskLimits(max_daily_loss_pct=0.10),
            ),
        )

        # Run sensitivity (small grid for speed)
        analysis = run_sensitivity_analysis(
            config,
            override_data={"AAPL": bars},
            commission_range=(0.5, 2.0, 0.5),  # 4 points
            slippage_range=(2.0, 8.0, 3.0),  # 3 points
        )

        # Should have 4 * 3 = 12 grid points
        self.assertEqual(len(analysis.grid), 12)

        # Check all points have valid metrics
        for point in analysis.grid:
            self.assertGreaterEqual(point.commission, 0.5)
            self.assertLessEqual(point.commission, 2.0)
            self.assertGreaterEqual(point.slippage_bps, 2.0)
            self.assertLessEqual(point.slippage_bps, 8.0)
            self.assertIsInstance(point.sharpe, float)
            self.assertIsInstance(point.total_return, Decimal)

        # Check summary stats
        stats = analysis.summary_stats()
        self.assertIn("return_mean", stats)
        self.assertIn("sharpe_mean", stats)
        self.assertIsInstance(stats["return_mean"], float)


if __name__ == "__main__":
    unittest.main()
