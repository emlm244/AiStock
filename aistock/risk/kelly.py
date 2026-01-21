"""Kelly Criterion position sizing calculator."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .advanced_config import KellyCriterionConfig


class SymbolPerformanceProvider(Protocol):
    """Protocol for accessing symbol performance data.

    Expected format for symbol_performance:
    {symbol: {'trades': int, 'wins': int, 'total_pnl': float, 'confidence_adj': float}}
    """

    @property
    def symbol_performance(self) -> dict[str, dict[str, float | int]]: ...


@dataclass
class KellyResult:
    """Result of Kelly Criterion calculation."""

    kelly_fraction: float
    applied_fraction: float  # After half-Kelly and caps
    win_rate: float
    avg_win: float
    avg_loss: float
    trade_count: int
    is_fallback: bool
    reason: str


class KellyCriterionSizer:
    """Calculate optimal position size using Kelly Criterion.

    Uses trade history from FSDEngine.symbol_performance to compute
    win rate and average win/loss ratio per symbol.

    The Kelly formula: K = W - (1-W)/R
    where W = win rate, R = avg_win / avg_loss

    This implementation uses half-Kelly by default for safety.

    Thread-safe for IBKR callback access.
    """

    def __init__(self, config: KellyCriterionConfig) -> None:
        self.config = config
        self._lock = threading.Lock()

    def calculate(
        self,
        symbol: str,
        performance_provider: SymbolPerformanceProvider,
    ) -> KellyResult:
        """Calculate Kelly fraction for a symbol.

        Args:
            symbol: Trading symbol to calculate Kelly for
            performance_provider: Object providing symbol_performance dict

        Returns:
            KellyResult with calculated or fallback fraction
        """
        with self._lock:
            perf = performance_provider.symbol_performance.get(symbol)

            if not perf:
                return KellyResult(
                    kelly_fraction=0.0,
                    applied_fraction=self.config.fallback_fraction,
                    win_rate=0.0,
                    avg_win=0.0,
                    avg_loss=0.0,
                    trade_count=0,
                    is_fallback=True,
                    reason='No performance data for symbol',
                )

            trades = int(perf.get('trades', 0))
            if trades < self.config.min_trades_required:
                return KellyResult(
                    kelly_fraction=0.0,
                    applied_fraction=self.config.fallback_fraction,
                    win_rate=0.0,
                    avg_win=0.0,
                    avg_loss=0.0,
                    trade_count=trades,
                    is_fallback=True,
                    reason=f'Insufficient trades ({trades} < {self.config.min_trades_required})',
                )

            wins = int(perf.get('wins', 0))
            total_pnl = float(perf.get('total_pnl', 0.0))

            win_rate = wins / trades if trades > 0 else 0.0

            # Estimate average win and loss amounts
            # Since we only track total_pnl, we estimate based on win/loss counts
            losses = trades - wins

            if wins == 0:
                # No wins, can't compute Kelly
                return KellyResult(
                    kelly_fraction=0.0,
                    applied_fraction=self.config.min_kelly_fraction,
                    win_rate=0.0,
                    avg_win=0.0,
                    avg_loss=abs(total_pnl / trades) if trades > 0 else 0.0,
                    trade_count=trades,
                    is_fallback=True,
                    reason='No winning trades',
                )

            if losses == 0:
                # All wins, use max Kelly
                avg_win = total_pnl / wins if wins > 0 else 0.0
                return KellyResult(
                    kelly_fraction=1.0,
                    applied_fraction=self.config.max_kelly_fraction,
                    win_rate=1.0,
                    avg_win=avg_win,
                    avg_loss=0.0,
                    trade_count=trades,
                    is_fallback=False,
                    reason='All winning trades, using max fraction',
                )

            # Estimate avg_win and avg_loss from total_pnl
            # Assumption: avg_win * wins + avg_loss * losses = total_pnl
            # We need another equation, so we estimate ratio from historical patterns
            # Using empirical approximation: avg_win / avg_loss ~ 1.5 for trading systems
            # Then solve for avg_win and avg_loss

            # Alternative approach: Use total_pnl sign to estimate
            if total_pnl >= 0:
                # Profitable overall: estimate avg_win > avg_loss
                # total_pnl = avg_win * wins - avg_loss * losses
                # Assume avg_win = 1.5 * avg_loss (typical for trend following)
                # total_pnl = 1.5 * avg_loss * wins - avg_loss * losses
                # total_pnl = avg_loss * (1.5 * wins - losses)
                denominator = 1.5 * wins - losses
                if denominator > 0:
                    avg_loss = total_pnl / denominator
                    avg_win = 1.5 * avg_loss
                else:
                    # Edge case: use simple average
                    avg_pnl = total_pnl / trades
                    avg_win = abs(avg_pnl) * 1.5
                    avg_loss = abs(avg_pnl)
            else:
                # Unprofitable overall: negative Kelly expected
                abs_pnl = abs(total_pnl)
                # Assume more losses than wins in magnitude
                avg_loss = abs_pnl / losses if losses > 0 else abs_pnl
                avg_win = abs_pnl / (2 * wins) if wins > 0 else 0.0

            # Ensure positive values for ratio
            avg_win = max(0.001, avg_win)
            avg_loss = max(0.001, avg_loss)

            # Kelly formula: K = W - (1-W)/R where R = avg_win/avg_loss
            r_ratio = avg_win / avg_loss
            kelly = win_rate - (1 - win_rate) / r_ratio

            # Apply fraction (half-Kelly, etc.)
            kelly_scaled = kelly * self.config.fraction

            # Apply caps and floor
            if kelly <= 0:
                applied = self.config.min_kelly_fraction
                reason = f'Negative Kelly ({kelly:.4f}), using min fraction'
            else:
                applied = max(
                    self.config.min_kelly_fraction,
                    min(self.config.max_kelly_fraction, kelly_scaled),
                )
                reason = f'Kelly={kelly:.4f}, scaled={kelly_scaled:.4f}, applied={applied:.4f}'

            return KellyResult(
                kelly_fraction=kelly,
                applied_fraction=applied,
                win_rate=win_rate,
                avg_win=avg_win,
                avg_loss=avg_loss,
                trade_count=trades,
                is_fallback=False,
                reason=reason,
            )
