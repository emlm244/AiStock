"""
Backtesting framework for AIStock.

This package provides:
- Walk-forward validation with out-of-sample testing
- Survivorship bias protection via historical universe reconstruction
- Realistic execution modeling with size-dependent slippage
- Comprehensive backtest reporting
"""

from .config import (
    BacktestPlanConfig,
    RealisticExecutionConfig,
    WalkForwardConfig,
)
from .execution import RealisticExecutionModel
from .orchestrator import BacktestOrchestrator
from .report import BacktestReport, generate_html_report
from .universe import HistoricalUniverseManager, UniverseValidationResult
from .walkforward import WalkForwardFold, WalkForwardResult, WalkForwardValidator

__all__ = [
    # Config
    'BacktestPlanConfig',
    'RealisticExecutionConfig',
    'WalkForwardConfig',
    # Execution
    'RealisticExecutionModel',
    # Orchestrator
    'BacktestOrchestrator',
    # Report
    'BacktestReport',
    'generate_html_report',
    # Universe
    'HistoricalUniverseManager',
    'UniverseValidationResult',
    # Walk-forward
    'WalkForwardFold',
    'WalkForwardResult',
    'WalkForwardValidator',
]
