"""Tests for volatility-based position scaling."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from aistock.data import Bar
from aistock.risk.advanced_config import VolatilityScalingConfig
from aistock.risk.volatility_scaling import VolatilityScaler, VolatilityScaleResult


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


class TestVolatilityScalingConfig:
    """Tests for VolatilityScalingConfig validation."""

    def test_default_config_is_valid(self):
        """Default configuration should be valid."""
        config = VolatilityScalingConfig()
        config.validate()

    def test_invalid_target_volatility_raises(self):
        """target_volatility <= 0 should raise."""
        config = VolatilityScalingConfig(target_volatility=0)
        with pytest.raises(ValueError, match='target_volatility must be positive'):
            config.validate()

    def test_invalid_max_scale_up_raises(self):
        """max_scale_up < 1 should raise."""
        config = VolatilityScalingConfig(max_scale_up=0.5)
        with pytest.raises(ValueError, match='max_scale_up must be >= 1.0'):
            config.validate()

    def test_invalid_max_scale_down_raises(self):
        """max_scale_down outside (0, 1] should raise."""
        config = VolatilityScalingConfig(max_scale_down=0)
        with pytest.raises(ValueError, match='max_scale_down must be in'):
            config.validate()

    def test_invalid_vix_thresholds_raises(self):
        """vix_low >= vix_high should raise."""
        config = VolatilityScalingConfig(vix_low_threshold=35, vix_high_threshold=30)
        with pytest.raises(ValueError, match='vix_low_threshold'):
            config.validate()


class TestVolatilityScaler:
    """Tests for VolatilityScaler."""

    def test_vix_scaling_high_vix(self):
        """High VIX should scale down position."""
        config = VolatilityScalingConfig(
            enable=True,
            vix_high_threshold=30,
            max_scale_down=0.25,
        )
        scaler = VolatilityScaler(config)

        # VIX at 40 (high)
        result = scaler.compute_scale(
            bars=[],
            last_prices={'VIX': Decimal('40')},
            state=None,
        )

        assert result.source == 'vix'
        assert result.scale_factor == config.max_scale_down
        assert result.vix_value == 40.0

    def test_vix_scaling_low_vix(self):
        """Low VIX should scale up position."""
        config = VolatilityScalingConfig(
            enable=True,
            vix_low_threshold=15,
            max_scale_up=2.0,
        )
        scaler = VolatilityScaler(config)

        # VIX at 12 (low)
        result = scaler.compute_scale(
            bars=[],
            last_prices={'VIX': Decimal('12')},
            state=None,
        )

        assert result.source == 'vix'
        assert result.scale_factor == config.max_scale_up
        assert result.vix_value == 12.0

    def test_vix_scaling_interpolation(self):
        """VIX between thresholds should interpolate scale."""
        config = VolatilityScalingConfig(
            enable=True,
            vix_low_threshold=15,
            vix_high_threshold=30,
            max_scale_up=2.0,
            max_scale_down=0.5,
        )
        scaler = VolatilityScaler(config)

        # VIX at 22.5 (midpoint)
        result = scaler.compute_scale(
            bars=[],
            last_prices={'VIX': Decimal('22.5')},
            state=None,
        )

        assert result.source == 'vix'
        # Midpoint should give ~1.25 (midpoint of 2.0 and 0.5)
        assert 1.0 <= result.scale_factor <= 1.5

    def test_vix_from_state(self):
        """VIX should be read from state dict."""
        config = VolatilityScalingConfig(enable=True)
        scaler = VolatilityScaler(config)

        # VIX in state
        result = scaler.compute_scale(
            bars=[],
            last_prices={},
            state={'vix_level': 25.0},
        )

        assert result.source == 'vix'
        assert result.vix_value == 25.0

    def test_vix_symbols_priority(self):
        """VIX symbols should be checked in order."""
        config = VolatilityScalingConfig(
            enable=True,
            vix_symbols=('VIX', '^VIX', 'VIXY'),
        )
        scaler = VolatilityScaler(config)

        # Only VIXY available
        result = scaler.compute_scale(
            bars=[],
            last_prices={'VIXY': Decimal('20')},
            state=None,
        )

        assert result.source == 'vix'
        assert result.vix_value == 20.0

    def test_realized_vol_fallback(self):
        """Should fall back to realized volatility when VIX unavailable."""
        config = VolatilityScalingConfig(
            enable=True,
            use_realized_vol_fallback=True,
            realized_vol_lookback=20,
            target_volatility=0.15,
        )
        scaler = VolatilityScaler(config)

        # Create bars with ~10% annualized volatility
        bars = make_bars([100 + i * 0.1 for i in range(25)])

        result = scaler.compute_scale(
            bars=bars,
            last_prices={},
            state=None,
        )

        assert result.source == 'realized'
        assert result.realized_volatility is not None
        assert result.vix_value is None

    def test_fallback_disabled(self):
        """Should return 1.0 when fallback disabled and no VIX."""
        config = VolatilityScalingConfig(
            enable=True,
            use_realized_vol_fallback=False,
        )
        scaler = VolatilityScaler(config)

        result = scaler.compute_scale(
            bars=[],
            last_prices={},
            state=None,
        )

        assert result.source == 'none'
        assert result.scale_factor == 1.0

    def test_insufficient_bars_for_realized(self):
        """Should return 1.0 when insufficient bars for realized vol."""
        config = VolatilityScalingConfig(
            enable=True,
            use_realized_vol_fallback=True,
            realized_vol_lookback=20,
        )
        scaler = VolatilityScaler(config)

        # Only 10 bars (need 21)
        bars = make_bars([100 + i for i in range(10)])

        result = scaler.compute_scale(
            bars=bars,
            last_prices={},
            state=None,
        )

        assert result.source == 'none'
        assert result.scale_factor == 1.0

    def test_realized_vol_scaling(self):
        """Realized volatility should scale positions correctly."""
        config = VolatilityScalingConfig(
            enable=True,
            use_realized_vol_fallback=True,
            target_volatility=0.15,
            max_scale_up=2.0,
            max_scale_down=0.25,
            realized_vol_lookback=20,
        )
        scaler = VolatilityScaler(config)

        # Low volatility bars (small changes)
        low_vol_bars = make_bars([100 + i * 0.001 for i in range(25)])
        result = scaler.compute_scale(low_vol_bars, {}, None)

        # Low vol should scale up
        assert result.source == 'realized'
        assert result.scale_factor >= 1.0

    def test_thread_safety(self):
        """Scaler should be thread-safe."""
        import threading

        config = VolatilityScalingConfig(enable=True)
        scaler = VolatilityScaler(config)

        results: list[VolatilityScaleResult] = []
        errors: list[Exception] = []

        def scale():
            try:
                result = scaler.compute_scale(
                    bars=[],
                    last_prices={'VIX': Decimal('20')},
                    state=None,
                )
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=scale) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
