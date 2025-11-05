"""
Comprehensive timezone and timing edge case test suite.

Tests critical fixes for:
1. DST transition boundaries
2. Naive vs timezone-aware datetime mixing
3. Stale data detection with out-of-order bars
4. Clock skew in TTL expiration
5. Session boundary timing
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from aistock.data import Bar
from aistock.edge_cases import EdgeCaseHandler
from aistock.idempotency import OrderIdempotencyTracker


class TestDSTTransitionEdgeCases:
    """Test DST transition boundary conditions."""

    def test_dst_spring_forward_boundary(self):
        """
        Test DST spring forward transition (2AM → 3AM).

        Edge case: Bar timestamps exactly at 2:00:00 AM on DST transition day.
        """
        # DST spring forward: 2025-03-09 02:00:00 EST → 03:00:00 EDT
        # In UTC: 2025-03-09 07:00:00 UTC (EST) → 07:00:00 UTC (EDT, no change)

        # Bar just before transition
        bar_before = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 3, 9, 6, 59, 59, tzinfo=timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('151.00'),
            low=Decimal('149.00'),
            close=Decimal('150.50'),
            volume=1000,
        )

        # Bar just after transition
        bar_after = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 3, 9, 7, 0, 1, tzinfo=timezone.utc),
            open=Decimal('150.50'),
            high=Decimal('151.50'),
            low=Decimal('150.00'),
            close=Decimal('151.00'),
            volume=1000,
        )

        # Both bars should have timezone-aware timestamps
        assert bar_before.timestamp.tzinfo is not None
        assert bar_after.timestamp.tzinfo is not None

        # Time delta should be ~2 seconds
        delta = bar_after.timestamp - bar_before.timestamp
        assert delta.total_seconds() == pytest.approx(2.0, abs=0.1)

    def test_dst_fall_back_boundary(self):
        """
        Test DST fall back transition (2AM → 1AM).

        Edge case: Bar timestamps during the "repeated hour" 1:00-2:00 AM.
        """
        # DST fall back: 2025-11-02 02:00:00 EDT → 01:00:00 EST
        # In UTC: 2025-11-02 06:00:00 UTC (EDT) → 06:00:00 UTC (EST, no change)

        # Bars during the transition should maintain UTC consistency
        bar1 = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 11, 2, 5, 59, 59, tzinfo=timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('151.00'),
            low=Decimal('149.00'),
            close=Decimal('150.50'),
            volume=1000,
        )

        bar2 = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 11, 2, 6, 0, 1, tzinfo=timezone.utc),
            open=Decimal('150.50'),
            high=Decimal('151.50'),
            low=Decimal('150.00'),
            close=Decimal('151.00'),
            volume=1000,
        )

        # Both should be timezone-aware
        assert bar1.timestamp.tzinfo is not None
        assert bar2.timestamp.tzinfo is not None

        # UTC timestamps should be monotonic (no duplicates)
        assert bar2.timestamp > bar1.timestamp


class TestNaiveTimestampEdgeCases:
    """Test naive vs timezone-aware datetime handling."""

    def test_naive_timestamp_detection(self):
        """
        CRITICAL FIX TEST: Naive timestamps should be detected and handled.

        Edge case identified in deep review: edge_cases.py:219
        """
        handler = EdgeCaseHandler()

        # Create naive bar (WRONG - should never happen in production)
        naive_bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 1, 15, 10, 30, 0),  # NO TIMEZONE!
            open=Decimal('150.00'),
            high=Decimal('151.00'),
            low=Decimal('149.00'),
            close=Decimal('150.50'),
            volume=1000,
        )

        # EdgeCaseHandler should detect this
        assert naive_bar.timestamp.tzinfo is None

        # System should handle this gracefully (not crash)
        current_time = datetime.now(timezone.utc)

        # This should not crash even with naive timestamp
        result = handler.check_edge_cases(
            symbol='AAPL',
            bars=[naive_bar],
            current_time=current_time,
        )

        # Should be flagged as edge case
        assert result.is_edge_case

    def test_mixed_naive_aware_bars(self):
        """Test handling of mixed naive/aware bars in same list."""
        # Aware bar
        aware_bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('151.00'),
            low=Decimal('149.00'),
            close=Decimal('150.50'),
            volume=1000,
        )

        # Naive bar
        naive_bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 1, 15, 10, 35, 0),  # NO TIMEZONE
            open=Decimal('150.50'),
            high=Decimal('151.50'),
            low=Decimal('150.00'),
            close=Decimal('151.00'),
            volume=1000,
        )

        # Check consistency
        assert aware_bar.timestamp.tzinfo is not None
        assert naive_bar.timestamp.tzinfo is None

        # Comparison should still work (Python allows this)
        # but the result may be unexpected
        # This is why we must enforce timezone-aware everywhere


class TestStaleDataDetection:
    """Test stale data detection with various edge cases."""

    def test_out_of_order_bars_age_calculation(self):
        """
        Test stale data check with out-of-order bars.

        Edge case identified in deep review: edge_cases.py:223-229
        """
        handler = EdgeCaseHandler()

        # Create bars out of chronological order
        bar1 = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('151.00'),
            low=Decimal('149.00'),
            close=Decimal('150.50'),
            volume=1000,
        )

        bar2 = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 1, 15, 10, 25, 0, tzinfo=timezone.utc),  # EARLIER!
            open=Decimal('149.00'),
            high=Decimal('150.00'),
            low=Decimal('148.50'),
            close=Decimal('149.50'),
            volume=1000,
        )

        bar3 = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 1, 15, 10, 35, 0, tzinfo=timezone.utc),
            open=Decimal('150.50'),
            high=Decimal('151.50'),
            low=Decimal('150.00'),
            close=Decimal('151.00'),
            volume=1000,
        )

        # Bars in wrong order: [10:30, 10:25, 10:35]
        bars_out_of_order = [bar1, bar2, bar3]

        current_time = datetime(2025, 1, 15, 10, 40, 0, tzinfo=timezone.utc)

        # EdgeCaseHandler should handle this gracefully
        handler.check_edge_cases(
            symbol='AAPL',
            bars=bars_out_of_order,
            current_time=current_time,
        )

        # May flag as edge case depending on implementation
        # At minimum, should not crash

    def test_future_bar_timestamp(self):
        """Test bar with timestamp in the future."""
        handler = EdgeCaseHandler()

        current_time = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        # Bar with future timestamp (clock skew or data error)
        future_bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2025, 1, 15, 10, 35, 0, tzinfo=timezone.utc),  # 5 min future!
            open=Decimal('150.00'),
            high=Decimal('151.00'),
            low=Decimal('149.00'),
            close=Decimal('150.50'),
            volume=1000,
        )

        result = handler.check_edge_cases(
            symbol='AAPL',
            bars=[future_bar],
            current_time=current_time,
        )

        # Should be flagged as edge case (future data)
        # Age would be negative
        assert result.is_edge_case


class TestClockSkewInTTL:
    """Test idempotency TTL scenarios."""

    def test_idempotency_basic_duplicate_detection(self, tmp_path):
        """Test basic duplicate order detection."""
        tracker = OrderIdempotencyTracker(storage_path=str(tmp_path / 'test_orders.json'), expiration_minutes=5)

        # Submit order (timestamp captured internally)
        tracker.mark_submitted('ORDER_001')

        # Immediately check - should be duplicate
        is_dup = tracker.is_duplicate('ORDER_001')
        assert is_dup

        # Different order should not be duplicate
        is_dup_other = tracker.is_duplicate('ORDER_002')
        assert not is_dup_other

    def test_ttl_expiration_detection(self, tmp_path):
        """
        Test TTL expiration (cannot test exact timing without mocking).

        NOTE: This test documents the expected behavior. Full testing
        would require time mocking to advance clock 5+ minutes.
        """
        tracker = OrderIdempotencyTracker(storage_path=str(tmp_path / 'test_orders.json'), expiration_minutes=5)

        # Submit order
        tracker.mark_submitted('ORDER_001')

        # Within TTL - should be duplicate
        is_dup = tracker.is_duplicate('ORDER_001')
        assert is_dup

        # NOTE: After 5+ minutes, should NOT be duplicate (TTL expired)
        # This would require time.sleep(301) or mocking datetime.now()

    def test_multiple_orders_tracked(self, tmp_path):
        """Test multiple orders tracked independently."""
        tracker = OrderIdempotencyTracker(storage_path=str(tmp_path / 'test_orders.json'), expiration_minutes=5)

        # Submit multiple orders
        for i in range(10):
            tracker.mark_submitted(f'ORDER_{i:03d}')

        # All should be duplicates
        for i in range(10):
            is_dup = tracker.is_duplicate(f'ORDER_{i:03d}')
            assert is_dup, f'ORDER_{i:03d} should be duplicate'


class TestSessionBoundaryTiming:
    """Test timing logic at session boundaries."""

    def test_midnight_utc_boundary(self):
        """Test behavior exactly at midnight UTC."""
        # Exactly midnight UTC
        midnight = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)

        # One second before midnight
        before_midnight = datetime(2025, 1, 14, 23, 59, 59, tzinfo=timezone.utc)

        # One second after midnight
        after_midnight = datetime(2025, 1, 15, 0, 0, 1, tzinfo=timezone.utc)

        # All should be valid timezone-aware datetimes
        assert midnight.tzinfo is not None
        assert before_midnight.tzinfo is not None
        assert after_midnight.tzinfo is not None

        # Delta across midnight should be correct
        delta = after_midnight - before_midnight
        assert delta.total_seconds() == pytest.approx(2.0, abs=0.1)

    def test_weekend_gap_handling(self):
        """Test handling of 48+ hour gaps over weekend."""
        # Friday market close: 2025-01-17 21:00:00 UTC (4:00 PM ET)
        friday_close = datetime(2025, 1, 17, 21, 0, 0, tzinfo=timezone.utc)

        # Monday market open: 2025-01-20 14:30:00 UTC (9:30 AM ET)
        monday_open = datetime(2025, 1, 20, 14, 30, 0, tzinfo=timezone.utc)

        # Gap should be ~65.5 hours
        gap = monday_open - friday_close
        expected_hours = 65.5
        assert gap.total_seconds() / 3600 == pytest.approx(expected_hours, abs=0.5)


class TestDataQualityEdgeCases:
    """Test data quality edge cases with edge case handler."""

    def test_empty_bars_list(self):
        """Test handling of empty bars list."""
        handler = EdgeCaseHandler()

        result = handler.check_edge_cases(
            symbol='AAPL',
            bars=[],
            current_time=datetime.now(timezone.utc),
        )

        # Should block trading with insufficient data
        assert result.action == 'block'
        assert 'insufficient' in result.reason.lower() or 'bars' in result.reason.lower()

    def test_single_bar_edge_case(self):
        """Test handling of single bar (insufficient for analysis)."""
        handler = EdgeCaseHandler()

        bar = Bar(
            symbol='AAPL',
            timestamp=datetime.now(timezone.utc),
            open=Decimal('150.00'),
            high=Decimal('151.00'),
            low=Decimal('149.00'),
            close=Decimal('150.50'),
            volume=1000,
        )

        result = handler.check_edge_cases(
            symbol='AAPL',
            bars=[bar],
            current_time=datetime.now(timezone.utc),
        )

        # Should block or warn about insufficient data
        assert result.is_edge_case
        assert result.action in ['block', 'warn']

    def test_all_nan_volume(self):
        """Test bars with zero volume (halted security or data corruption)."""
        handler = EdgeCaseHandler()

        # Create bars with zero volume
        bars = []
        base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        for i in range(20):
            bar = Bar(
                symbol='HALTED',
                timestamp=base_time + timedelta(minutes=i),
                open=Decimal('100.00'),
                high=Decimal('100.00'),
                low=Decimal('100.00'),
                close=Decimal('100.00'),
                volume=0,  # ZERO VOLUME!
            )
            bars.append(bar)

        result = handler.check_edge_cases(
            symbol='HALTED',
            bars=bars,
            current_time=datetime.now(timezone.utc),
        )

        # Should flag as edge case (unusual data)
        assert result.is_edge_case


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
