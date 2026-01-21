"""Tests for AdvancedRiskManager composite class."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from aistock.data import Bar
from aistock.risk import (
    AdvancedRiskConfig,
    AdvancedRiskManager,
    AdvancedRiskResult,
    CorrelationLimitsConfig,
    KellyCriterionConfig,
    RegimeDetectionConfig,
    VolatilityScalingConfig,
)


def make_bars(closes: list[float], symbol: str = 'TEST') -> list[Bar]:
    """Create Bar objects from a list of closing prices."""
    bars = []
    for i, close in enumerate(closes):
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, 10, i, tzinfo=timezone.utc),
                open=Decimal(str(close)),
                high=Decimal(str(close * 1.01)),
                low=Decimal(str(close * 0.99)),
                close=Decimal(str(close)),
                volume=1000,
            )
        )
    return bars


class MockPerformanceProvider:
    """Mock performance provider for testing."""

    def __init__(self, performance: dict[str, dict[str, float | int]]):
        self._performance = performance

    @property
    def symbol_performance(self) -> dict[str, dict[str, float | int]]:
        return self._performance


class TestAdvancedRiskConfig:
    """Tests for AdvancedRiskConfig."""

    def test_default_config_is_valid(self):
        """Default configuration should be valid."""
        config = AdvancedRiskConfig()
        config.validate()

    def test_all_features_disabled_by_default(self):
        """All features should be disabled by default."""
        config = AdvancedRiskConfig()
        assert not config.kelly.enable
        assert not config.correlation.enable
        assert not config.regime.enable
        assert not config.volatility_scaling.enable

    def test_validates_all_sub_configs(self):
        """Should validate all sub-configurations."""
        config = AdvancedRiskConfig(
            kelly=KellyCriterionConfig(fraction=1.5),  # Invalid
        )
        with pytest.raises(ValueError, match='fraction must be in'):
            config.validate()


class TestAdvancedRiskManager:
    """Tests for AdvancedRiskManager."""

    def test_no_features_enabled_returns_neutral(self):
        """With no features enabled, should return neutral multiplier."""
        config = AdvancedRiskConfig()
        manager = AdvancedRiskManager(config)

        result = manager.evaluate(
            symbol='AAPL',
            bars=make_bars([100 + i for i in range(35)]),
            last_prices={},
            current_positions={},
            price_history={},
        )

        assert result.allowed
        assert result.position_size_multiplier == 1.0
        assert 'No advanced risk checks enabled' in result.reason

    def test_is_any_enabled(self):
        """is_any_enabled should reflect feature status."""
        config = AdvancedRiskConfig()
        manager = AdvancedRiskManager(config)
        assert not manager.is_any_enabled()

        config = AdvancedRiskConfig(
            kelly=KellyCriterionConfig(enable=True)
        )
        manager = AdvancedRiskManager(config)
        assert manager.is_any_enabled()

    def test_kelly_multiplier_applied(self):
        """Kelly multiplier should affect final position size."""
        config = AdvancedRiskConfig(
            kelly=KellyCriterionConfig(
                enable=True,
                min_trades_required=5,
                fallback_fraction=0.05,
            )
        )
        manager = AdvancedRiskManager(config)

        provider = MockPerformanceProvider({
            'AAPL': {'trades': 20, 'wins': 14, 'total_pnl': 5000.0, 'confidence_adj': 0.0}
        })

        result = manager.evaluate(
            symbol='AAPL',
            bars=make_bars([100 + i for i in range(35)]),
            last_prices={},
            current_positions={},
            price_history={},
            performance_provider=provider,
        )

        assert result.allowed
        assert result.kelly is not None
        # Multiplier should be adjusted based on Kelly
        assert 'Kelly' in result.reason

    def test_correlation_blocks_trade(self):
        """High correlation should block trade."""
        config = AdvancedRiskConfig(
            correlation=CorrelationLimitsConfig(
                enable=True,
                max_correlation=0.5,
                min_data_points=5,
                block_on_high_correlation=True,
            )
        )
        manager = AdvancedRiskManager(config)

        # Highly correlated price series
        base = [100 + i * 0.5 for i in range(30)]
        correlated = [100 + i * 0.51 for i in range(30)]

        result = manager.evaluate(
            symbol='AAPL',
            bars=make_bars(base),
            last_prices={},
            current_positions={'MSFT': Decimal('100')},
            price_history={'AAPL': base, 'MSFT': correlated},
        )

        assert not result.allowed
        assert result.correlation is not None
        assert 'BLOCKED' in result.reason

    def test_regime_multiplier_applied(self):
        """Regime multiplier should affect final position size."""
        config = AdvancedRiskConfig(
            regime=RegimeDetectionConfig(
                enable=True,
                strong_bear_multiplier=0.2,
            )
        )
        manager = AdvancedRiskManager(config)

        # Strong downtrend
        bars = make_bars([100 - i * 1.0 for i in range(35)])

        result = manager.evaluate(
            symbol='AAPL',
            bars=bars,
            last_prices={},
            current_positions={},
            price_history={},
        )

        assert result.allowed
        assert result.regime is not None
        assert 'Regime' in result.reason

    def test_volatility_multiplier_applied(self):
        """Volatility multiplier should affect final position size."""
        config = AdvancedRiskConfig(
            volatility_scaling=VolatilityScalingConfig(
                enable=True,
                vix_high_threshold=30,
                max_scale_down=0.25,
            )
        )
        manager = AdvancedRiskManager(config)

        result = manager.evaluate(
            symbol='AAPL',
            bars=make_bars([100 + i for i in range(35)]),
            last_prices={'VIX': Decimal('40')},  # High VIX
            current_positions={},
            price_history={},
        )

        assert result.allowed
        assert result.volatility is not None
        assert result.position_size_multiplier < 1.0
        assert 'VolScale' in result.reason

    def test_all_features_composite_multiplier(self):
        """All features combined should multiply together."""
        config = AdvancedRiskConfig(
            kelly=KellyCriterionConfig(
                enable=True,
                min_trades_required=5,
                fallback_fraction=0.05,
            ),
            regime=RegimeDetectionConfig(
                enable=True,
                sideways_multiplier=0.6,
            ),
            volatility_scaling=VolatilityScalingConfig(
                enable=True,
            ),
        )
        manager = AdvancedRiskManager(config)

        provider = MockPerformanceProvider({
            'AAPL': {'trades': 20, 'wins': 14, 'total_pnl': 5000.0, 'confidence_adj': 0.0}
        })

        result = manager.evaluate(
            symbol='AAPL',
            bars=make_bars([100 + (i % 5) - 2 for i in range(35)]),  # Sideways
            last_prices={'VIX': Decimal('20')},
            current_positions={},
            price_history={},
            performance_provider=provider,
        )

        assert result.allowed
        # Should have components from all features
        assert result.kelly is not None
        assert result.regime is not None
        assert result.volatility is not None

    def test_multiplier_capped(self):
        """Final multiplier should be capped to reasonable bounds."""
        config = AdvancedRiskConfig(
            regime=RegimeDetectionConfig(
                enable=True,
                strong_bull_multiplier=5.0,  # Very high
            ),
            volatility_scaling=VolatilityScalingConfig(
                enable=True,
                max_scale_up=3.0,  # Also high
            ),
        )
        manager = AdvancedRiskManager(config)

        result = manager.evaluate(
            symbol='AAPL',
            bars=make_bars([100 + i * 2 for i in range(35)]),  # Strong uptrend
            last_prices={'VIX': Decimal('10')},  # Low VIX
            current_positions={},
            price_history={},
        )

        # Should be capped to 3.0 (or whatever the max is)
        assert result.position_size_multiplier <= 3.0
        assert result.position_size_multiplier >= 0.01

    def test_thread_safety(self):
        """Manager should be thread-safe."""
        import threading

        config = AdvancedRiskConfig(
            regime=RegimeDetectionConfig(enable=True)
        )
        manager = AdvancedRiskManager(config)
        bars = make_bars([100 + i * 0.5 for i in range(35)])

        results: list[AdvancedRiskResult] = []
        errors: list[Exception] = []

        def evaluate():
            try:
                result = manager.evaluate(
                    symbol='AAPL',
                    bars=bars,
                    last_prices={},
                    current_positions={},
                    price_history={},
                )
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=evaluate) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # All results should have same multiplier
        first = results[0].position_size_multiplier
        assert all(abs(r.position_size_multiplier - first) < 0.001 for r in results)
