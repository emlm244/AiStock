"""Tests for Kelly Criterion position sizing."""

import pytest

from aistock.risk.advanced_config import KellyCriterionConfig
from aistock.risk.kelly import KellyCriterionSizer, KellyResult


class MockPerformanceProvider:
    """Mock performance provider for testing."""

    def __init__(self, performance: dict[str, dict[str, float | int]]):
        self._performance = performance

    @property
    def symbol_performance(self) -> dict[str, dict[str, float | int]]:
        return self._performance


class TestKellyCriterionConfig:
    """Tests for KellyCriterionConfig validation."""

    def test_default_config_is_valid(self):
        """Default configuration should be valid."""
        config = KellyCriterionConfig()
        config.validate()  # Should not raise

    def test_invalid_fraction_raises(self):
        """Fraction outside (0, 1] should raise."""
        config = KellyCriterionConfig(fraction=0.0)
        with pytest.raises(ValueError, match='fraction must be in'):
            config.validate()

        config = KellyCriterionConfig(fraction=1.5)
        with pytest.raises(ValueError, match='fraction must be in'):
            config.validate()

    def test_invalid_min_trades_raises(self):
        """min_trades_required < 1 should raise."""
        config = KellyCriterionConfig(min_trades_required=0)
        with pytest.raises(ValueError, match='min_trades_required must be >= 1'):
            config.validate()

    def test_invalid_kelly_caps_raises(self):
        """min_kelly_fraction >= max_kelly_fraction should raise."""
        config = KellyCriterionConfig(min_kelly_fraction=0.3, max_kelly_fraction=0.2)
        with pytest.raises(ValueError, match='min_kelly_fraction'):
            config.validate()


class TestKellyCriterionSizer:
    """Tests for KellyCriterionSizer."""

    def test_no_performance_data_returns_fallback(self):
        """Symbol with no performance data should return fallback."""
        config = KellyCriterionConfig(enable=True)
        sizer = KellyCriterionSizer(config)
        provider = MockPerformanceProvider({})

        result = sizer.calculate('AAPL', provider)

        assert result.is_fallback
        assert result.applied_fraction == config.fallback_fraction
        assert result.trade_count == 0

    def test_insufficient_trades_returns_fallback(self):
        """Symbol with insufficient trades should return fallback."""
        config = KellyCriterionConfig(enable=True, min_trades_required=10)
        sizer = KellyCriterionSizer(config)
        provider = MockPerformanceProvider({
            'AAPL': {'trades': 5, 'wins': 3, 'total_pnl': 100.0, 'confidence_adj': 0.0}
        })

        result = sizer.calculate('AAPL', provider)

        assert result.is_fallback
        assert result.applied_fraction == config.fallback_fraction
        assert result.trade_count == 5

    def test_no_wins_returns_min_fraction(self):
        """Symbol with no winning trades should return min fraction."""
        config = KellyCriterionConfig(enable=True, min_trades_required=5)
        sizer = KellyCriterionSizer(config)
        provider = MockPerformanceProvider({
            'AAPL': {'trades': 10, 'wins': 0, 'total_pnl': -500.0, 'confidence_adj': 0.0}
        })

        result = sizer.calculate('AAPL', provider)

        assert result.is_fallback
        assert result.applied_fraction == config.min_kelly_fraction
        assert result.win_rate == 0.0

    def test_all_wins_returns_max_fraction(self):
        """Symbol with all winning trades should return max fraction."""
        config = KellyCriterionConfig(enable=True, min_trades_required=5)
        sizer = KellyCriterionSizer(config)
        provider = MockPerformanceProvider({
            'AAPL': {'trades': 10, 'wins': 10, 'total_pnl': 1000.0, 'confidence_adj': 0.0}
        })

        result = sizer.calculate('AAPL', provider)

        assert not result.is_fallback
        assert result.applied_fraction == config.max_kelly_fraction
        assert result.win_rate == 1.0

    def test_profitable_symbol_calculates_kelly(self):
        """Symbol with positive edge should calculate positive Kelly."""
        config = KellyCriterionConfig(
            enable=True,
            min_trades_required=5,
            fraction=0.5,  # Half-Kelly
        )
        sizer = KellyCriterionSizer(config)
        # 70% win rate, profitable
        provider = MockPerformanceProvider({
            'AAPL': {'trades': 20, 'wins': 14, 'total_pnl': 5000.0, 'confidence_adj': 0.0}
        })

        result = sizer.calculate('AAPL', provider)

        assert not result.is_fallback
        assert result.kelly_fraction > 0
        assert config.min_kelly_fraction <= result.applied_fraction <= config.max_kelly_fraction
        assert result.win_rate == 0.7

    def test_unprofitable_symbol_calculates_negative_kelly(self):
        """Symbol with negative edge should have negative Kelly -> min fraction."""
        config = KellyCriterionConfig(
            enable=True,
            min_trades_required=5,
            fraction=0.5,
        )
        sizer = KellyCriterionSizer(config)
        # 30% win rate, unprofitable
        provider = MockPerformanceProvider({
            'AAPL': {'trades': 20, 'wins': 6, 'total_pnl': -2000.0, 'confidence_adj': 0.0}
        })

        result = sizer.calculate('AAPL', provider)

        # With negative edge, Kelly should be negative or very low
        assert result.applied_fraction == config.min_kelly_fraction
        assert result.win_rate == 0.3

    def test_thread_safety(self):
        """Sizer should be thread-safe."""
        import threading

        config = KellyCriterionConfig(enable=True, min_trades_required=5)
        sizer = KellyCriterionSizer(config)
        provider = MockPerformanceProvider({
            'AAPL': {'trades': 20, 'wins': 14, 'total_pnl': 1000.0, 'confidence_adj': 0.0}
        })

        results: list[KellyResult] = []
        errors: list[Exception] = []

        def calculate():
            try:
                result = sizer.calculate('AAPL', provider)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=calculate) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # All results should be identical
        first = results[0].applied_fraction
        assert all(r.applied_fraction == first for r in results)
