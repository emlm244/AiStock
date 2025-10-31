import sys
import threading
import time
import types
import unittest
from decimal import Decimal
from importlib import import_module
from pathlib import Path

if 'aistock' not in sys.modules:
    pkg = types.ModuleType('aistock')
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / 'aistock')]
    sys.modules['aistock'] = pkg

portfolio_module = import_module('aistock.portfolio')
Portfolio = portfolio_module.Portfolio
Position = portfolio_module.Position


class PortfolioThreadSafetyTests(unittest.TestCase):
    """Basic thread safety tests for portfolio snapshot methods."""

    def test_snapshot_positions_returns_independent_copy(self):
        """Verify snapshot is independent copy."""
        portfolio = Portfolio(cash=Decimal('100000'))
        portfolio.update_position('AAPL', Decimal('10'), Decimal('150'))

        snapshot = portfolio.snapshot_positions()
        self.assertIn('AAPL', snapshot)

        snapshot['AAPL'].quantity = Decimal('0')
        self.assertEqual(portfolio.get_position('AAPL'), Decimal('10'))

    def test_replace_positions_copies_input(self):
        """Verify replace_positions copies input."""
        portfolio = Portfolio()
        external_position = Position(symbol='MSFT', quantity=Decimal('5'), average_price=Decimal('200'))

        portfolio.replace_positions({'MSFT': external_position})
        external_position.quantity = Decimal('20')

        self.assertEqual(portfolio.get_position('MSFT'), Decimal('5'))

    def test_trade_log_snapshot_returns_copy(self):
        """Verify trade log snapshot is copy."""
        portfolio = Portfolio()
        portfolio.trade_log.append({'symbol': 'AAPL', 'realised_pnl': 10.0})

        snapshot = portfolio.get_trade_log_snapshot()
        snapshot.append({'symbol': 'TSLA', 'realised_pnl': 5.0})

        self.assertEqual(len(portfolio.trade_log), 1)


class PortfolioConcurrencyStressTests(unittest.TestCase):
    """Stress tests for concurrent portfolio operations."""

    def test_concurrent_position_updates(self):
        """Test 100 concurrent position updates don't cause corruption."""
        portfolio = Portfolio(cash=Decimal('1000000'))
        errors = []

        def update_worker(symbol: str, iterations: int):
            try:
                for i in range(iterations):
                    qty = Decimal(str(i % 10 + 1))
                    price = Decimal('100.00')
                    portfolio.update_position(symbol, qty, price)
                    # Verify we can read back
                    portfolio.get_position(symbol)
            except Exception as e:
                errors.append(str(e))

        # Spawn 10 threads, each doing 10 updates
        threads = []
        for i in range(10):
            symbol = f'SYM{i}'
            t = threading.Thread(target=update_worker, args=(symbol, 10))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5)

        # No errors should have occurred
        self.assertEqual(len(errors), 0, f"Concurrent updates had errors: {errors}")

        # Should have 10 positions
        self.assertEqual(portfolio.position_count(), 10)

    def test_concurrent_snapshot_and_updates(self):
        """Test snapshots while positions are being updated."""
        portfolio = Portfolio(cash=Decimal('500000'))
        portfolio.update_position('AAPL', Decimal('100'), Decimal('150'))

        snapshots = []
        errors = []

        def snapshot_worker():
            try:
                for _ in range(50):
                    snapshot = portfolio.snapshot_positions()
                    snapshots.append(snapshot)
                    time.sleep(0.001)  # Small delay
            except Exception as e:
                errors.append(f"Snapshot error: {e}")

        def update_worker():
            try:
                for i in range(50):
                    qty = Decimal(str(100 + i))
                    portfolio.update_position('AAPL', qty, Decimal('150'))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Update error: {e}")

        # Run snapshot and update threads concurrently
        t1 = threading.Thread(target=snapshot_worker)
        t2 = threading.Thread(target=update_worker)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        # No errors should have occurred
        self.assertEqual(len(errors), 0, f"Concurrent operations had errors: {errors}")

        # All snapshots should be valid
        self.assertGreater(len(snapshots), 0)
        for snapshot in snapshots:
            self.assertIsInstance(snapshot, dict)
            if 'AAPL' in snapshot:
                self.assertIsInstance(snapshot['AAPL'], Position)

    def test_concurrent_trade_log_access(self):
        """Test concurrent trade log reads and writes."""
        portfolio = Portfolio()
        errors = []

        def writer():
            try:
                for i in range(50):
                    portfolio.trade_log.append({
                        'symbol': f'SYM{i}',
                        'realised_pnl': float(i),
                        'timestamp': time.time()
                    })
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Writer error: {e}")

        def reader():
            try:
                for _ in range(50):
                    snapshot = portfolio.get_trade_log_snapshot(limit=10)
                    self.assertIsInstance(snapshot, list)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Reader error: {e}")

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Trade log operations had errors: {errors}")
        self.assertEqual(len(portfolio.trade_log), 50)

    def test_no_deadlocks_under_load(self):
        """Test that heavy concurrent operations don't deadlock."""
        portfolio = Portfolio(cash=Decimal('2000000'))
        completed = {'count': 0}
        errors = []

        def mixed_operations_worker(worker_id: int):
            try:
                for i in range(20):
                    # Mix of different operations
                    if i % 3 == 0:
                        portfolio.update_position(f'SYM{worker_id}', Decimal(str(i)), Decimal('100'))
                    elif i % 3 == 1:
                        portfolio.snapshot_positions()
                    else:
                        portfolio.get_cash()
                    time.sleep(0.0001)
                completed['count'] += 1
            except Exception as e:
                errors.append(f"Worker {worker_id} error: {e}")

        # Spawn 20 workers doing mixed operations
        threads = []
        for i in range(20):
            t = threading.Thread(target=mixed_operations_worker, args=(i,))
            threads.append(t)
            t.start()

        # Wait with timeout - if deadlock occurs, this will timeout
        for t in threads:
            t.join(timeout=15)

        # All workers should have completed
        self.assertEqual(completed['count'], 20, "Some workers didn't complete (possible deadlock)")
        self.assertEqual(len(errors), 0, f"Workers had errors: {errors}")


if __name__ == '__main__':
    unittest.main()
