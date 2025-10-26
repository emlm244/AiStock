import pathlib
import tempfile
import unittest
from datetime import timezone

from aistock.config import BacktestConfig, DataSource, EngineConfig, RiskLimits, StrategyConfig
from aistock.engine import BacktestRunner


class BacktestTests(unittest.TestCase):
    def test_backtest_runs_with_sample_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = pathlib.Path(tmpdir)
            sample = source_dir / "AAPL.csv"
            sample.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T09:30:00,100,101,99,100,1000\n"
                "2024-01-01T09:31:00,100,101,99,100.5,1000\n"
                "2024-01-01T09:32:00,100.5,101,100,101,1000\n"
                "2024-01-01T09:33:00,101,102,100,101.5,1000\n"
                "2024-01-01T09:34:00,101.5,102,100,100.5,1000\n",
                encoding="utf-8",
            )

            risk = RiskLimits(
                max_position_fraction=1.0,
                per_symbol_notional_cap=100_000,
                max_single_position_units=100_000,
            )
            config = BacktestConfig(
                data=DataSource(
                    path=str(source_dir),
                    timezone=timezone.utc,
                    symbols=["AAPL"],
                    warmup_bars=1,
                    enforce_trading_hours=False,  # P0 Fix: Disable for synthetic test data
                ),
                engine=EngineConfig(
                    risk=risk,
                    initial_equity=10_000,
                    commission_per_trade=0.0,
                    slippage_bps=0.0,
                    strategy=StrategyConfig(short_window=2, long_window=3),
                ),
            )
            result = BacktestRunner(config).run()
            self.assertTrue(result.trades)
            self.assertTrue(result.equity_curve)
            self.assertGreaterEqual(result.max_drawdown, 0)
            self.assertIn("sharpe", result.metrics)
if __name__ == "__main__":
    unittest.main()
