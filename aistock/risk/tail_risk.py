"""Tail risk metrics: Value at Risk (VaR) and Conditional VaR (CVaR).

Provides statistical risk metrics for portfolio risk assessment.

References:
- Jorion (2006) "Value at Risk: The New Benchmark for Managing Financial Risk"
- Rockafellar & Uryasev (2000) "Optimization of Conditional Value-at-Risk"
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _load_scipy_stats() -> Any:
    try:
        import importlib

        return importlib.import_module('scipy.stats')
    except ModuleNotFoundError as exc:
        raise RuntimeError('scipy is required for parametric/cornish_fisher VaR calculations') from exc


@dataclass
class TailRiskConfig:
    """Configuration for tail risk calculations.

    Attributes:
        confidence_level: VaR confidence level (default 0.95 = 95%)
        lookback_periods: Number of historical periods for calculation
        method: Calculation method ('historical', 'parametric', 'cornish_fisher')
        annualization_factor: Factor to annualize returns (252 for daily)
    """

    confidence_level: float = 0.95
    lookback_periods: int = 252  # 1 year of daily data
    method: str = 'historical'  # 'historical', 'parametric', 'cornish_fisher'
    annualization_factor: int = 252

    def validate(self) -> None:
        """Validate configuration parameters."""
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError(f'confidence_level must be in (0, 1), got {self.confidence_level}')
        if self.lookback_periods <= 0:
            raise ValueError(f'lookback_periods must be positive, got {self.lookback_periods}')
        valid_methods = ('historical', 'parametric', 'cornish_fisher')
        if self.method not in valid_methods:
            raise ValueError(f'method must be one of {valid_methods}, got {self.method}')
        if self.annualization_factor <= 0:
            raise ValueError(f'annualization_factor must be positive, got {self.annualization_factor}')


@dataclass
class TailRiskResult:
    """Result of tail risk calculation.

    Attributes:
        var: Value at Risk (positive number representing potential loss)
        cvar: Conditional VaR / Expected Shortfall (average loss beyond VaR)
        confidence_level: Confidence level used
        method: Calculation method used
        sample_size: Number of observations used
        var_pct: VaR as percentage
        cvar_pct: CVaR as percentage
    """

    var: Decimal
    cvar: Decimal
    confidence_level: float
    method: str
    sample_size: int
    var_pct: float = 0.0
    cvar_pct: float = 0.0


class TailRiskCalculator:
    """Calculator for Value at Risk (VaR) and Conditional VaR (CVaR).

    VaR estimates the maximum expected loss at a given confidence level.
    CVaR (Expected Shortfall) measures the average loss beyond VaR.

    Example:
        >>> calculator = TailRiskCalculator(TailRiskConfig(confidence_level=0.95))
        >>> returns = [-0.02, 0.01, -0.03, 0.02, -0.01, ...]  # Daily returns
        >>> result = calculator.calculate(returns)
        >>> print(f"95% VaR: {result.var_pct:.2%}")
        >>> print(f"95% CVaR: {result.cvar_pct:.2%}")
    """

    def __init__(self, config: TailRiskConfig | None = None):
        """Initialize tail risk calculator.

        Args:
            config: Configuration for calculations
        """
        self.config = config or TailRiskConfig()
        self.config.validate()

    def calculate(
        self,
        returns: Sequence[float] | np.ndarray,
        portfolio_value: Decimal | None = None,
    ) -> TailRiskResult:
        """Calculate VaR and CVaR from return series.

        Args:
            returns: Sequence of periodic returns (e.g., daily returns)
            portfolio_value: Optional portfolio value for absolute VaR

        Returns:
            TailRiskResult with VaR and CVaR metrics
        """
        returns_array = np.array(returns, dtype=np.float64)

        # Filter out NaN and Inf values
        returns_array = returns_array[np.isfinite(returns_array)]

        if len(returns_array) < 10:
            logger.warning(f'Insufficient data for VaR calculation: {len(returns_array)} returns')
            return TailRiskResult(
                var=Decimal('0'),
                cvar=Decimal('0'),
                confidence_level=self.config.confidence_level,
                method=self.config.method,
                sample_size=len(returns_array),
            )

        # Calculate based on method
        if self.config.method == 'historical':
            var_pct, cvar_pct = self._historical_var_cvar(returns_array)
        elif self.config.method == 'parametric':
            var_pct, cvar_pct = self._parametric_var_cvar(returns_array)
        elif self.config.method == 'cornish_fisher':
            var_pct, cvar_pct = self._cornish_fisher_var_cvar(returns_array)
        else:
            var_pct, cvar_pct = self._historical_var_cvar(returns_array)

        # Convert to absolute values if portfolio value provided
        if portfolio_value is not None and portfolio_value > 0:
            var_abs = portfolio_value * Decimal(str(var_pct))
            cvar_abs = portfolio_value * Decimal(str(cvar_pct))
        else:
            var_abs = Decimal(str(var_pct))
            cvar_abs = Decimal(str(cvar_pct))

        return TailRiskResult(
            var=var_abs,
            cvar=cvar_abs,
            confidence_level=self.config.confidence_level,
            method=self.config.method,
            sample_size=len(returns_array),
            var_pct=var_pct,
            cvar_pct=cvar_pct,
        )

    def _historical_var_cvar(self, returns: np.ndarray) -> tuple[float, float]:
        """Calculate historical VaR and CVaR.

        Uses empirical distribution of returns without assuming normality.

        Args:
            returns: Array of returns

        Returns:
            Tuple of (VaR, CVaR) as percentages (positive = loss)
        """
        # VaR is the (1 - confidence) percentile of the loss distribution
        # For losses, we negate returns (negative return = positive loss)
        alpha = 1 - self.config.confidence_level
        var_percentile = np.percentile(returns, alpha * 100)

        # VaR is reported as positive loss
        var = -var_percentile if var_percentile < 0 else 0.0

        # CVaR is the average of returns worse than VaR
        tail_returns = returns[returns <= var_percentile]
        cvar = -np.mean(tail_returns) if len(tail_returns) > 0 else var

        return float(var), float(cvar)

    def _parametric_var_cvar(self, returns: np.ndarray) -> tuple[float, float]:
        """Calculate parametric (Gaussian) VaR and CVaR.

        Assumes returns are normally distributed.

        Args:
            returns: Array of returns

        Returns:
            Tuple of (VaR, CVaR) as percentages (positive = loss)
        """
        mean = np.mean(returns)
        std = np.std(returns, ddof=1)

        if std == 0:
            return 0.0, 0.0

        # Z-score for confidence level
        stats = _load_scipy_stats()

        z = stats.norm.ppf(1 - self.config.confidence_level)

        # VaR = -mean - z * std (for loss)
        var = -(mean + z * std)
        var = max(0.0, var)  # VaR should be non-negative

        # CVaR for normal distribution
        # CVaR = mean + std * phi(z) / (1 - alpha)
        # where phi is the PDF and alpha is confidence level
        alpha = self.config.confidence_level
        phi_z = stats.norm.pdf(z)
        cvar = -(mean - std * phi_z / (1 - alpha))
        cvar = max(var, cvar)  # CVaR >= VaR

        return float(var), float(cvar)

    def _cornish_fisher_var_cvar(self, returns: np.ndarray) -> tuple[float, float]:
        """Calculate Cornish-Fisher adjusted VaR and CVaR.

        Adjusts for skewness and kurtosis of the return distribution.

        Args:
            returns: Array of returns

        Returns:
            Tuple of (VaR, CVaR) as percentages (positive = loss)
        """
        mean = np.mean(returns)
        std = np.std(returns, ddof=1)

        if std == 0:
            return 0.0, 0.0

        # Calculate skewness and excess kurtosis
        stats = _load_scipy_stats()

        skew = stats.skew(returns)
        kurt = stats.kurtosis(returns)  # Excess kurtosis

        # Standard normal quantile
        z = stats.norm.ppf(1 - self.config.confidence_level)

        # Cornish-Fisher expansion
        z_cf = (
            z
            + (z**2 - 1) * skew / 6
            + (z**3 - 3 * z) * kurt / 24
            - (2 * z**3 - 5 * z) * skew**2 / 36
        )

        # VaR with Cornish-Fisher adjustment
        var = -(mean + z_cf * std)
        var = max(0.0, var)

        # Approximate CVaR (use historical for tail average)
        var_percentile = mean + z_cf * std
        tail_returns = returns[returns <= var_percentile]
        cvar = -np.mean(tail_returns) if len(tail_returns) > 0 else var

        return float(var), float(cvar)

    def calculate_from_equity_curve(
        self,
        equity_curve: Sequence[Any],
    ) -> TailRiskResult:
        """Calculate VaR/CVaR from an equity curve.

        Args:
            equity_curve: List of (date, equity) tuples or list of equity values

        Returns:
            TailRiskResult with VaR and CVaR metrics
        """
        # Extract equity values
        equities: list[float] = []
        if equity_curve:
            first = equity_curve[0]
            if isinstance(first, tuple):
                equities = [float(e[1]) for e in equity_curve]
            else:
                equities = [float(e) for e in equity_curve]

        if len(equities) < 2:
            return TailRiskResult(
                var=Decimal('0'),
                cvar=Decimal('0'),
                confidence_level=self.config.confidence_level,
                method=self.config.method,
                sample_size=0,
            )

        # Calculate returns
        returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] != 0:
                ret = (equities[i] - equities[i - 1]) / equities[i - 1]
                returns.append(ret)

        portfolio_value = Decimal(str(equities[-1])) if equities else Decimal('0')
        return self.calculate(returns, portfolio_value)


def calculate_var(
    returns: Sequence[float],
    confidence_level: float = 0.95,
    method: str = 'historical',
) -> float:
    """Convenience function to calculate VaR.

    Args:
        returns: Sequence of periodic returns
        confidence_level: VaR confidence level
        method: Calculation method

    Returns:
        VaR as percentage (positive = loss)
    """
    config = TailRiskConfig(confidence_level=confidence_level, method=method)
    calculator = TailRiskCalculator(config)
    result = calculator.calculate(returns)
    return result.var_pct


def calculate_cvar(
    returns: Sequence[float],
    confidence_level: float = 0.95,
    method: str = 'historical',
) -> float:
    """Convenience function to calculate CVaR (Expected Shortfall).

    Args:
        returns: Sequence of periodic returns
        confidence_level: VaR confidence level
        method: Calculation method

    Returns:
        CVaR as percentage (positive = loss)
    """
    config = TailRiskConfig(confidence_level=confidence_level, method=method)
    calculator = TailRiskCalculator(config)
    result = calculator.calculate(returns)
    return result.cvar_pct
