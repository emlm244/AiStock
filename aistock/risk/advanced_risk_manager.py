"""Advanced Risk Manager - composite coordinator for all advanced features."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..data import Bar
    from .advanced_config import AdvancedRiskConfig
    from .correlation import CorrelationCheckResult
    from .kelly import KellyResult
    from .regime import RegimeResult
    from .volatility_scaling import VolatilityScaleResult


class SymbolPerformanceProvider(Protocol):
    """Protocol for accessing symbol performance data."""

    @property
    def symbol_performance(self) -> dict[str, dict[str, float | int]]: ...


@dataclass
class AdvancedRiskResult:
    """Composite result from all advanced risk checks."""

    allowed: bool
    position_size_multiplier: float
    kelly: KellyResult | None
    correlation: CorrelationCheckResult | None
    regime: RegimeResult | None
    volatility: VolatilityScaleResult | None
    reason: str


class AdvancedRiskManager:
    """Coordinate all advanced risk management features.

    Integrates Kelly sizing, correlation limits, regime detection,
    and volatility scaling into a single interface.

    Features:
    - Kelly Criterion: Optimal position sizing from trade history
    - Correlation Limits: Block trades that exceed correlation threshold
    - Regime Detection: 5-regime classifier with position multipliers
    - Volatility Scaling: VIX/realized vol position scaling

    Thread-safe for IBKR callback access.
    """

    def __init__(self, config: AdvancedRiskConfig) -> None:
        # Avoid circular imports by importing here
        from .correlation import CorrelationMonitor
        from .kelly import KellyCriterionSizer
        from .regime import RegimeDetector
        from .volatility_scaling import VolatilityScaler

        self.config = config
        self._lock = threading.RLock()

        # Initialize sub-components (only if enabled)
        self._kelly: KellyCriterionSizer | None = KellyCriterionSizer(config.kelly) if config.kelly.enable else None
        self._correlation: CorrelationMonitor | None = (
            CorrelationMonitor(config.correlation) if config.correlation.enable else None
        )
        self._regime: RegimeDetector | None = RegimeDetector(config.regime) if config.regime.enable else None
        self._volatility: VolatilityScaler | None = (
            VolatilityScaler(config.volatility_scaling) if config.volatility_scaling.enable else None
        )

    def evaluate(
        self,
        symbol: str,
        bars: list[Bar],
        last_prices: dict[str, Decimal],
        current_positions: dict[str, Decimal],
        price_history: dict[str, list[float]],
        performance_provider: SymbolPerformanceProvider | None = None,
        state: dict[str, Any] | None = None,
    ) -> AdvancedRiskResult:
        """Run all enabled advanced risk checks and compute composite multiplier.

        Args:
            symbol: Symbol being evaluated for trade
            bars: List of Bar objects for the symbol
            last_prices: Dict of symbol -> current price
            current_positions: Dict of symbol -> current position size
            price_history: Dict of symbol -> list of closing prices (for correlation)
            performance_provider: Object providing symbol_performance (for Kelly)
            state: State dict from FSDEngine (for VIX level)

        Returns:
            AdvancedRiskResult with allowed status and composite multiplier
        """
        # Import result types for return

        with self._lock:
            multiplier = 1.0
            allowed = True
            reasons: list[str] = []

            kelly_result: KellyResult | None = None
            corr_result: CorrelationCheckResult | None = None
            regime_result: RegimeResult | None = None
            vol_result: VolatilityScaleResult | None = None

            # === Kelly Criterion ===
            if self._kelly and performance_provider:
                kelly_result = self._kelly.calculate(symbol, performance_provider)
                # Convert Kelly fraction to multiplier relative to fallback
                default_fraction = self.config.kelly.fallback_fraction
                if default_fraction > 0:
                    kelly_multiplier = kelly_result.applied_fraction / default_fraction
                    multiplier *= kelly_multiplier
                    reasons.append(f'Kelly={kelly_result.applied_fraction:.2%} (x{kelly_multiplier:.2f})')

            # === Correlation Check ===
            if self._correlation:
                corr_result = self._correlation.check_correlation(symbol, current_positions, price_history)
                if not corr_result.allowed:
                    allowed = False
                    reasons.append(f'BLOCKED: {corr_result.reason}')

            # === Regime Detection ===
            if self._regime:
                regime_result = self._regime.detect_regime(bars)
                multiplier *= regime_result.position_multiplier
                reasons.append(f'Regime={regime_result.regime.value} (x{regime_result.position_multiplier:.2f})')

            # === Volatility Scaling ===
            if self._volatility:
                vol_result = self._volatility.compute_scale(bars, last_prices, state)
                multiplier *= vol_result.scale_factor
                reasons.append(f'VolScale={vol_result.scale_factor:.2f}')

            # Cap final multiplier to reasonable bounds
            multiplier = max(0.01, min(3.0, multiplier))

            return AdvancedRiskResult(
                allowed=allowed,
                position_size_multiplier=multiplier,
                kelly=kelly_result,
                correlation=corr_result,
                regime=regime_result,
                volatility=vol_result,
                reason='; '.join(reasons) if reasons else 'No advanced risk checks enabled',
            )

    def is_any_enabled(self) -> bool:
        """Check if any advanced risk feature is enabled.

        Returns:
            True if at least one feature is enabled
        """
        return (
            self._kelly is not None
            or self._correlation is not None
            or self._regime is not None
            or self._volatility is not None
        )
