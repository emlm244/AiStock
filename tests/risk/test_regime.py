"""Tests for market regime detection."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from aistock.data import Bar
from aistock.risk.advanced_config import RegimeDetectionConfig
from aistock.risk.regime import MarketRegime, RegimeDetector, RegimeResult


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


class TestRegimeDetectionConfig:
    """Tests for RegimeDetectionConfig validation."""

    def test_default_config_is_valid(self):
        """Default configuration should be valid."""
        config = RegimeDetectionConfig()
        config.validate()

    def test_invalid_rsi_thresholds_raises(self):
        """Non-monotonic RSI thresholds should raise."""
        config = RegimeDetectionConfig(rsi_strong_bear=50, rsi_mild_bear=40)
        with pytest.raises(ValueError, match='RSI thresholds must be monotonically increasing'):
            config.validate()

    def test_invalid_volatility_thresholds_raises(self):
        """low >= high volatility threshold should raise."""
        config = RegimeDetectionConfig(
            volatility_low_threshold=0.03,
            volatility_high_threshold=0.02,
        )
        with pytest.raises(ValueError, match='volatility_low_threshold'):
            config.validate()

    def test_negative_multiplier_raises(self):
        """Negative position multiplier should raise."""
        config = RegimeDetectionConfig(strong_bull_multiplier=-0.5)
        with pytest.raises(ValueError, match='must be positive'):
            config.validate()


class TestRegimeDetector:
    """Tests for RegimeDetector."""

    def test_insufficient_data_returns_sideways(self):
        """Insufficient bars should return sideways regime."""
        config = RegimeDetectionConfig(enable=True)
        detector = RegimeDetector(config)

        # Only 5 bars (need 20+)
        bars = make_bars([100 + i for i in range(5)])

        result = detector.detect_regime(bars)

        assert result.regime == MarketRegime.SIDEWAYS
        assert result.confidence == 0.0
        assert 'Insufficient data' in result.reason

    def test_strong_uptrend_detects_bull(self):
        """Strong uptrend should be detected as bull regime."""
        config = RegimeDetectionConfig(enable=True)
        detector = RegimeDetector(config)

        # Strong uptrend: +30% over 30 bars
        bars = make_bars([100 + i * 1.0 for i in range(35)])

        result = detector.detect_regime(bars)

        assert result.regime in [MarketRegime.STRONG_BULL, MarketRegime.MILD_BULL]
        assert result.trend_return > 0

    def test_strong_downtrend_detects_bear(self):
        """Strong downtrend should be detected as bear regime."""
        config = RegimeDetectionConfig(enable=True)
        detector = RegimeDetector(config)

        # Strong downtrend: -20% over 30 bars
        bars = make_bars([100 - i * 0.8 for i in range(35)])

        result = detector.detect_regime(bars)

        assert result.regime in [MarketRegime.STRONG_BEAR, MarketRegime.MILD_BEAR]
        assert result.trend_return < 0

    def test_sideways_market_detects_sideways(self):
        """Range-bound market should be detected as sideways."""
        config = RegimeDetectionConfig(enable=True)
        detector = RegimeDetector(config)

        # Sideways: oscillating around 100
        bars = make_bars([100 + (i % 5) - 2 for i in range(35)])

        result = detector.detect_regime(bars)

        # Could be sideways or mild depending on exact values
        assert result.regime in [MarketRegime.SIDEWAYS, MarketRegime.MILD_BULL, MarketRegime.MILD_BEAR]

    def test_regime_multipliers_applied(self):
        """Correct position multipliers should be returned per regime."""
        config = RegimeDetectionConfig(
            enable=True,
            strong_bull_multiplier=1.5,
            mild_bull_multiplier=1.0,
            sideways_multiplier=0.5,
            mild_bear_multiplier=0.3,
            strong_bear_multiplier=0.1,
        )
        detector = RegimeDetector(config)

        # Strong uptrend
        bars = make_bars([100 + i * 2 for i in range(35)])
        result = detector.detect_regime(bars)

        if result.regime == MarketRegime.STRONG_BULL:
            assert result.position_multiplier == 1.5
        elif result.regime == MarketRegime.MILD_BULL:
            assert result.position_multiplier == 1.0

    def test_rsi_calculation(self):
        """RSI should be calculated correctly."""
        config = RegimeDetectionConfig(enable=True)
        detector = RegimeDetector(config)

        # Strong uptrend should have high RSI
        bars = make_bars([100 + i * 0.5 for i in range(35)])
        result = detector.detect_regime(bars)
        assert result.rsi > 50  # Uptrend = RSI > 50

        # Strong downtrend should have low RSI
        bars = make_bars([100 - i * 0.5 for i in range(35)])
        result = detector.detect_regime(bars)
        assert result.rsi < 50  # Downtrend = RSI < 50

    def test_volatility_calculation(self):
        """Volatility should be calculated correctly."""
        config = RegimeDetectionConfig(enable=True)
        detector = RegimeDetector(config)

        # Low volatility: small price changes
        bars = make_bars([100 + i * 0.01 for i in range(35)])
        result = detector.detect_regime(bars)
        assert result.volatility < 0.01

        # Higher volatility: larger price changes
        bars = make_bars([100 + (i % 5 - 2) * 5 for i in range(35)])
        result = detector.detect_regime(bars)
        assert result.volatility > 0.01

    def test_thread_safety(self):
        """Detector should be thread-safe."""
        import threading

        config = RegimeDetectionConfig(enable=True)
        detector = RegimeDetector(config)
        bars = make_bars([100 + i * 0.5 for i in range(35)])

        results: list[RegimeResult] = []
        errors: list[Exception] = []

        def detect():
            try:
                result = detector.detect_regime(bars)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=detect) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # All results should be identical
        first = results[0].regime
        assert all(r.regime == first for r in results)
