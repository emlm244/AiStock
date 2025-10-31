"""Market state extraction for FSD."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import numpy as np

from ..data import Bar

if TYPE_CHECKING:
    from ..edge_cases import EdgeCaseHandler
    from ..patterns import PatternDetector
    from ..timeframes import TimeframeManager


class MarketStateExtractor:
    """Extracts state features from market data.

    Responsibilities:
    - Extract price, volume, trend features
    - Multi-timeframe analysis
    - Pattern detection integration
    - Edge case detection
    """

    def __init__(
        self,
        current_positions: dict[str, Decimal],
        timeframe_manager: TimeframeManager | None = None,
        pattern_detector: PatternDetector | None = None,
        edge_case_handler: EdgeCaseHandler | None = None,
    ):
        self.current_positions = current_positions
        self.timeframe_manager = timeframe_manager
        self.pattern_detector = pattern_detector
        self.edge_case_handler = edge_case_handler

        self.logger = logging.getLogger(__name__)

    def extract_state(
        self,
        symbol: str,
        bars: list[Bar],
        last_prices: dict[str, Decimal],
        equity: float,
    ) -> dict[str, Any]:
        """Extract state features from market data."""
        if len(bars) < 20:
            return {}

        # Price features
        recent_closes = [float(bar.close) for bar in bars[-20:]]
        current_price = recent_closes[-1]
        prev_price = recent_closes[-2] if len(recent_closes) > 1 else current_price
        price_change_pct = (current_price - prev_price) / prev_price if prev_price > 0 else 0

        # Volume features
        recent_volumes = [bar.volume for bar in bars[-20:]]
        avg_volume = np.mean(recent_volumes) if recent_volumes else 1
        current_volume = bars[-1].volume
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        # Trend detection (multi-window)
        trend = 'neutral'
        trend_fast = 'neutral'
        trend_slow = 'neutral'

        if len(recent_closes) >= 10:
            short_ma = np.mean(recent_closes[-5:])
            long_ma = np.mean(recent_closes[-10:])
            trend = 'up' if short_ma > long_ma * 1.01 else 'down' if short_ma < long_ma * 0.99 else 'neutral'

        if len(recent_closes) >= 6:
            fast_short = np.mean(recent_closes[-3:])
            fast_long = np.mean(recent_closes[-6:])
            trend_fast = 'up' if fast_short > fast_long * 1.01 else 'down' if fast_short < fast_long * 0.99 else 'neutral'

        if len(recent_closes) >= 30:
            slow_short = np.mean(recent_closes[-15:])
            slow_long = np.mean(recent_closes[-30:])
            trend_slow = 'up' if slow_short > slow_long * 1.005 else 'down' if slow_short < slow_long * 0.995 else 'neutral'

        # Volatility (multi-window)
        volatility = 'normal'
        volatility_fast = 'normal'
        volatility_slow = 'normal'

        if len(recent_closes) >= 10:
            returns = np.diff(recent_closes) / recent_closes[:-1]
            vol_val = np.std(returns)
            volatility = 'low' if vol_val < 0.01 else 'high' if vol_val > 0.03 else 'normal'

        if len(recent_closes) >= 6:
            returns_fast = np.diff(recent_closes[-6:]) / np.array(recent_closes[-6:-1])
            vol_fast = np.std(returns_fast)
            volatility_fast = 'low' if vol_fast < 0.012 else 'high' if vol_fast > 0.04 else 'normal'

        if len(recent_closes) >= 30:
            returns_slow = np.diff(recent_closes[-30:]) / np.array(recent_closes[-30:-1])
            vol_slow = np.std(returns_slow)
            volatility_slow = 'low' if vol_slow < 0.008 else 'high' if vol_slow > 0.025 else 'normal'

        # Position state
        current_pos = self.current_positions.get(symbol, Decimal('0'))
        position_value = float(current_pos) * current_price
        position_pct = position_value / equity if equity > 0 else 0

        state: dict[str, Any] = {
            'symbol': symbol,
            'price_change_pct': price_change_pct,
            'volume_ratio': volume_ratio,
            'trend': trend,
            'volatility': volatility,
            'trend_fast': trend_fast,
            'trend_slow': trend_slow,
            'volatility_fast': volatility_fast,
            'volatility_slow': volatility_slow,
            'position_pct': position_pct,
            'current_price': current_price,
        }

        # Multi-timeframe features
        if self.timeframe_manager and self.timeframe_manager.has_sufficient_data(symbol):
            timeframe_features = self.timeframe_manager.get_timeframe_features(symbol)
            state.update(timeframe_features)

        # Pattern features
        if self.pattern_detector and len(bars) >= 3:
            patterns = self.pattern_detector.detect_patterns(bars)
            if patterns:
                strongest = self.pattern_detector.get_strongest_signal(patterns)
                state['pattern_signal'] = strongest.value
                state['pattern_count'] = len(patterns)
                state['has_bullish_pattern'] = any(p.signal.value == 'bullish' for p in patterns)
                state['has_bearish_pattern'] = any(p.signal.value == 'bearish' for p in patterns)
            else:
                state['pattern_signal'] = 'neutral'
                state['pattern_count'] = 0
                state['has_bullish_pattern'] = False
                state['has_bearish_pattern'] = False

        return state

    def check_edge_cases(
        self,
        symbol: str,
        bars: list[Bar],
        timeframe_data: dict[str, list[Bar]] | None = None,
    ) -> dict[str, Any] | None:
        """Check for edge cases that should block trading."""
        if not self.edge_case_handler:
            return None

        from datetime import datetime

        edge_result = self.edge_case_handler.check_edge_cases(
            symbol=symbol,
            bars=bars,
            timeframe_data=timeframe_data,
            current_time=datetime.now(),
        )

        if edge_result.action == 'block':
            return {
                'blocked': True,
                'reason': edge_result.reason,
                'severity': edge_result.severity,
            }

        return {
            'blocked': False,
            'confidence_adjustment': edge_result.confidence_adjustment,
            'position_multiplier': edge_result.position_size_multiplier,
            'warnings': [edge_result.reason] if edge_result.is_edge_case else [],
        }
