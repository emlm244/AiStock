import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from aistock.config import DataQualityConfig, DataSource, UniverseConfig
from aistock.universe import UniverseSelector


def _write_series(path: str, start_price: float, step: float, volume: float) -> None:
    start_time = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        price = start_price
        for idx in range(20):
            ts = start_time + timedelta(minutes=idx)
            row = [
                ts.isoformat(),
                f"{price:.2f}",
                f"{price + 0.1:.2f}",
                f"{price - 0.1:.2f}",
                f"{price:.2f}",
                f"{volume:.0f}",
            ]
            writer.writerow(row)
            price += step


class UniverseSelectorTests(unittest.TestCase):
    def test_rank_by_momentum_and_volume(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_series(f"{tmpdir}/ALPHA.csv", 100.0, 1.5, 15000)
            _write_series(f"{tmpdir}/BETA.csv", 200.0, 0.5, 9000)
            _write_series(f"{tmpdir}/GAMMA.csv", 50.0, 1.0, 50)

            source = DataSource(
                path=tmpdir,
                symbols=None,
                warmup_bars=5,
                enforce_trading_hours=False,
            )
            config = UniverseConfig(
                max_symbols=2,
                lookback_bars=15,
                min_avg_volume=1000,
            )

            selector = UniverseSelector(source, DataQualityConfig())
            result = selector.select(config)

            self.assertEqual(result.symbols, ["ALPHA", "BETA"])
            self.assertEqual(len(result.scores), 2)
            self.assertGreater(result.scores["ALPHA"]["score"], result.scores["BETA"]["score"])

    def test_include_symbols_are_respected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_series(f"{tmpdir}/ALPHA.csv", 100.0, 1.5, 15000)
            _write_series(f"{tmpdir}/BETA.csv", 200.0, 0.5, 9000)
            _write_series(f"{tmpdir}/GAMMA.csv", 50.0, 1.0, 50)

            source = DataSource(
                path=tmpdir,
                symbols=None,
                warmup_bars=5,
                enforce_trading_hours=False,
            )
            config = UniverseConfig(
                max_symbols=2,
                lookback_bars=15,
                min_avg_volume=1000,
                include=("GAMMA",),
            )

            selector = UniverseSelector(source, DataQualityConfig())
            result = selector.select(config)

            self.assertIn("GAMMA", result.symbols)
            self.assertIn("ALPHA", result.symbols)
            self.assertEqual(len(result.symbols), 2)


if __name__ == "__main__":
    unittest.main()
