"""Risk management module.

This module provides:
1. Core risk management (RiskEngine, RiskState, RiskViolation)
2. Advanced risk management features:
   - Kelly Criterion position sizing
   - Portfolio correlation limits
   - Market regime detection
   - Volatility-based position scaling

Example usage:
    from aistock.risk import (
        RiskEngine,
        RiskViolation,
        RiskState,
        AdvancedRiskConfig,
        AdvancedRiskManager,
    )
"""

from .advanced_config import (
    AdvancedRiskConfig,
    CorrelationLimitsConfig,
    KellyCriterionConfig,
    RegimeDetectionConfig,
    VolatilityScalingConfig,
)
from .advanced_risk_manager import AdvancedRiskManager, AdvancedRiskResult
from .correlation import CorrelationCheckResult, CorrelationMonitor
# Core risk management (from original risk.py)
from .engine import RiskEngine, RiskState, RiskViolation
from .kelly import KellyCriterionSizer, KellyResult
from .regime import MarketRegime, RegimeDetector, RegimeResult
from .tail_risk import (
    TailRiskCalculator,
    TailRiskConfig,
    TailRiskResult,
    calculate_cvar,
    calculate_var,
)
from .volatility_scaling import VolatilityScaler, VolatilityScaleResult

__all__ = [
    # Core risk management
    'RiskEngine',
    'RiskState',
    'RiskViolation',
    # Advanced configs
    'AdvancedRiskConfig',
    'CorrelationLimitsConfig',
    'KellyCriterionConfig',
    'RegimeDetectionConfig',
    'VolatilityScalingConfig',
    # Advanced managers
    'AdvancedRiskManager',
    'AdvancedRiskResult',
    # Correlation
    'CorrelationCheckResult',
    'CorrelationMonitor',
    # Kelly
    'KellyCriterionSizer',
    'KellyResult',
    # Regime
    'MarketRegime',
    'RegimeDetector',
    'RegimeResult',
    # Volatility
    'VolatilityScaleResult',
    'VolatilityScaler',
    # Tail risk
    'TailRiskCalculator',
    'TailRiskConfig',
    'TailRiskResult',
    'calculate_var',
    'calculate_cvar',
]
