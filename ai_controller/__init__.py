# ai_controller/__init__.py

"""
AI Controller Module - Autonomous Parameter Optimization

This module provides autonomous optimization capabilities for the trading bot,
including Bayesian parameter optimization, strategy selection, and position sizing.
"""

from .autonomous_optimizer import AutonomousOptimizer
from .mode_manager import ModeManager

__all__ = ['AutonomousOptimizer', 'ModeManager']
