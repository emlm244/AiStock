import unittest
from datetime import datetime, timezone
from decimal import Decimal

from aistock.brokers.paper import PaperBroker
from aistock.config import ExecutionConfig
from aistock.data import Bar
from aistock.execution import ExecutionReport, Order, OrderSide, OrderType


class BrokerTests(unittest.TestCase):
    def test_market_order_fills(self):
        reports = []

        def on_fill(report: ExecutionReport) -> None:
            reports.append(report)

        broker = PaperBroker(ExecutionConfig(slip_bps_limit=0.0))
        broker.set_fill_handler(on_fill)
        broker.start()
        order = Order(symbol='AAPL', quantity=Decimal('10'), side=OrderSide.BUY, order_type=OrderType.MARKET)
        broker.submit(order)
        bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 1, 9, 31, tzinfo=timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100'),
            volume=1000,
        )
        broker.process_bar(bar, bar.timestamp)
        self.assertEqual(len(reports), 1)
        fill = reports[0]
        self.assertEqual(fill.symbol, 'AAPL')
        self.assertEqual(fill.quantity, Decimal('10'))

    def test_get_positions_tracks_executions(self):
        broker = PaperBroker(ExecutionConfig(slip_bps_limit=0.0))
        broker.start()
        order = Order(symbol='AAPL', quantity=Decimal('5'), side=OrderSide.BUY, order_type=OrderType.MARKET)
        broker.submit(order)
        bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 1, 9, 31, tzinfo=timezone.utc),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100'),
            volume=1000,
        )
        broker.process_bar(bar, bar.timestamp)
        positions = broker.get_positions()
        self.assertIn('AAPL', positions)
        qty, avg_price = positions['AAPL']
        self.assertAlmostEqual(qty, 5.0)
        self.assertAlmostEqual(avg_price, 100.0)

        # Flatten the position and ensure it disappears from the snapshot.
        sell_order = Order(symbol='AAPL', quantity=Decimal('5'), side=OrderSide.SELL, order_type=OrderType.MARKET)
        broker.submit(sell_order)
        broker.process_bar(bar, bar.timestamp)
        self.assertEqual(broker.get_positions(), {})


if __name__ == '__main__':
    unittest.main()
