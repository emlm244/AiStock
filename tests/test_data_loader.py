import pathlib
import tempfile
import unittest
from datetime import timezone

from aistock.config import DataSource
from aistock.data import load_csv_directory


class DataLoaderTests(unittest.TestCase):
    def test_load_csv_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir)
            sample = path / "AAPL.csv"
            sample.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T09:30:00,100,101,99,100,1000\n"
                "2024-01-01T09:31:00,101,102,100,101,1100\n",
                encoding="utf-8",
            )

            bars = load_csv_directory(
                DataSource(path=str(path), timezone=timezone.utc, symbols=["AAPL"], warmup_bars=1)
            )
            self.assertEqual(set(bars), {"AAPL"})
            self.assertEqual(len(bars["AAPL"]), 2)
            first_bar = bars["AAPL"][0]
            self.assertEqual(first_bar.symbol, "AAPL")
            self.assertIs(first_bar.timestamp.tzinfo, timezone.utc)
            self.assertEqual(float(first_bar.open), 100.0)

if __name__ == "__main__":
    unittest.main()
