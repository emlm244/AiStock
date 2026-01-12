"""Volatility-based position scaling."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ..data import Bar
    from .advanced_config import VolatilityScalingConfig


@dataclass
class VolatilityScaleResult:
    """Result of volatility scaling calculation."""

    scale_factor: float
    vix_value: float | None
    realized_volatility: float | None
    source: str  # 'vix', 'realized', or 'none'
    reason: str


class VolatilityScaler:
    """Scale position sizes based on market volatility.

    Uses VIX when available (from last_prices or state['vix_level']),
    falls back to computed realized volatility.

    Scaling logic:
    - High volatility (VIX > 30 or high realized vol) -> scale down to 0.25x
    - Low volatility (VIX < 15 or low realized vol) -> scale up to 2.0x
    - Normal volatility -> interpolate between scale factors

    Thread-safe for IBKR callback access.
    """

    def __init__(self, config: VolatilityScalingConfig) -> None:
        self.config = config
        self._lock = threading.Lock()

    def compute_scale(
        self,
        bars: list[Bar],
        last_prices: dict[str, Decimal],
        state: dict[str, Any] | None = None,
    ) -> VolatilityScaleResult:
        """Compute position scale factor based on volatility.

        Args:
            bars: List of Bar objects for realized vol calculation
            last_prices: Dict of symbol -> current price (for VIX lookup)
            state: Optional state dict from FSDEngine (contains vix_level)

        Returns:
            VolatilityScaleResult with scale factor and source
        """
        with self._lock:
            # Try VIX first
            vix_value = self._get_vix(last_prices, state)

            if vix_value is not None and vix_value > 0:
                scale = self._scale_from_vix(vix_value)
                return VolatilityScaleResult(
                    scale_factor=scale,
                    vix_value=vix_value,
                    realized_volatility=None,
                    source='vix',
                    reason=f'VIX={vix_value:.1f} -> scale={scale:.2f}',
                )

            # Fall back to realized volatility
            if not self.config.use_realized_vol_fallback:
                return VolatilityScaleResult(
                    scale_factor=1.0,
                    vix_value=None,
                    realized_volatility=None,
                    source='none',
                    reason='VIX unavailable, fallback disabled',
                )

            realized_vol = self._compute_realized_vol(bars)
            if realized_vol is None or realized_vol <= 0:
                return VolatilityScaleResult(
                    scale_factor=1.0,
                    vix_value=None,
                    realized_volatility=None,
                    source='none',
                    reason=f'Insufficient data for volatility (need {self.config.realized_vol_lookback + 1} bars)',
                )

            scale = self._scale_from_realized(realized_vol)
            return VolatilityScaleResult(
                scale_factor=scale,
                vix_value=None,
                realized_volatility=realized_vol,
                source='realized',
                reason=f'Realized vol={realized_vol:.2%} -> scale={scale:.2f}',
            )

    def _get_vix(
        self,
        last_prices: dict[str, Decimal],
        state: dict[str, Any] | None,
    ) -> float | None:
        """Get VIX value from state or last_prices.

        Args:
            last_prices: Dict of symbol -> current price
            state: Optional state dict from FSDEngine

        Returns:
            VIX value or None if not available
        """
        # Check state first (from extract_state)
        if state:
            vix = state.get('vix_level')
            if isinstance(vix, (int, float)) and vix > 0:
                return float(vix)

        # Check last_prices for VIX symbols
        for symbol in self.config.vix_symbols:
            price = last_prices.get(symbol)
            if price is not None:
                try:
                    val = float(price)
                    if val > 0:
                        return val
                except (TypeError, ValueError):
                    continue

        return None

    def _scale_from_vix(self, vix: float) -> float:
        """Compute scale factor from VIX value.

        Linear interpolation between low/high thresholds:
        - VIX <= low threshold -> max_scale_up
        - VIX >= high threshold -> max_scale_down
        - Between -> linear interpolation

        Args:
            vix: VIX value

        Returns:
            Scale factor
        """
        if vix >= self.config.vix_high_threshold:
            return self.config.max_scale_down
        elif vix <= self.config.vix_low_threshold:
            return self.config.max_scale_up
        else:
            # Linear interpolation
            range_vix = self.config.vix_high_threshold - self.config.vix_low_threshold
            position = (vix - self.config.vix_low_threshold) / range_vix
            scale_range = self.config.max_scale_up - self.config.max_scale_down
            return self.config.max_scale_up - (position * scale_range)

    def _compute_realized_vol(self, bars: list[Bar]) -> float | None:
        """Compute annualized realized volatility from bars.

        Args:
            bars: List of Bar objects

        Returns:
            Annualized volatility as decimal or None if insufficient data
        """
        lookback = self.config.realized_vol_lookback
        if len(bars) < lookback + 1:
            return None

        closes = [float(bar.close) for bar in bars[-(lookback + 1) :]]
        arr = np.array(closes)

        with np.errstate(divide='ignore', invalid='ignore'):
            returns = np.diff(arr) / arr[:-1]

        # Filter invalid values
        returns = returns[np.isfinite(returns)]

        if len(returns) < 2:
            return None

        daily_vol = float(np.std(returns))
        # Annualize: daily vol * sqrt(252 trading days)
        annualized = daily_vol * np.sqrt(252)

        return annualized

    def _scale_from_realized(self, realized_vol: float) -> float:
        """Compute scale factor from realized volatility.

        Uses target volatility to determine scaling:
        scale = target_vol / realized_vol

        Args:
            realized_vol: Annualized realized volatility

        Returns:
            Scale factor (capped to [max_scale_down, max_scale_up])
        """
        if realized_vol <= 0:
            return 1.0

        # Target vol / realized vol
        scale = self.config.target_volatility / realized_vol

        # Apply caps
        return max(
            self.config.max_scale_down,
            min(self.config.max_scale_up, scale),
        )
