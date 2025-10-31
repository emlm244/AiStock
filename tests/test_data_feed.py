import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aistock.data import Bar, DataFeed


class DataFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t0 = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(minutes=1)
        self.t2 = self.t0 + timedelta(minutes=2)

    def _bar(self, symbol: str, timestamp: datetime, price: str) -> Bar:
        value = Decimal(price)
        return Bar(
            symbol=symbol,
            timestamp=timestamp,
            open=value,
            high=value,
            low=value,
            close=value,
            volume=1000,  # int, not float
        )

    def test_forward_fill_emits_virtual_bar(self):
        bars = {
            'AAPL': [
                self._bar('AAPL', self.t0, '100'),
                self._bar('AAPL', self.t1, '101'),
                self._bar('AAPL', self.t2, '102'),
            ],
            'MSFT': [
                self._bar('MSFT', self.t0, '200'),
                self._bar('MSFT', self.t2, '202'),
            ],
        }
        feed = DataFeed(bars, timedelta(minutes=1), warmup_bars=0, fill_missing=True)
        events = list(feed.iter_stream())
        fill_events = [evt for evt in events if evt[0] == self.t1 and evt[1] == 'MSFT']
        self.assertEqual(len(fill_events), 1)
        _, _, fill_bar = fill_events[0]
        self.assertEqual(fill_bar.close, Decimal('200'))
        self.assertEqual(fill_bar.volume, 0)  # int, not float
        self.assertEqual(fill_bar.timestamp, self.t1)

    def test_no_fill_when_disabled(self):
        bars = {
            'AAPL': [
                self._bar('AAPL', self.t0, '100'),
                self._bar('AAPL', self.t1, '101'),
            ],
            'MSFT': [
                self._bar('MSFT', self.t0, '200'),
                self._bar('MSFT', self.t2, '202'),
            ],
        }
        feed = DataFeed(bars, timedelta(minutes=1), warmup_bars=0, fill_missing=False)
        events = [evt for evt in feed.iter_stream() if evt[1] == 'MSFT' and evt[0] == self.t1]
        self.assertFalse(events)


if __name__ == '__main__':
    unittest.main()
