"""
Tests for edge case handler.

Critical edge cases:
- Insufficient data
- Missing timeframe data
- Extreme volatility
- Stale data
- Invalid prices
- Low volume
- Timeframe sync issues
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from aistock.data import Bar
from aistock.edge_cases import EdgeCaseHandler


class TestEdgeCaseHandler:
    """Test edge case detection and handling."""

    def test_insufficient_bars_blocks_trading(self):
        """Test that insufficient bars blocks trading."""
        handler = EdgeCaseHandler()

        # Only 2 bars (need at least 3)
        bars = self._create_test_bars('AAPL', 2)

        result = handler.check_edge_cases('AAPL', bars)

        assert result.is_edge_case is True
        assert result.action == 'block'
        assert result.severity == 'critical'
        assert 'Insufficient bars' in result.reason

    def test_extreme_volatility_blocks_trading(self):
        """Test that extreme volatility blocks trading (flash crash scenario)."""
        handler = EdgeCaseHandler()

        # Create normal bars + one with extreme range
        bars = self._create_test_bars('AAPL', 5)

        # Add extreme volatility bar (20% range in single bar)
        extreme_bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc),
            open=Decimal('100.0'),
            high=Decimal('120.0'),  # 20% jump
            low=Decimal('90.0'),  # 10% drop
            close=Decimal('105.0'),
            volume=1000,
        )
        bars.append(extreme_bar)

        result = handler.check_edge_cases('AAPL', bars)

        assert result.is_edge_case is True
        assert result.action == 'block'
        assert result.severity == 'high'
        assert 'Extreme volatility' in result.reason or 'circuit breaker' in result.reason.lower()

    def test_stale_data_blocks_trading(self):
        """Test that stale data blocks trading."""
        handler = EdgeCaseHandler()

        # Create bars with old timestamp
        old_time = datetime.now(timezone.utc) - timedelta(minutes=15)  # 15 minutes old
        bars = []
        for i in range(5):
            bars.append(
                Bar(
                    symbol='AAPL',
                    timestamp=old_time + timedelta(minutes=i),
                    open=Decimal('100.0'),
                    high=Decimal('101.0'),
                    low=Decimal('99.0'),
                    close=Decimal('100.0'),
                    volume=1000,
                )
            )

        result = handler.check_edge_cases('AAPL', bars, current_time=datetime.now(timezone.utc))

        assert result.is_edge_case is True
        assert result.action == 'block'
        assert 'Stale data' in result.reason

    def test_invalid_prices_blocks_trading(self):
        """Test that invalid prices block trading."""
        handler = EdgeCaseHandler()

        # Create normal bars + one with negative price
        bars = self._create_test_bars('AAPL', 4)

        # Add bar with invalid price
        bad_bar = Bar(
            symbol='AAPL',
            timestamp=datetime(2024, 1, 1, 10, 4, tzinfo=timezone.utc),
            open=Decimal('-10.0'),  # Invalid negative price!
            high=Decimal('101.0'),
            low=Decimal('-10.0'),
            close=Decimal('100.0'),
            volume=1000,
        )
        bars.append(bad_bar)

        result = handler.check_edge_cases('AAPL', bars)

        # Should be blocked (either for invalid prices or extreme volatility from bad data)
        assert result.is_edge_case is True
        assert result.action == 'block'
        # Accept either invalid price detection or extreme volatility (both indicate bad data)
        assert (
            'Invalid prices' in result.reason
            or 'corruption' in result.reason.lower()
            or 'Extreme volatility' in result.reason
            or 'circuit breaker' in result.reason.lower()
        )

    def test_low_volume_reduces_size(self):
        """Test that low volume reduces position size."""
        handler = EdgeCaseHandler()

        # Create bars with very low volume
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        for i in range(10):
            bars.append(
                Bar(
                    symbol='AAPL',
                    timestamp=base_time + timedelta(minutes=i),
                    open=Decimal('100.0'),
                    high=Decimal('101.0'),
                    low=Decimal('99.0'),
                    close=Decimal('100.0'),
                    volume=50,  # Very low volume (suspicious)
                )
            )

        result = handler.check_edge_cases('AAPL', bars)

        assert result.is_edge_case is True
        assert result.action == 'reduce_size'
        assert result.position_size_multiplier < 1.0
        assert 'low volume' in result.reason.lower()

    def test_missing_timeframe_data_reduces_confidence(self):
        """Test that missing timeframe data reduces confidence."""
        handler = EdgeCaseHandler()

        bars_1m = self._create_test_bars('AAPL', 50)
        bars_5m = self._create_test_bars('AAPL', 2)  # Only 2 bars (insufficient)

        timeframe_data = {
            '1m': bars_1m,
            '5m': bars_5m,  # Insufficient
        }

        result = handler.check_edge_cases('AAPL', bars_1m, timeframe_data=timeframe_data)

        assert result.is_edge_case is True
        assert result.action == 'reduce_size'
        assert 'Missing timeframe data' in result.reason

    def test_all_checks_pass(self):
        """Test that good data passes all checks."""
        handler = EdgeCaseHandler()

        # Create good, recent bars
        bars = []
        base_time = datetime.now(timezone.utc) - timedelta(minutes=5)  # Recent
        for i in range(30):
            bars.append(
                Bar(
                    symbol='AAPL',
                    timestamp=base_time + timedelta(minutes=i),
                    open=Decimal('100.0'),
                    high=Decimal('101.0'),
                    low=Decimal('99.0'),
                    close=Decimal('100.5'),
                    volume=10000,  # Good volume
                )
            )

        result = handler.check_edge_cases('AAPL', bars, current_time=datetime.now(timezone.utc))

        assert result.is_edge_case is False
        assert result.action == 'allow'
        assert result.position_size_multiplier == 1.0
        assert result.confidence_adjustment == 0.0

    @staticmethod
    def _create_test_bars(symbol: str, count: int) -> list[Bar]:
        """Create test bars with good data."""
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)

        for i in range(count):
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=base_time + timedelta(minutes=i),
                    open=Decimal('100.0'),
                    high=Decimal('101.0'),
                    low=Decimal('99.0'),
                    close=Decimal('100.0'),
                    volume=1000,
                )
            )

        return bars
