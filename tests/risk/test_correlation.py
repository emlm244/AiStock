"""Tests for correlation monitoring."""

import threading
from decimal import Decimal

import pytest

from aistock.risk.advanced_config import CorrelationLimitsConfig
from aistock.risk.correlation import CorrelationCheckResult, CorrelationMonitor


class TestCorrelationLimitsConfig:
    """Tests for CorrelationLimitsConfig validation."""

    def test_default_config_is_valid(self):
        """Default configuration should be valid."""
        config = CorrelationLimitsConfig()
        config.validate()

    def test_invalid_max_correlation_raises(self):
        """max_correlation outside [0, 1] should raise."""
        config = CorrelationLimitsConfig(max_correlation=-0.1)
        with pytest.raises(ValueError, match='max_correlation must be in'):
            config.validate()

        config = CorrelationLimitsConfig(max_correlation=1.5)
        with pytest.raises(ValueError, match='max_correlation must be in'):
            config.validate()

    def test_invalid_lookback_raises(self):
        """lookback_bars < 10 should raise."""
        config = CorrelationLimitsConfig(lookback_bars=5)
        with pytest.raises(ValueError, match='lookback_bars must be >= 10'):
            config.validate()

    def test_min_data_points_exceeds_lookback_raises(self):
        """min_data_points > lookback_bars should raise."""
        config = CorrelationLimitsConfig(lookback_bars=20, min_data_points=30)
        with pytest.raises(ValueError, match='min_data_points'):
            config.validate()


class TestCorrelationMonitor:
    """Tests for CorrelationMonitor."""

    def test_no_positions_allows_trade(self):
        """Empty portfolio should allow any trade."""
        config = CorrelationLimitsConfig(enable=True, max_correlation=0.7)
        monitor = CorrelationMonitor(config)

        result = monitor.check_correlation('AAPL', {}, {})

        assert result.allowed
        assert result.max_correlation == 0.0
        assert len(result.correlated_symbols) == 0

    def test_insufficient_data_allows_trade(self):
        """Insufficient price history should allow trade."""
        config = CorrelationLimitsConfig(enable=True, min_data_points=20)
        monitor = CorrelationMonitor(config)

        # Only 10 bars for AAPL
        result = monitor.check_correlation(
            'AAPL',
            {'MSFT': Decimal('100')},
            {'AAPL': [100.0 + i for i in range(10)], 'MSFT': [100.0 + i for i in range(30)]},
        )

        assert result.allowed
        assert 'Insufficient data' in result.reason

    def test_uncorrelated_positions_allows_trade(self):
        """Uncorrelated positions should allow trade."""
        config = CorrelationLimitsConfig(enable=True, max_correlation=0.7, min_data_points=5)
        monitor = CorrelationMonitor(config)

        # Create uncorrelated price series (one goes up, one goes down)
        aapl = [100 + i for i in range(30)]
        msft = [100 - i * 0.5 + (i % 3) for i in range(30)]  # Mostly uncorrelated

        result = monitor.check_correlation(
            'AAPL',
            {'MSFT': Decimal('100')},
            {'AAPL': aapl, 'MSFT': msft},
        )

        # Should be allowed (low correlation)
        assert result.allowed is True
        assert result.max_correlation <= 0.7

    def test_highly_correlated_positions_blocks_trade(self):
        """Highly correlated positions should block trade."""
        config = CorrelationLimitsConfig(
            enable=True,
            max_correlation=0.7,
            min_data_points=5,
            block_on_high_correlation=True,
        )
        monitor = CorrelationMonitor(config)

        # Create highly correlated price series (nearly identical)
        base = [100 + i * 0.5 for i in range(30)]
        correlated = [100 + i * 0.51 for i in range(30)]  # Very similar pattern

        result = monitor.check_correlation(
            'AAPL',
            {'MSFT': Decimal('100')},
            {'AAPL': base, 'MSFT': correlated},
        )

        # Should be blocked due to high correlation
        assert not result.allowed
        assert result.max_correlation > 0.7
        assert len(result.correlated_symbols) > 0

    def test_zero_position_skipped(self):
        """Zero positions should be skipped in correlation check."""
        config = CorrelationLimitsConfig(enable=True, max_correlation=0.7, min_data_points=5)
        monitor = CorrelationMonitor(config)

        # MSFT has zero position
        result = monitor.check_correlation(
            'AAPL',
            {'MSFT': Decimal('0')},
            {'AAPL': [100 + i for i in range(30)], 'MSFT': [100 + i for i in range(30)]},
        )

        assert result.allowed

    def test_correlation_matrix_computation(self):
        """Portfolio correlation matrix should be computed correctly."""
        config = CorrelationLimitsConfig(enable=True, min_data_points=5)
        monitor = CorrelationMonitor(config)

        # Create price history
        aapl = [100 + i for i in range(30)]
        msft = [100 + i * 1.01 for i in range(30)]  # Highly correlated
        googl = [100 - i * 0.5 for i in range(30)]  # Inversely correlated

        matrix = monitor.compute_portfolio_correlation_matrix(
            ['AAPL', 'MSFT', 'GOOGL'],
            {'AAPL': aapl, 'MSFT': msft, 'GOOGL': googl},
        )

        # Diagonal should be 1.0
        assert matrix['AAPL']['AAPL'] == 1.0
        assert matrix['MSFT']['MSFT'] == 1.0
        assert matrix['GOOGL']['GOOGL'] == 1.0

        # AAPL-MSFT should be highly correlated
        assert matrix['AAPL']['MSFT'] > 0.9

        # AAPL-GOOGL should have some inverse correlation
        # (note: we use absolute correlation, so this might be high too)
        assert 0 <= matrix['AAPL']['GOOGL'] <= 1.0

    def test_thread_safety(self):
        """Monitor should be thread-safe."""
        config = CorrelationLimitsConfig(enable=True, min_data_points=5)
        monitor = CorrelationMonitor(config)

        price_history = {
            'AAPL': [100 + i for i in range(30)],
            'MSFT': [100 + i * 0.5 for i in range(30)],
        }

        results: list[CorrelationCheckResult] = []
        errors: list[Exception] = []
        results_lock = threading.Lock()

        def check():
            try:
                result = monitor.check_correlation(
                    'AAPL',
                    {'MSFT': Decimal('100')},
                    price_history,
                )
                with results_lock:
                    results.append(result)
            except Exception as e:
                with results_lock:
                    errors.append(e)

        threads = [threading.Thread(target=check) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
