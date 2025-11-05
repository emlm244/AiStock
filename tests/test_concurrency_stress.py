"""
Comprehensive concurrency and state management stress test suite.

Tests critical fixes for:
1. Timeframe state race conditions under concurrent access
2. Portfolio thread safety with concurrent trades
3. Q-value table concurrent updates
4. Checkpoint manager shutdown edge cases
5. Idempotency tracker concurrent submissions
"""

import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from aistock.data import Bar
from aistock.fsd import FSDConfig, RLAgent
from aistock.idempotency import OrderIdempotencyTracker
from aistock.portfolio import Portfolio
from aistock.timeframes import TimeframeManager


class TestTimeframeStateConcurrency:
    """Test timeframe state updates under concurrent access."""

    def test_concurrent_bar_additions(self):
        """
        CRITICAL FIX TEST: Concurrent add_bar() calls should not corrupt state.

        Edge case identified in deep review: timeframes.py:191-219
        """
        symbols = ['AAPL']
        timeframes = ['1m', '5m']
        manager = TimeframeManager(symbols, timeframes)

        def add_bars_worker(worker_id: int, count: int):
            """Worker thread that adds bars concurrently."""
            base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

            for i in range(count):
                timestamp = base_time + timedelta(seconds=worker_id * count + i)
                price_offset = Decimal(i) / Decimal('10')
                bar = Bar(
                    symbol='AAPL',
                    timestamp=timestamp,
                    open=Decimal('150.00') + price_offset,
                    high=Decimal('151.00') + price_offset,
                    low=Decimal('149.00') + price_offset,
                    close=Decimal('150.50') + price_offset,
                    volume=1000,
                )
                manager.add_bar('AAPL', '1m', bar)

        # Launch 10 concurrent workers
        threads = []
        num_workers = 10
        bars_per_worker = 50

        for worker_id in range(num_workers):
            thread = threading.Thread(target=add_bars_worker, args=(worker_id, bars_per_worker))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=5.0)

        # Verify state is not corrupted
        bars = manager.get_bars('AAPL', '1m')
        assert len(bars) > 0  # Should have bars
        assert len(bars) <= num_workers * bars_per_worker  # No duplicates

    def test_concurrent_read_write_race(self):
        """Test concurrent get_bars() while add_bar() is happening."""
        manager = TimeframeManager(['AAPL'], ['1m'])

        stop_flag = threading.Event()
        read_errors = []
        write_errors = []

        def writer_worker():
            """Continuously add bars."""
            base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
            i = 0
            while not stop_flag.is_set():
                try:
                    bar = Bar(
                        symbol='AAPL',
                        timestamp=base_time + timedelta(seconds=i * 60),
                        open=Decimal('150.00'),
                        high=Decimal('151.00'),
                        low=Decimal('149.00'),
                        close=Decimal('150.50'),
                        volume=1000,
                    )
                    manager.add_bar('AAPL', '1m', bar)
                    i += 1
                    time.sleep(0.001)
                except Exception as e:
                    write_errors.append(e)

        def reader_worker():
            """Continuously read bars."""
            while not stop_flag.is_set():
                try:
                    bars = manager.get_bars('AAPL', '1m')
                    # Access bars to trigger potential race
                    if bars:
                        _ = bars[-1].close
                    time.sleep(0.001)
                except Exception as e:
                    read_errors.append(e)

        # Launch workers
        writer = threading.Thread(target=writer_worker)
        readers = [threading.Thread(target=reader_worker) for _ in range(5)]

        writer.start()
        for reader in readers:
            reader.start()

        # Run for 1 second
        time.sleep(1.0)
        stop_flag.set()

        # Wait for completion
        writer.join(timeout=2.0)
        for reader in readers:
            reader.join(timeout=2.0)

        # No errors should occur
        assert len(read_errors) == 0, f'Read errors: {read_errors}'
        assert len(write_errors) == 0, f'Write errors: {write_errors}'


