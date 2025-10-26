import tempfile
import unittest
from datetime import timezone
from pathlib import Path

from aistock.config import BacktestConfig, DataSource, EngineConfig, RiskLimits, StrategyConfig
from aistock.engine import BacktestRunner


class MultiAssetEngineTests(unittest.TestCase):
    def test_two_symbol_backtest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for symbol in ("AAPL", "MSFT"):
                path = Path(tmpdir) / f"{symbol}.csv"
                path.write_text(
                    "timestamp,open,high,low,close,volume\n"
                    "2024-01-01T09:30:00,100,101,99,100,1000\n"
                    "2024-01-01T09:31:00,101,102,100,101,1000\n",
                    encoding="utf-8",
                )

            risk = RiskLimits(
                max_position_fraction=1.0,
                per_symbol_notional_cap=100_000,
                max_single_position_units=100_000,
            )
            config = BacktestConfig(
                data=DataSource(
                    path=tmpdir,
                    timezone=timezone.utc,
                    symbols=["AAPL", "MSFT"],
                    warmup_bars=1,
                    enforce_trading_hours=False,  # P0 Fix: Disable for synthetic test data
                ),
                engine=EngineConfig(
                    risk=risk,
                    initial_equity=50_000,
                    commission_per_trade=0.0,
                    slippage_bps=0.0,
                    strategy=StrategyConfig(short_window=1, long_window=2),
                ),
            )
            result = BacktestRunner(config).run()
            self.assertGreaterEqual(len(result.trades), 2)
if __name__ == "__main__":
    unittest.main()
