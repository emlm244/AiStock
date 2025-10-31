"""Consolidated configuration management.

Provides a unified configuration hierarchy with composition and validation.
"""

from .builder import ConfigBuilder
from .trading_config import TradingConfig
from .validator import ConfigValidator

__all__ = [
    'ConfigBuilder',
    'TradingConfig',
    'ConfigValidator',
]