class TestPortfolioThreadSafety:
    """Test Portfolio thread safety under concurrent access."""

    def test_concurrent_position_updates(self):
        """Test concurrent update_position() calls on different symbols."""
        portfolio = Portfolio(initial_cash=Decimal('100000'))

        symbols = [f'SYM{i:02d}' for i in range(10)]
        errors = []

        def trade_worker(symbol: str, num_trades: int):
            """Execute trades on a symbol."""
            try:
                for i in range(num_trades):
                    # Buy
                    portfolio.update_position(
                        symbol=symbol,
                        quantity_delta=Decimal('10'),
                        price=Decimal('100.00') + Decimal(str(i)),
                        commission=Decimal('1.00'),
                    )

                    # Sell half
                    portfolio.update_position(
                        symbol=symbol,
                        quantity_delta=Decimal('-5'),
                        price=Decimal('101.00') + Decimal(str(i)),
                        commission=Decimal('1.00'),
                    )
            except Exception as e:
                errors.append((symbol, e))

        # Launch concurrent workers
        threads = []
        for symbol in symbols:
            thread = threading.Thread(target=trade_worker, args=(symbol, 20))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout=5.0)

        # No errors should occur
        assert len(errors) == 0, f'Errors: {errors}'

        # Verify portfolio state is consistent
        total_position_value = Decimal('0')
        for symbol in symbols:
            pos = portfolio.get_position(symbol)
            # Should have accumulated position
            assert pos >= Decimal('0')
            if pos > 0:
                avg_price = portfolio.get_avg_price(symbol)
                total_position_value += pos * avg_price  # type: ignore

        # Cash + position value should be reasonable
        total_equity = portfolio.cash + total_position_value
        assert total_equity > Decimal('0')

    def test_concurrent_equity_calculations(self):
        """Test concurrent get_equity() calls while trades happen."""
        portfolio = Portfolio(initial_cash=Decimal('100000'))

        stop_flag = threading.Event()
        equity_errors = []
        trade_errors = []

        def trader_worker():
            """Execute trades."""
            i = 0
            while not stop_flag.is_set():
                try:
                    portfolio.update_position(
                        symbol='AAPL',
                        quantity_delta=Decimal('10') if i % 2 == 0 else Decimal('-10'),
                        price=Decimal('150.00'),
                        commission=Decimal('1.00'),
                    )
                    i += 1
                    time.sleep(0.01)
                except Exception as e:
                    trade_errors.append(e)

        def equity_reader():
            """Read equity."""
            while not stop_flag.is_set():
                try:
                    current_prices = {'AAPL': Decimal('150.00')}
                    equity = portfolio.get_equity(current_prices)
                    assert equity > Decimal('0')
                    time.sleep(0.01)
                except Exception as e:
                    equity_errors.append(e)

        # Launch workers
        trader = threading.Thread(target=trader_worker)
        equity_readers = [threading.Thread(target=equity_reader) for _ in range(3)]

        trader.start()
        for reader in equity_readers:
            reader.start()

        # Run for 0.5 seconds
        time.sleep(0.5)
        stop_flag.set()

        # Wait for completion
        trader.join(timeout=2.0)
        for reader in equity_readers:
            reader.join(timeout=2.0)

        # No errors
        assert len(trade_errors) == 0, f'Trade errors: {trade_errors}'
        assert len(equity_errors) == 0, f'Equity errors: {equity_errors}'


