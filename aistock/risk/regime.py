"""Market regime detection for position sizing."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..data import Bar
    from .advanced_config import RegimeDetectionConfig


class MarketRegime(str, Enum):
    """Market regime classification.

    Five regimes from strongly bullish to strongly bearish:
    - STRONG_BULL: Strong uptrend with high confidence
    - MILD_BULL: Moderate uptrend
    - SIDEWAYS: Range-bound or uncertain market
    - MILD_BEAR: Moderate downtrend
    - STRONG_BEAR: Strong downtrend with high confidence
    """

    STRONG_BULL = 'strong_bull'
    MILD_BULL = 'mild_bull'
    SIDEWAYS = 'sideways'
    MILD_BEAR = 'mild_bear'
    STRONG_BEAR = 'strong_bear'


@dataclass
class RegimeResult:
    """Result of regime detection."""

    regime: MarketRegime
    confidence: float
    position_multiplier: float
    rsi: float
    trend_return: float
    volatility: float
    reason: str


class RegimeDetector:
    """Detect market regime for position sizing adjustment.

    Classifies market into 5 regimes based on:
    - RSI (Relative Strength Index)
    - Trend return (N-bar price return)
    - Realized volatility

    Each regime maps to a position size multiplier:
    - Strong bull: 1.2x (more aggressive)
    - Mild bull: 1.0x (normal)
    - Sideways: 0.6x (reduced)
    - Mild bear: 0.4x (defensive)
    - Strong bear: 0.2x (highly defensive)

    Thread-safe for IBKR callback access.
    """

    def __init__(self, config: RegimeDetectionConfig) -> None:
        try:
            config.validate()
        except AttributeError as exc:
            raise ValueError('RegimeDetectionConfig missing validate method') from exc
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Invalid RegimeDetectionConfig: {exc}') from exc
        self.config = config
        self._lock = threading.Lock()

    def detect_regime(self, bars: list[Bar]) -> RegimeResult:
        """Detect current market regime from price bars.

        Args:
            bars: List of Bar objects (must have at least 15 bars for RSI)

        Returns:
            RegimeResult with regime classification and multiplier
        """
        with self._lock:
            min_bars = max(
                self.config.trend_lookback_bars,
                self.config.volatility_lookback_bars,
                15,  # RSI needs 14+1 bars
            )

            if len(bars) < min_bars:
                return RegimeResult(
                    regime=MarketRegime.SIDEWAYS,
                    confidence=0.0,
                    position_multiplier=self.config.sideways_multiplier,
                    rsi=50.0,
                    trend_return=0.0,
                    volatility=0.0,
                    reason=f'Insufficient data ({len(bars)} < {min_bars} bars)',
                )

            closes = [float(bar.close) for bar in bars]

            # Calculate indicators
            rsi = self._compute_rsi(closes)
            trend_return = self._compute_trend_return(closes)
            volatility = self._compute_volatility(closes)

            # Classify regime
            regime, confidence = self._classify_regime(rsi, trend_return, volatility)

            multiplier = self._get_multiplier(regime)

            return RegimeResult(
                regime=regime,
                confidence=confidence,
                position_multiplier=multiplier,
                rsi=rsi,
                trend_return=trend_return,
                volatility=volatility,
                reason=f'RSI={rsi:.1f}, Return={trend_return:.2%}, Vol={volatility:.2%}',
            )

    def _compute_rsi(self, closes: list[float], period: int = 14) -> float:
        """Compute Relative Strength Index.

        Args:
            closes: List of closing prices
            period: RSI calculation period (default 14)

        Returns:
            RSI value (0 to 100)
        """
        if len(closes) < period + 1:
            return 50.0

        deltas = np.diff(closes[-(period + 1) :])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _compute_trend_return(self, closes: list[float]) -> float:
        """Compute N-bar return for trend direction.

        Args:
            closes: List of closing prices

        Returns:
            Percentage return over lookback period
        """
        lookback = self.config.trend_lookback_bars
        if len(closes) <= lookback:
            return 0.0

        start_price = closes[-(lookback + 1)]
        end_price = closes[-1]

        if start_price <= 0:
            return 0.0

        return (end_price - start_price) / start_price

    def _compute_volatility(self, closes: list[float]) -> float:
        """Compute realized volatility (standard deviation of returns).

        Args:
            closes: List of closing prices

        Returns:
            Daily volatility as decimal (e.g., 0.02 = 2%)
        """
        lookback = self.config.volatility_lookback_bars
        if len(closes) <= lookback:
            return 0.0

        recent = closes[-(lookback + 1) :]
        arr = np.array(recent)

        with np.errstate(divide='ignore', invalid='ignore'):
            returns = np.diff(arr) / arr[:-1]

        # Filter invalid values
        returns = returns[np.isfinite(returns)]

        if len(returns) < 2:
            return 0.0

        return float(np.std(returns))

    def _classify_regime(
        self,
        rsi: float,
        trend_return: float,
        volatility: float,
    ) -> tuple[MarketRegime, float]:
        """Classify regime based on indicators.

        Args:
            rsi: RSI value (0-100)
            trend_return: N-bar return
            volatility: Realized volatility

        Returns:
            Tuple of (MarketRegime, confidence)
        """
        # Strong bull: High RSI, positive strong trend, low/normal volatility
        if (
            rsi >= self.config.rsi_strong_bull
            and trend_return > self.config.strong_trend_threshold
            and volatility < self.config.volatility_high_threshold
        ):
            return MarketRegime.STRONG_BULL, 0.9

        # Strong bear: Low RSI, negative strong trend, elevated volatility
        if (
            rsi <= self.config.rsi_strong_bear
            and trend_return < -self.config.strong_trend_threshold
            and volatility > self.config.volatility_low_threshold
        ):
            return MarketRegime.STRONG_BEAR, 0.9

        # Mild bull: Moderately high RSI, positive trend
        if rsi >= self.config.rsi_mild_bull and trend_return > 0:
            return MarketRegime.MILD_BULL, 0.7

        # Mild bear: Moderately low RSI, negative trend
        if rsi <= self.config.rsi_mild_bear and trend_return < 0:
            return MarketRegime.MILD_BEAR, 0.7

        # Sideways: Middle RSI range or conflicting signals
        return MarketRegime.SIDEWAYS, 0.5

    def _get_multiplier(self, regime: MarketRegime) -> float:
        """Get position size multiplier for regime.

        Args:
            regime: Market regime classification

        Returns:
            Position size multiplier
        """
        return {
            MarketRegime.STRONG_BULL: self.config.strong_bull_multiplier,
            MarketRegime.MILD_BULL: self.config.mild_bull_multiplier,
            MarketRegime.SIDEWAYS: self.config.sideways_multiplier,
            MarketRegime.MILD_BEAR: self.config.mild_bear_multiplier,
            MarketRegime.STRONG_BEAR: self.config.strong_bear_multiplier,
        }[regime]
