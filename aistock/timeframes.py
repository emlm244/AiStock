"""
Professional Multi-Timeframe Analysis Module.

This module provides:
- Multi-timeframe bar aggregation and management
- Cross-timeframe correlation analysis
- Timeframe confluence detection
- Professional trading signals based on timeframe alignment
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from threading import Lock
from typing import Any

from .data import Bar
from .logging import configure_logger


class Trend(str, Enum):
    """Trend direction."""

    UP = 'up'
    DOWN = 'down'
    NEUTRAL = 'neutral'


class Timeframe(str, Enum):
    """Supported timeframes."""

    FIVE_SEC = '5s'
    THIRTY_SEC = '30s'
    ONE_MIN = '1m'
    FIVE_MIN = '5m'
    FIFTEEN_MIN = '15m'
    THIRTY_MIN = '30m'
    ONE_HOUR = '1h'
    FOUR_HOUR = '4h'
    ONE_DAY = '1d'


# Mapping timeframe strings to seconds (for IBKR bar_size parameter)
# Use string keys throughout to align with public APIs and avoid enum/string mismatches.
TIMEFRAME_TO_SECONDS: dict[str, int] = {
    Timeframe.FIVE_SEC.value: 5,
    Timeframe.THIRTY_SEC.value: 30,
    Timeframe.ONE_MIN.value: 60,
    Timeframe.FIVE_MIN.value: 300,
    Timeframe.FIFTEEN_MIN.value: 900,
    Timeframe.THIRTY_MIN.value: 1800,
    Timeframe.ONE_HOUR.value: 3600,
    Timeframe.FOUR_HOUR.value: 14400,
    Timeframe.ONE_DAY.value: 86400,
}

# Reverse mapping for display (seconds -> timeframe string)
SECONDS_TO_TIMEFRAME: dict[int, str] = {v: k for k, v in TIMEFRAME_TO_SECONDS.items()}


@dataclass
class TimeframeState:
    """State for a single timeframe."""

    trend: Trend
    momentum: float  # -1.0 to 1.0
    volatility: float  # 0.0 to 1.0
    volume_ratio: float  # Current volume vs average
    last_bar: Bar | None


@dataclass
class CrossTimeframeAnalysis:
    """Analysis across multiple timeframes."""

    confluence: bool  # All timeframes agree on direction
    fast_leads_medium: bool  # Fast timeframe predicting medium
    medium_leads_slow: bool  # Medium timeframe predicting slow
    divergence_detected: bool  # Timeframes disagree (risky!)
    confidence_adjustment: float  # -0.3 to +0.3 adjustment to base confidence
    dominant_trend: Trend  # Weighted trend across all timeframes
    timeframe_states: dict[str, TimeframeState]


class TimeframeManager:
    """
    Professional multi-timeframe bar management and analysis.

    Manages bars across multiple timeframes for each symbol and provides
    cross-timeframe correlation analysis used by professional traders.
    """

    def __init__(self, symbols: list[str], timeframes: list[str], max_bars_per_timeframe: int = 500):
        """
        Initialize TimeframeManager.

        Args:
            symbols: List of symbols to track
            timeframes: List of timeframes (e.g., ['1m', '5m', '15m'])
            max_bars_per_timeframe: Maximum bars to keep in memory per timeframe
        """
        self.symbols = symbols
        self.timeframes = self._validate_timeframes(timeframes)
        self.max_bars = max_bars_per_timeframe
        self.logger = configure_logger('TimeframeManager', structured=True)

        # P0 Fix (Code Review): Thread safety lock for IBKR callback access
        self._lock = Lock()

        # Data structure: {symbol: {timeframe: [bars]}}
        self.bars: dict[str, dict[str, list[Bar]]] = defaultdict(lambda: defaultdict(list))

        # Timeframe states: {symbol: {timeframe: TimeframeState}}
        self._states: dict[str, dict[str, TimeframeState]] = defaultdict(dict)

    def _validate_timeframes(self, timeframes: list[str]) -> list[str]:
        """Validate and normalize timeframe strings."""
        validated = []
        for tf in timeframes:
            tf_lower = tf.lower().strip()
            if tf_lower not in TIMEFRAME_TO_SECONDS:
                self.logger.warning(
                    'invalid_timeframe',
                    extra={'timeframe': tf, 'valid_options': list(TIMEFRAME_TO_SECONDS.keys())},
                )
                continue
            validated.append(tf_lower)

        if not validated:
            # Default to 1m if no valid timeframes
            validated = [Timeframe.ONE_MIN.value]
            self.logger.warning('no_valid_timeframes_using_default', extra={'default': Timeframe.ONE_MIN.value})

        return validated

    def add_bar(self, symbol: str, timeframe: str, bar: Bar) -> None:
        """
        Add a bar to the manager.

        P0 Fix (Code Review): Thread-safe to prevent race conditions with IBKR callbacks.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe string (e.g., '1m')
            bar: Bar to add
        """
        timeframe = timeframe.lower()
        if timeframe not in self.timeframes:
            return

        with self._lock:  # P0 Fix: Thread safety
            bars = self.bars[symbol][timeframe]
            bars.append(bar)

            # Keep memory bounded
            if len(bars) > self.max_bars:
                # Remove oldest 20% of bars
                remove_count = len(bars) - self.max_bars
                del bars[:remove_count]

        # Update state for this timeframe
        self._update_timeframe_state(symbol, timeframe)

    def get_bars(self, symbol: str, timeframe: str, lookback: int | None = None) -> list[Bar]:
        """
        Get bars for a symbol and timeframe.

        P0 Fix (CRITICAL-1): Thread-safe to prevent race conditions with add_bar().

        Args:
            symbol: Trading symbol
            timeframe: Timeframe string
            lookback: Number of recent bars (None = all)

        Returns:
            List of bars (may be empty, always a copy)
        """
        timeframe = timeframe.lower()

        with self._lock:  # P0 Fix: Thread safety
            bars = self.bars[symbol].get(timeframe, [])

            if lookback is None:
                return bars.copy()

            return bars[-lookback:].copy() if bars else []

    def _update_timeframe_state(self, symbol: str, timeframe: str) -> None:
        """
        Update state for a specific symbol/timeframe.

        CRITICAL FIX: Keep lock held through state calculations to prevent race conditions.
        """
        # CRITICAL FIX: Hold lock for entire state update, not just bar copy
        with self._lock:
            bars = self.bars[symbol][timeframe].copy()

            if len(bars) < 10:
                return  # Need minimum bars for analysis

            # Calculate trend
            trend = self._calculate_trend(bars[-20:])

            # Calculate momentum (rate of change)
            momentum = self._calculate_momentum(bars[-20:])

            # Calculate volatility
            volatility = self._calculate_volatility(bars[-20:])

            # Calculate volume ratio
            volume_ratio = self._calculate_volume_ratio(bars[-20:])

            # Store state (still under lock)
            self._states[symbol][timeframe] = TimeframeState(
                trend=trend,
                momentum=momentum,
                volatility=volatility,
                volume_ratio=volume_ratio,
                last_bar=bars[-1],
            )

    def _calculate_trend(self, bars: list[Bar]) -> Trend:
        """
        Calculate trend from bars using moving averages.

        Professional logic: Fast MA vs Slow MA crossover.
        """
        if len(bars) < 10:
            return Trend.NEUTRAL

        closes = [bar.close for bar in bars]

        # Fast MA (5 bars)
        fast_ma = sum(closes[-5:]) / 5

        # Slow MA (10 bars)
        slow_ma = sum(closes[-10:]) / 10

        # Trend determination
        diff_pct = (fast_ma - slow_ma) / slow_ma if slow_ma > 0 else 0

        if diff_pct > 0.01:  # 1% above
            return Trend.UP
        elif diff_pct < -0.01:  # 1% below
            return Trend.DOWN
        else:
            return Trend.NEUTRAL

    def _calculate_momentum(self, bars: list[Bar]) -> float:
        """
        Calculate momentum as rate of price change.

        Returns: -1.0 to +1.0
        """
        if len(bars) < 2:
            return 0.0

        first_price = bars[0].close
        last_price = bars[-1].close

        if first_price == 0:
            return 0.0

        # Momentum as percentage change, clamped to [-1, 1] using Decimal math
        momentum = (last_price - first_price) / first_price
        scaled = momentum * Decimal('10')
        clamped = max(Decimal('-1'), min(Decimal('1'), scaled))
        return float(clamped)  # expose as float for downstream consumers

    def _calculate_volatility(self, bars: list[Bar]) -> float:
        """
        Calculate volatility as standard deviation of returns.

        Returns: 0.0 to 1.0 (normalized)
        """
        if len(bars) < 2:
            return 0.0

        closes = [bar.close for bar in bars]
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]

        if not returns:
            return 0.0

        # Standard deviation
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        # P0-7 Fix: Use Decimal.sqrt() instead of ** 0.5 for Decimal compatibility
        std_dev = variance.sqrt() if hasattr(variance, 'sqrt') else variance ** Decimal('0.5')

        # Normalize to 0-1 range (assume 5% std dev = high volatility)
        # P0-7 Fix: Return float for compatibility (volatility is used as multiplier)
        return min(1.0, float(std_dev) / 0.05)

    def _calculate_volume_ratio(self, bars: list[Bar]) -> float:
        """
        Calculate current volume vs average volume.

        Returns: Ratio (1.0 = average, 2.0 = double average)
        """
        if len(bars) < 2:
            return 1.0

        volumes = [bar.volume for bar in bars]
        avg_volume = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1

        current_volume = volumes[-1]

        if avg_volume == 0:
            return 1.0

        return current_volume / avg_volume

    def _validate_timeframe_sync(self, symbol: str) -> tuple[bool, str]:
        """
        P1-2 Fix: Validate that all timeframes have synchronized data.
        P0 Fix (Code Review): Thread-safe to prevent race conditions with add_bar().

        Checks that bar timestamps across timeframes are within acceptable drift.
        Prevents trading on misaligned timeframe data (e.g., 1m at 10:05, 5m at 10:00).

        Args:
            symbol: Trading symbol to validate

        Returns:
            Tuple of (is_valid, reason_if_invalid)
        """
        from datetime import timedelta

        with self._lock:  # P0 Fix: Thread safety
            states = self._states.get(symbol, {})

            if len(states) < 2:
                return (True, '')  # Single timeframe doesn't need sync check

            # Get last bar timestamp from each timeframe
            timestamps = []
            for tf, state in states.items():
                if state.last_bar:
                    timestamps.append((tf, state.last_bar.timestamp))

            if len(timestamps) < 2:
                return (False, 'Insufficient bar data across timeframes')

            # Check maximum drift between timeframes
            # Allow drift based on slowest timeframe (e.g., 15m timeframe = 15 min drift OK)
            max_timestamp = max(ts for _, ts in timestamps)
            min_timestamp = min(ts for _, ts in timestamps)
            drift = max_timestamp - min_timestamp

            # Find slowest timeframe in use
            slowest_seconds = max(TIMEFRAME_TO_SECONDS[tf] for tf, _ in timestamps)
            max_allowed_drift = timedelta(seconds=slowest_seconds * 2)  # 2x slowest timeframe

            if drift > max_allowed_drift:
                drift_minutes = drift.total_seconds() / 60
                max_allowed_minutes = max_allowed_drift.total_seconds() / 60
                return (
                    False,
                    f'Timeframe drift too large: {drift_minutes:.1f} minutes (max: {max_allowed_minutes:.1f})',
                )

            return (True, '')

    def analyze_cross_timeframe(self, symbol: str) -> CrossTimeframeAnalysis:
        """
        Perform professional cross-timeframe correlation analysis.

        P1-2 Fix: Now validates timeframe synchronization before analysis.
        P0 Fix (CRITICAL-1): Thread-safe to prevent race conditions with add_bar().

        This is the core logic used by professional traders:
        - Fast timeframes lead slow timeframes
        - Confluence (agreement) = high confidence
        - Divergence (disagreement) = risky trade

        Args:
            symbol: Trading symbol

        Returns:
            CrossTimeframeAnalysis with correlation data
        """
        # P0 Fix: Make a copy of states inside lock to prevent race conditions
        with self._lock:
            states = self._states.get(symbol, {}).copy()

        # Need at least 2 timeframes for correlation
        if len(states) < 2:
            return CrossTimeframeAnalysis(
                confluence=False,
                fast_leads_medium=False,
                medium_leads_slow=False,
                divergence_detected=False,
                confidence_adjustment=0.0,
                dominant_trend=Trend.NEUTRAL,
                timeframe_states=states,
            )

        # P1-2 Fix: Validate timeframe synchronization before analysis
        is_valid, reason = self._validate_timeframe_sync(symbol)
        if not is_valid:
            self.logger.warning(
                'timeframe_sync_invalid',
                extra={'symbol': symbol, 'reason': reason},
            )
            # Return neutral analysis with negative confidence adjustment
            return CrossTimeframeAnalysis(
                confluence=False,
                fast_leads_medium=False,
                medium_leads_slow=False,
                divergence_detected=True,  # Treat as divergence (risky)
                confidence_adjustment=-0.25,  # Penalty for misaligned data
                dominant_trend=Trend.NEUTRAL,
                timeframe_states=states,
            )

        # Sort timeframes by speed (fastest first)
        sorted_timeframes = sorted(states.keys(), key=lambda tf: TIMEFRAME_TO_SECONDS[tf])

        # Get trends for fast, medium, slow
        fast_trend = states[sorted_timeframes[0]].trend if len(sorted_timeframes) > 0 else Trend.NEUTRAL
        medium_trend = (
            states[sorted_timeframes[len(sorted_timeframes) // 2]].trend if len(sorted_timeframes) > 1 else fast_trend
        )
        slow_trend = states[sorted_timeframes[-1]].trend if len(sorted_timeframes) > 1 else fast_trend

        # Check confluence (all timeframes agree)
        all_trends = [state.trend for state in states.values()]
        confluence = len(set(all_trends)) == 1 and Trend.NEUTRAL not in all_trends

        # Check if fast leads medium
        fast_leads_medium = fast_trend == medium_trend and fast_trend != Trend.NEUTRAL

        # Check if medium leads slow
        medium_leads_slow = medium_trend == slow_trend and medium_trend != Trend.NEUTRAL

        # Detect divergence (timeframes disagree)
        divergence_detected = fast_trend != Trend.NEUTRAL and slow_trend != Trend.NEUTRAL and fast_trend != slow_trend

        # Calculate confidence adjustment
        confidence_adjustment = 0.0

        if confluence:
            # All timeframes agree - BIG confidence boost!
            confidence_adjustment = 0.25
        elif fast_leads_medium and medium_leads_slow:
            # Cascading alignment - good confidence boost
            confidence_adjustment = 0.15
        elif fast_leads_medium:
            # Fast and medium agree - moderate boost
            confidence_adjustment = 0.10
        elif divergence_detected:
            # Divergence - PENALTY!
            confidence_adjustment = -0.20

        # Determine dominant trend (weighted by timeframe)
        # Slower timeframes have more weight
        trend_scores = {Trend.UP: 0.0, Trend.DOWN: 0.0, Trend.NEUTRAL: 0.0}

        for i, tf in enumerate(sorted_timeframes):
            weight = (i + 1) / len(sorted_timeframes)  # Slower = higher weight
            trend = states[tf].trend
            trend_scores[trend] += weight

        dominant_trend = max(trend_scores.items(), key=lambda x: x[1])[0]

        return CrossTimeframeAnalysis(
            confluence=confluence,
            fast_leads_medium=fast_leads_medium,
            medium_leads_slow=medium_leads_slow,
            divergence_detected=divergence_detected,
            confidence_adjustment=confidence_adjustment,
            dominant_trend=dominant_trend,
            timeframe_states=states,
        )

    def get_timeframe_features(self, symbol: str) -> dict[str, Any]:
        """
        Extract features for FSD RL agent.

        Returns dictionary with multi-timeframe features:
        - Individual timeframe trends
        - Cross-timeframe correlation
        - Confluence signals
        """
        analysis = self.analyze_cross_timeframe(symbol)

        features: dict[str, Any] = {
            'confluence': analysis.confluence,
            'fast_leads_medium': analysis.fast_leads_medium,
            'medium_leads_slow': analysis.medium_leads_slow,
            'divergence_detected': analysis.divergence_detected,
            'confidence_adjustment': analysis.confidence_adjustment,
            'dominant_trend': analysis.dominant_trend.value,
        }

        # Add individual timeframe features
        for tf, state in analysis.timeframe_states.items():
            prefix = tf.replace('m', 'min').replace('h', 'hr').replace('s', 'sec')  # Normalize names
            features[f'{prefix}_trend'] = state.trend.value
            features[f'{prefix}_momentum'] = state.momentum
            features[f'{prefix}_volatility'] = state.volatility
            features[f'{prefix}_volume_ratio'] = state.volume_ratio

        return features

    def has_sufficient_data(self, symbol: str, min_bars: int = 20) -> bool:
        """
        Check if we have sufficient data across all timeframes.

        P0 Fix (CRITICAL-1): Thread-safe to prevent race conditions with add_bar().
        """
        with self._lock:  # P0 Fix: Thread safety
            if symbol not in self.bars:
                return False

            for tf in self.timeframes:
                bars = self.bars[symbol].get(tf, [])
                if len(bars) < min_bars:
                    return False

            return True


__all__ = [
    'TimeframeManager',
    'CrossTimeframeAnalysis',
    'TimeframeState',
    'Trend',
    'Timeframe',
    'TIMEFRAME_TO_SECONDS',
    'SECONDS_TO_TIMEFRAME',
]
