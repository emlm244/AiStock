"""Correlation-based trade blocking."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .advanced_config import CorrelationLimitsConfig


@dataclass
class CorrelationCheckResult:
    """Result of correlation check."""

    allowed: bool
    max_correlation: float
    correlated_symbols: list[tuple[str, str, float]]
    reason: str


class CorrelationMonitor:
    """Monitor portfolio correlation and block highly correlated trades.

    Uses price history to compute rolling correlation between symbols.
    Blocks new trades when adding a position would create excessive
    portfolio correlation.

    Thread-safe for IBKR callback access.
    """

    def __init__(self, config: CorrelationLimitsConfig) -> None:
        try:
            config.validate()
        except Exception as exc:
            raise ValueError(f'Invalid CorrelationLimitsConfig: {exc}') from exc
        self.config = config
        self._lock = threading.Lock()

    def check_correlation(
        self,
        symbol: str,
        current_positions: dict[str, Decimal],
        price_history: dict[str, list[float]],
    ) -> CorrelationCheckResult:
        """Check if adding symbol would exceed correlation limits.

        Args:
            symbol: Symbol to potentially add
            current_positions: Dict of symbol -> current position size
            price_history: Dict of symbol -> list of closing prices

        Returns:
            CorrelationCheckResult with allowed status and correlation details
        """
        with self._lock:
            # Allow if no existing positions
            if not current_positions:
                return CorrelationCheckResult(
                    allowed=True,
                    max_correlation=0.0,
                    correlated_symbols=[],
                    reason='No existing positions',
                )

            # Get closes for new symbol
            new_closes = price_history.get(symbol, [])
            if len(new_closes) < self.config.min_data_points:
                return CorrelationCheckResult(
                    allowed=True,
                    max_correlation=0.0,
                    correlated_symbols=[],
                    reason=f'Insufficient data for {symbol} ({len(new_closes)} < {self.config.min_data_points})',
                )

            correlated_pairs: list[tuple[str, str, float]] = []
            max_corr = 0.0

            for existing_symbol, position in current_positions.items():
                # Skip if same symbol or no position
                if existing_symbol == symbol or position == Decimal('0'):
                    continue

                existing_closes = price_history.get(existing_symbol, [])
                if len(existing_closes) < self.config.min_data_points:
                    continue

                # Align lengths and use most recent data
                min_len = min(
                    len(new_closes),
                    len(existing_closes),
                    self.config.lookback_bars,
                )

                if min_len < self.config.min_data_points:
                    continue

                corr = self._compute_correlation(
                    new_closes[-min_len:],
                    existing_closes[-min_len:],
                )

                if corr > max_corr:
                    max_corr = corr

                if corr > self.config.max_correlation:
                    correlated_pairs.append((symbol, existing_symbol, corr))

            # Block if any pair exceeds threshold
            if correlated_pairs and self.config.block_on_high_correlation:
                pairs_str = ', '.join(f'{s1}/{s2}={c:.2f}' for s1, s2, c in correlated_pairs)
                return CorrelationCheckResult(
                    allowed=False,
                    max_correlation=max_corr,
                    correlated_symbols=correlated_pairs,
                    reason=f'High correlation detected: {pairs_str}',
                )

            return CorrelationCheckResult(
                allowed=True,
                max_correlation=max_corr,
                correlated_symbols=correlated_pairs,
                reason='Correlation within limits' if max_corr > 0 else 'No correlation data',
            )

    def _compute_correlation(
        self,
        series1: list[float],
        series2: list[float],
    ) -> float:
        """Compute Pearson correlation between two price series using returns.

        Args:
            series1: First price series (closing prices)
            series2: Second price series (closing prices)

        Returns:
            Absolute value of correlation coefficient (0 to 1)
        """
        if len(series1) != len(series2) or len(series1) < 3:
            return 0.0

        # Convert prices to returns for correlation
        arr1 = np.array(series1)
        arr2 = np.array(series2)

        # Avoid division by zero
        with np.errstate(divide='ignore', invalid='ignore'):
            returns1 = np.diff(arr1) / arr1[:-1]
            returns2 = np.diff(arr2) / arr2[:-1]

        # Filter out any inf/nan values
        valid_mask = np.isfinite(returns1) & np.isfinite(returns2)
        returns1 = returns1[valid_mask]
        returns2 = returns2[valid_mask]

        if len(returns1) < 2:
            return 0.0

        # Compute Pearson correlation
        corr_matrix = np.corrcoef(returns1, returns2)
        corr = corr_matrix[0, 1]

        # Handle NaN (can occur if one series is constant)
        if np.isnan(corr):
            return 0.0

        # Return absolute correlation (we care about magnitude, not direction)
        return float(abs(corr))

    def compute_portfolio_correlation_matrix(
        self,
        symbols: list[str],
        price_history: dict[str, list[float]],
    ) -> dict[str, dict[str, float]]:
        """Compute full correlation matrix for a set of symbols.

        Args:
            symbols: List of symbols to compute correlations for
            price_history: Dict of symbol -> list of closing prices

        Returns:
            Nested dict with correlation values: {symbol1: {symbol2: corr}}
        """
        with self._lock:
            result: dict[str, dict[str, float]] = {}

            for i, sym1 in enumerate(symbols):
                result[sym1] = {}
                for j, sym2 in enumerate(symbols):
                    if i == j:
                        result[sym1][sym2] = 1.0
                    elif j < i:
                        # Use already computed value
                        result[sym1][sym2] = result[sym2][sym1]
                    else:
                        closes1 = price_history.get(sym1, [])
                        closes2 = price_history.get(sym2, [])

                        if len(closes1) < self.config.min_data_points or len(closes2) < self.config.min_data_points:
                            result[sym1][sym2] = 0.0
                        else:
                            min_len = min(len(closes1), len(closes2), self.config.lookback_bars)
                            result[sym1][sym2] = self._compute_correlation(
                                closes1[-min_len:],
                                closes2[-min_len:],
                            )

            return result
