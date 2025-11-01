"""
Professional Candlestick Pattern Recognition Module.

Detects classic candlestick patterns used by professional traders:
- Bullish patterns (hammer, engulfing, morning star, etc.)
- Bearish patterns (shooting star, engulfing, evening star, etc.)
- Neutral patterns (doji, spinning top)
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .data import Bar


class PatternType(str, Enum):
    """Candlestick pattern types."""

    # Bullish patterns
    HAMMER = 'hammer'
    INVERTED_HAMMER = 'inverted_hammer'
    BULLISH_ENGULFING = 'bullish_engulfing'
    MORNING_STAR = 'morning_star'
    THREE_WHITE_SOLDIERS = 'three_white_soldiers'
    PIERCING_LINE = 'piercing_line'

    # Bearish patterns
    SHOOTING_STAR = 'shooting_star'
    HANGING_MAN = 'hanging_man'
    BEARISH_ENGULFING = 'bearish_engulfing'
    EVENING_STAR = 'evening_star'
    THREE_BLACK_CROWS = 'three_black_crows'
    DARK_CLOUD_COVER = 'dark_cloud_cover'

    # Neutral patterns
    DOJI = 'doji'
    SPINNING_TOP = 'spinning_top'


class PatternSignal(str, Enum):
    """Pattern trading signal."""

    BULLISH = 'bullish'
    BEARISH = 'bearish'
    NEUTRAL = 'neutral'


@dataclass
class DetectedPattern:
    """A detected candlestick pattern."""

    pattern_type: PatternType
    signal: PatternSignal
    confidence: float  # 0.0 to 1.0
    description: str


class PatternDetector:
    """
    Professional candlestick pattern detector.

    Uses strict pattern recognition rules used by professional technical analysts.

    P2-3 Fix: Includes caching to avoid re-computing patterns for same bar data.
    """

    def __init__(self, body_threshold: float = 0.3, wick_ratio: float = 2.0, cache_size: int = 1000):
        """
        Initialize pattern detector.

        Args:
            body_threshold: Maximum body size for small-body patterns (as fraction of range)
            wick_ratio: Minimum wick-to-body ratio for wick patterns
            cache_size: Maximum number of cached pattern results (P0-2 Fix: increased to 1000, thread-safe)
        """
        # P0-7 Fix: Convert to Decimal for compatibility with Decimal bar prices
        self.body_threshold = Decimal(str(body_threshold))
        self.wick_ratio = Decimal(str(wick_ratio))

        # P0-2 Fix: Thread-safe LRU cache for pattern detection results (bounded to 1000)
        # Key: (timestamp of last bar, hash of last 3 bar timestamps)
        # Value: list of DetectedPattern
        self._cache: OrderedDict[tuple[object, ...], list[DetectedPattern]] = OrderedDict()
        self._cache_max_size = cache_size
        self._lock = threading.Lock()  # P0-2 Fix: Protect cache from concurrent access

    def _is_downtrend(self, bars: list[Bar], lookback: int = 5) -> bool:
        """
        P1-3 Fix: Check if market is in downtrend (for reversal pattern context).

        Uses SMA crossover: price below SMA = downtrend.

        Args:
            bars: Historical bars
            lookback: Number of bars to analyze

        Returns:
            True if in downtrend
        """
        if len(bars) < lookback:
            return False

        recent_bars = bars[-lookback:]
        # P0-7 Fix: Use Decimal throughout (no float conversion)
        closes = [bar.close for bar in recent_bars]
        sma = sum(closes, start=closes[0].__class__('0')) / len(closes)

        # Current price below SMA = downtrend
        return closes[-1] < sma

    def _is_uptrend(self, bars: list[Bar], lookback: int = 5) -> bool:
        """
        P1-3 Fix: Check if market is in uptrend (for reversal pattern context).

        Uses SMA crossover: price above SMA = uptrend.

        Args:
            bars: Historical bars
            lookback: Number of bars to analyze

        Returns:
            True if in uptrend
        """
        if len(bars) < lookback:
            return False

        recent_bars = bars[-lookback:]
        # P0-7 Fix: Use Decimal throughout (no float conversion)
        closes = [bar.close for bar in recent_bars]
        sma = sum(closes, start=closes[0].__class__('0')) / len(closes)

        # Current price above SMA = uptrend
        return closes[-1] > sma

    def _has_volume_confirmation(self, bars: list[Bar], multiplier: float = 1.5) -> bool:
        """
        P1-3 Fix: Check if current bar has volume confirmation.

        Pattern is more reliable with above-average volume.

        Args:
            bars: Historical bars (need at least 10 for average)
            multiplier: Volume multiplier (1.5 = 50% above average)

        Returns:
            True if volume is elevated
        """
        if len(bars) < 10:
            return False  # Not enough data, assume no confirmation

        current_volume = bars[-1].volume
        avg_volume = sum(bar.volume for bar in bars[-10:-1]) / 9

        return current_volume >= avg_volume * multiplier

    def detect_patterns(self, bars: list[Bar]) -> list[DetectedPattern]:
        """
        Detect all candlestick patterns in the most recent bars.

        P1-3 Fix: Now includes trend context and volume confirmation.
        P2-3 Fix: Caches results to avoid re-computing for same bar data.

        Args:
            bars: List of bars (need at least 10 for reliable detection with context)

        Returns:
            List of detected patterns (filtered by trend context and volume)
        """
        if len(bars) < 1:
            return []

        # P2-3 Fix: Check cache first
        current = bars[-1]
        prev = bars[-2] if len(bars) >= 2 else None
        prev_prev = bars[-3] if len(bars) >= 3 else None

        # Cache key: timestamps of last 3 bars (or fewer if not available)
        cache_key_parts = [current.timestamp]
        if prev:
            cache_key_parts.append(prev.timestamp)
        if prev_prev:
            cache_key_parts.append(prev_prev.timestamp)
        cache_key = tuple(cache_key_parts)

        # P0-2 Fix: Check cache with lock (thread-safe read)
        with self._lock:
            if cache_key in self._cache:
                # Move to end (LRU)
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key].copy()  # Return copy to prevent external modification

        # Cache miss - compute patterns (outside lock to avoid holding lock during expensive computation)
        patterns: list[DetectedPattern] = []
        early_exit = False  # CRITICAL-11: Track if we can skip remaining pattern detection

        # P1-3 Fix: Pass full bars for trend/volume context
        # Single-bar patterns
        patterns.extend(self._detect_single_bar_patterns(current, prev, bars))

        # CRITICAL-11 Fix: Early exit if we have 2 strong patterns (confidence > 0.8)
        # No need to evaluate remaining patterns if signal is already clear
        strong_patterns = [p for p in patterns if p.confidence > 0.8]
        if len(strong_patterns) >= 2:
            early_exit = True  # Signal clear, skip remaining detection

        # Two-bar patterns
        if prev and not early_exit:
            patterns.extend(self._detect_two_bar_patterns(current, prev, bars))

            # CRITICAL-11: Check again after two-bar patterns
            strong_patterns = [p for p in patterns if p.confidence > 0.8]
            if len(strong_patterns) >= 2:
                early_exit = True

        # Three-bar patterns
        if prev and prev_prev and not early_exit:
            patterns.extend(self._detect_three_bar_patterns(current, prev, prev_prev, bars))

        # P0-2 Fix: Store in cache with lock (thread-safe write, bounded LRU)
        with self._lock:
            if len(self._cache) >= self._cache_max_size:
                # Remove oldest entry (FIFO eviction for LRU)
                self._cache.popitem(last=False)

            self._cache[cache_key] = patterns.copy()

        return patterns

    def _detect_single_bar_patterns(self, bar: Bar, prev: Bar | None, bars: list[Bar]) -> list[DetectedPattern]:
        """
        P1-3 Fix: Detect single-bar patterns with trend context and volume confirmation.

        Args:
            bar: Current bar
            prev: Previous bar (if available)
            bars: Full bar history for context
        """
        patterns: list[DetectedPattern] = []

        # Doji - small body, indecision
        if self._is_doji(bar):
            patterns.append(
                DetectedPattern(
                    pattern_type=PatternType.DOJI,
                    signal=PatternSignal.NEUTRAL,
                    confidence=0.6,
                    description='Doji - Market indecision, potential reversal',
                )
            )

        # P1-3 Fix: Hammer - bullish reversal ONLY in downtrend with volume
        if self._is_hammer(bar):
            # Require downtrend context
            in_downtrend = len(bars) >= 10 and self._is_downtrend(bars)
            has_volume = self._has_volume_confirmation(bars)

            if in_downtrend:
                # Full confirmation: downtrend + volume
                if has_volume:
                    patterns.append(
                        DetectedPattern(
                            pattern_type=PatternType.HAMMER,
                            signal=PatternSignal.BULLISH,
                            confidence=0.85,  # High confidence with full confirmation
                            description='Hammer - Strong bullish reversal (downtrend + volume)',
                        )
                    )
                else:
                    # Partial confirmation: downtrend only (no volume)
                    patterns.append(
                        DetectedPattern(
                            pattern_type=PatternType.HAMMER,
                            signal=PatternSignal.BULLISH,
                            confidence=0.60,  # Reduced confidence without volume
                            description='Hammer - Bullish reversal (downtrend, weak volume)',
                        )
                    )
            # Otherwise skip - hammer in uptrend is false signal

        # P1-3 Fix: Shooting Star - bearish reversal ONLY in uptrend with volume
        if self._is_shooting_star(bar):
            # Require uptrend context
            in_uptrend = len(bars) >= 10 and self._is_uptrend(bars)
            has_volume = self._has_volume_confirmation(bars)

            if in_uptrend:
                # Full confirmation: uptrend + volume
                if has_volume:
                    patterns.append(
                        DetectedPattern(
                            pattern_type=PatternType.SHOOTING_STAR,
                            signal=PatternSignal.BEARISH,
                            confidence=0.85,  # High confidence with full confirmation
                            description='Shooting Star - Strong bearish reversal (uptrend + volume)',
                        )
                    )
                else:
                    # Partial confirmation: uptrend only (no volume)
                    patterns.append(
                        DetectedPattern(
                            pattern_type=PatternType.SHOOTING_STAR,
                            signal=PatternSignal.BEARISH,
                            confidence=0.60,  # Reduced confidence without volume
                            description='Shooting Star - Bearish reversal (uptrend, weak volume)',
                        )
                    )
            # Otherwise skip - shooting star in downtrend is false signal

        # Spinning Top - indecision
        if self._is_spinning_top(bar):
            patterns.append(
                DetectedPattern(
                    pattern_type=PatternType.SPINNING_TOP,
                    signal=PatternSignal.NEUTRAL,
                    confidence=0.5,
                    description='Spinning Top - Indecision, wait for confirmation',
                )
            )

        return patterns

    def _detect_two_bar_patterns(self, current: Bar, prev: Bar, bars: list[Bar]) -> list[DetectedPattern]:
        """
        P1-3 Fix: Detect two-bar patterns with volume confirmation.

        Args:
            current: Current bar
            prev: Previous bar
            bars: Full bar history for volume confirmation
        """
        patterns: list[DetectedPattern] = []

        # P1-3 Fix: Bullish Engulfing with volume confirmation
        if self._is_bullish_engulfing(current, prev):
            has_volume = len(bars) >= 10 and self._has_volume_confirmation(bars)
            if has_volume:
                patterns.append(
                    DetectedPattern(
                        pattern_type=PatternType.BULLISH_ENGULFING,
                        signal=PatternSignal.BULLISH,
                        confidence=0.90,  # Increased with volume
                        description='Bullish Engulfing - Very strong bullish reversal (volume confirmed)',
                    )
                )
            else:
                patterns.append(
                    DetectedPattern(
                        pattern_type=PatternType.BULLISH_ENGULFING,
                        signal=PatternSignal.BULLISH,
                        confidence=0.75,  # Reduced without volume
                        description='Bullish Engulfing - Strong bullish reversal',
                    )
                )

        # P1-3 Fix: Bearish Engulfing with volume confirmation
        if self._is_bearish_engulfing(current, prev):
            has_volume = len(bars) >= 10 and self._has_volume_confirmation(bars)
            if has_volume:
                patterns.append(
                    DetectedPattern(
                        pattern_type=PatternType.BEARISH_ENGULFING,
                        signal=PatternSignal.BEARISH,
                        confidence=0.90,  # Increased with volume
                        description='Bearish Engulfing - Very strong bearish reversal (volume confirmed)',
                    )
                )
            else:
                patterns.append(
                    DetectedPattern(
                        pattern_type=PatternType.BEARISH_ENGULFING,
                        signal=PatternSignal.BEARISH,
                        confidence=0.75,  # Reduced without volume
                        description='Bearish Engulfing - Strong bearish reversal',
                    )
                )

        # Piercing Line - bullish reversal
        if self._is_piercing_line(current, prev):
            patterns.append(
                DetectedPattern(
                    pattern_type=PatternType.PIERCING_LINE,
                    signal=PatternSignal.BULLISH,
                    confidence=0.7,
                    description='Piercing Line - Bullish reversal pattern',
                )
            )

        # Dark Cloud Cover - bearish reversal
        if self._is_dark_cloud_cover(current, prev):
            patterns.append(
                DetectedPattern(
                    pattern_type=PatternType.DARK_CLOUD_COVER,
                    signal=PatternSignal.BEARISH,
                    confidence=0.7,
                    description='Dark Cloud Cover - Bearish reversal pattern',
                )
            )

        return patterns

    def _detect_three_bar_patterns(
        self, current: Bar, prev: Bar, prev_prev: Bar, bars: list[Bar]
    ) -> list[DetectedPattern]:
        """
        P1-3 Fix: Detect three-bar patterns (bars parameter for future enhancements).

        Args:
            current: Current bar
            prev: Previous bar
            prev_prev: Bar before previous
            bars: Full bar history (reserved for future volume/trend filtering)
        """
        patterns: list[DetectedPattern] = []

        # Morning Star - strong bullish reversal
        if self._is_morning_star(current, prev, prev_prev):
            patterns.append(
                DetectedPattern(
                    pattern_type=PatternType.MORNING_STAR,
                    signal=PatternSignal.BULLISH,
                    confidence=0.9,
                    description='Morning Star - Extremely strong bullish reversal',
                )
            )

        # Evening Star - strong bearish reversal
        if self._is_evening_star(current, prev, prev_prev):
            patterns.append(
                DetectedPattern(
                    pattern_type=PatternType.EVENING_STAR,
                    signal=PatternSignal.BEARISH,
                    confidence=0.9,
                    description='Evening Star - Extremely strong bearish reversal',
                )
            )

        # Three White Soldiers - strong bullish continuation
        if self._is_three_white_soldiers(current, prev, prev_prev):
            patterns.append(
                DetectedPattern(
                    pattern_type=PatternType.THREE_WHITE_SOLDIERS,
                    signal=PatternSignal.BULLISH,
                    confidence=0.8,
                    description='Three White Soldiers - Strong bullish continuation',
                )
            )

        # Three Black Crows - strong bearish continuation
        if self._is_three_black_crows(current, prev, prev_prev):
            patterns.append(
                DetectedPattern(
                    pattern_type=PatternType.THREE_BLACK_CROWS,
                    signal=PatternSignal.BEARISH,
                    confidence=0.8,
                    description='Three Black Crows - Strong bearish continuation',
                )
            )

        return patterns

    # Pattern detection helpers

    def _is_doji(self, bar: Bar) -> bool:
        """Detect Doji pattern."""
        # P0-7 Fix: Use Decimal throughout (no float conversion)
        body = abs(bar.close - bar.open)
        total_range = bar.high - bar.low

        if total_range == 0:
            return False

        # Doji: body is less than 10% of total range
        # P0-7 Fix: Convert float literal to Decimal
        return (body / total_range) < Decimal('0.1')

    def _is_hammer(self, bar: Bar) -> bool:
        """Detect Hammer pattern."""
        # P0-7 Fix: Use Decimal throughout (no float conversion)
        open_price = bar.open
        close_price = bar.close
        high_price = bar.high
        low_price = bar.low

        body = abs(close_price - open_price)
        total_range = high_price - low_price

        if total_range == 0:
            return False

        body_pct = body / total_range
        lower_wick = min(open_price, close_price) - low_price
        upper_wick = high_price - max(open_price, close_price)

        # Hammer: small body, long lower wick, no upper wick, bullish close
        # P0-7 Fix: Convert float literals to Decimal
        return (
            body_pct < self.body_threshold
            and lower_wick > body * self.wick_ratio
            and upper_wick < body * Decimal('0.1')
            and close_price >= open_price
        )

    def _is_shooting_star(self, bar: Bar) -> bool:
        """Detect Shooting Star pattern."""
        # P0-7 Fix: Use Decimal throughout (no float conversion)
        open_price = bar.open
        close_price = bar.close
        high_price = bar.high
        low_price = bar.low

        body = abs(close_price - open_price)
        total_range = high_price - low_price

        if total_range == 0:
            return False

        body_pct = body / total_range
        upper_wick = high_price - max(open_price, close_price)
        lower_wick = min(open_price, close_price) - low_price

        # Shooting Star: small body, long upper wick, no lower wick, bearish close
        # P0-7 Fix: Convert float literals to Decimal
        return (
            body_pct < self.body_threshold
            and upper_wick > body * self.wick_ratio
            and lower_wick < body * Decimal('0.1')
            and close_price <= open_price
        )

    def _is_spinning_top(self, bar: Bar) -> bool:
        """Detect Spinning Top pattern."""
        # P0-7 Fix: Use Decimal throughout (no float conversion)
        open_price = bar.open
        close_price = bar.close
        high_price = bar.high
        low_price = bar.low

        body = abs(close_price - open_price)
        total_range = high_price - low_price

        if total_range == 0:
            return False

        body_pct = body / total_range
        upper_wick = high_price - max(open_price, close_price)
        lower_wick = min(open_price, close_price) - low_price

        # Spinning Top: small body, wicks on both sides
        return body_pct < self.body_threshold and upper_wick > 0 and lower_wick > 0

    def _is_bullish_engulfing(self, current: Bar, prev: Bar) -> bool:
        """Detect Bullish Engulfing pattern."""
        prev_open = prev.open
        prev_close = prev.close
        curr_open = current.open
        curr_close = current.close

        # Previous bar is bearish
        prev_bearish = prev_close < prev_open

        # Current bar is bullish
        curr_bullish = curr_close > curr_open

        # Current bar engulfs previous bar
        engulfs = curr_open < prev_close and curr_close > prev_open

        return prev_bearish and curr_bullish and engulfs

    def _is_bearish_engulfing(self, current: Bar, prev: Bar) -> bool:
        """Detect Bearish Engulfing pattern."""
        prev_open = prev.open
        prev_close = prev.close
        curr_open = current.open
        curr_close = current.close

        # Previous bar is bullish
        prev_bullish = prev_close > prev_open

        # Current bar is bearish
        curr_bearish = curr_close < curr_open

        # Current bar engulfs previous bar
        engulfs = curr_open > prev_close and curr_close < prev_open

        return prev_bullish and curr_bearish and engulfs

    def _is_piercing_line(self, current: Bar, prev: Bar) -> bool:
        """Detect Piercing Line pattern."""
        prev_open = prev.open
        prev_close = prev.close
        curr_open = current.open
        curr_close = current.close

        # Previous bar is bearish
        prev_bearish = prev_close < prev_open

        # Current bar is bullish
        curr_bullish = curr_close > curr_open

        # Current opens below previous close and closes above midpoint
        prev_midpoint = (prev_open + prev_close) / 2
        pierces = curr_open < prev_close and curr_close > prev_midpoint

        return prev_bearish and curr_bullish and pierces

    def _is_dark_cloud_cover(self, current: Bar, prev: Bar) -> bool:
        """Detect Dark Cloud Cover pattern."""
        prev_open = prev.open
        prev_close = prev.close
        curr_open = current.open
        curr_close = current.close

        # Previous bar is bullish
        prev_bullish = prev_close > prev_open

        # Current bar is bearish
        curr_bearish = curr_close < curr_open

        # Current opens above previous close and closes below midpoint
        prev_midpoint = (prev_open + prev_close) / 2
        covers = curr_open > prev_close and curr_close < prev_midpoint

        return prev_bullish and curr_bearish and covers

    def _is_morning_star(self, current: Bar, prev: Bar, prev_prev: Bar) -> bool:
        """Detect Morning Star pattern."""
        pp_open = prev_prev.open
        pp_close = prev_prev.close
        p_open = prev.open
        p_close = prev.close
        c_open = current.open
        c_close = current.close

        # First bar is bearish
        first_bearish = pp_close < pp_open

        # Second bar is small (star)
        second_small = abs(p_close - p_open) < abs(pp_close - pp_open) * Decimal('0.3')

        # Third bar is bullish and closes above first bar's midpoint
        third_bullish = c_close > c_open
        pp_midpoint = (pp_open + pp_close) / 2
        closes_high = c_close > pp_midpoint

        return first_bearish and second_small and third_bullish and closes_high

    def _is_evening_star(self, current: Bar, prev: Bar, prev_prev: Bar) -> bool:
        """Detect Evening Star pattern."""
        pp_open = prev_prev.open
        pp_close = prev_prev.close
        p_open = prev.open
        p_close = prev.close
        c_open = current.open
        c_close = current.close

        # First bar is bullish
        first_bullish = pp_close > pp_open

        # Second bar is small (star)
        second_small = abs(p_close - p_open) < abs(pp_close - pp_open) * Decimal('0.3')

        # Third bar is bearish and closes below first bar's midpoint
        third_bearish = c_close < c_open
        pp_midpoint = (pp_open + pp_close) / 2
        closes_low = c_close < pp_midpoint

        return first_bullish and second_small and third_bearish and closes_low

    def _is_three_white_soldiers(self, current: Bar, prev: Bar, prev_prev: Bar) -> bool:
        """Detect Three White Soldiers pattern."""
        pp_open = prev_prev.open
        pp_close = prev_prev.close
        p_open = prev.open
        p_close = prev.close
        c_open = current.open
        c_close = current.close

        # All three bars are bullish
        all_bullish = pp_close > pp_open and p_close > p_open and c_close > c_open

        # Each bar closes higher than the previous
        ascending = pp_close < p_close < c_close

        # Each bar opens within the body of the previous bar
        opens_within_body = p_open > pp_open and c_open > p_open

        return all_bullish and ascending and opens_within_body

    def _is_three_black_crows(self, current: Bar, prev: Bar, prev_prev: Bar) -> bool:
        """Detect Three Black Crows pattern."""
        pp_open = prev_prev.open
        pp_close = prev_prev.close
        p_open = prev.open
        p_close = prev.close
        c_open = current.open
        c_close = current.close

        # All three bars are bearish
        all_bearish = pp_close < pp_open and p_close < p_open and c_close < c_open

        # Each bar closes lower than the previous
        descending = pp_close > p_close > c_close

        # Each bar opens within the body of the previous bar
        opens_within_body = p_open < pp_open and c_open < p_open

        return all_bearish and descending and opens_within_body

    def get_strongest_signal(self, patterns: list[DetectedPattern]) -> PatternSignal:
        """
        Get the strongest trading signal from detected patterns.

        Args:
            patterns: List of detected patterns

        Returns:
            Strongest signal (bullish, bearish, or neutral)
        """
        if not patterns:
            return PatternSignal.NEUTRAL

        # Weight patterns by confidence
        bullish_score = sum(p.confidence for p in patterns if p.signal == PatternSignal.BULLISH)
        bearish_score = sum(p.confidence for p in patterns if p.signal == PatternSignal.BEARISH)

        # P0-7 Fix: Confidence is float, keep comparisons as float
        if bullish_score > bearish_score and bullish_score > 0.5:
            return PatternSignal.BULLISH
        elif bearish_score > bullish_score and bearish_score > 0.5:
            return PatternSignal.BEARISH
        else:
            return PatternSignal.NEUTRAL


__all__ = [
    'PatternDetector',
    'DetectedPattern',
    'PatternType',
    'PatternSignal',
]