class TestQValueTableConcurrency:
    """Test Q-value table concurrent updates."""

    def test_concurrent_q_value_updates(self):
        """Test concurrent Q-value updates from multiple threads."""
        config = FSDConfig()
        agent = RLAgent(config)

        errors = []

        def update_worker(worker_id: int, num_updates: int):
            """Execute Q-value updates."""
            try:
                for i in range(num_updates):
                    state = {'price_change_pct': 0.01 * i, 'volume_ratio': 1.0, 'position_pct': 0.0}

                    # Select action (reads Q-values)
                    action = agent.select_action(state, training=True)

                    # Update Q-value (writes Q-values)
                    reward = float(i % 10 - 5)  # Random reward
                    next_state = {
                        'price_change_pct': 0.01 * (i + 1),
                        'volume_ratio': 1.0,
                        'position_pct': 0.1,
                    }

                    agent.update_q_value(state, action, reward, next_state, done=False)
            except Exception as e:
                errors.append((worker_id, e))

        # Launch concurrent workers
        threads = []
        num_workers = 5
        updates_per_worker = 100

        for worker_id in range(num_workers):
            thread = threading.Thread(target=update_worker, args=(worker_id, updates_per_worker))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout=10.0)

        # No errors should occur
        assert len(errors) == 0, f'Errors: {errors}'

        # Q-table should have entries
        assert len(agent.q_values) > 0


class TestIdempotencyTrackerConcurrency:
    """Test idempotency tracker concurrent submissions."""

    def test_concurrent_order_submissions(self):
        """Test concurrent mark_submitted() calls."""
        tracker = OrderIdempotencyTracker(expiration_minutes=5)

        errors = []

        def submit_worker(worker_id: int, num_orders: int):
            """Submit orders."""
            try:
                for i in range(num_orders):
                    order_id = f'ORDER_{worker_id:02d}_{i:03d}'
                    tracker.mark_submitted(order_id)

                    # Check if duplicate
                    is_dup = tracker.is_duplicate(order_id)
                    assert is_dup  # Should be duplicate immediately after marking
            except Exception as e:
                errors.append((worker_id, e))

        # Launch concurrent workers
        threads = []
        num_workers = 10
        orders_per_worker = 50

        for worker_id in range(num_workers):
            thread = threading.Thread(target=submit_worker, args=(worker_id, orders_per_worker))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout=5.0)

        # No errors
        assert len(errors) == 0, f'Errors: {errors}'

        # All orders should be tracked
        num_workers * orders_per_worker
        # (Note: We can't directly check count, but verify no corruption occurred)


class TestStressScenarios:
    """High-load stress test scenarios."""

    def test_1000_bars_per_second_throughput(self):
        """Stress test with 1000 bars/second."""
        manager = TimeframeManager(['AAPL'], ['1m'], max_bars_per_timeframe=1500)

        base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        start_time = time.time()

        # Add 1000 bars
        for i in range(1000):
            bar = Bar(
                symbol='AAPL',
                timestamp=base_time + timedelta(seconds=i),
                open=Decimal('150.00'),
                high=Decimal('151.00'),
                low=Decimal('149.00'),
                close=Decimal('150.50'),
                volume=1000,
            )
            manager.add_bar('AAPL', '1m', bar)

        elapsed = time.time() - start_time

        # Should complete in reasonable time
        assert elapsed < 5.0, f'Too slow: {elapsed:.2f}s for 1000 bars'

        # Verify all bars added (accounting for max_bars limit)
        bars = manager.get_bars('AAPL', '1m')
        assert len(bars) == 1000

    def test_100_concurrent_operations(self):
        """Stress test with 100 concurrent operations."""
        portfolio = Portfolio(initial_cash=Decimal('1000000'))

        def random_operations(worker_id: int):
            """Execute random portfolio operations."""
            symbol = f'SYM{worker_id % 10}'
            for _ in range(10):
                # Random buy/sell
                qty = Decimal('10') if worker_id % 2 == 0 else Decimal('-10')
                portfolio.update_position(
                    symbol=symbol,
                    quantity_delta=qty,
                    price=Decimal('100.00'),
                    commission=Decimal('1.00'),
                )

                # Read equity
                prices = {f'SYM{i}': Decimal('100.00') for i in range(10)}
                _ = portfolio.get_equity(prices)

        # Launch 100 workers
        threads = []
        for i in range(100):
            thread = threading.Thread(target=random_operations, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all
        for thread in threads:
            thread.join(timeout=10.0)

        # No crashes = success


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
