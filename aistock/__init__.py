"""
AIStock Package - FSD (Full Self-Driving) Trading Engine

This package provides:
- FSD (Full Self-Driving) RL trading agent with Q-Learning
- Custom trading engine for execution
- Portfolio and risk management
- Live and paper trading support
- Interactive Brokers integration

PROFESSIONAL ENHANCEMENTS (v2.0):
- Multi-timeframe analysis and correlation
- Candlestick pattern recognition
- Professional trading safeguards
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import config as config
    from . import data as data
    from . import edge_cases as edge_cases
    from . import engine as engine
    from . import fsd as fsd
    from . import logging as logging
    from . import patterns as patterns
    from . import performance as performance
    from . import portfolio as portfolio
    from . import professional as professional
    from . import risk as risk
    from . import session as session
    from . import timeframes as timeframes
    from . import universe as universe

__version__ = '2.0.0'
__all__ = [
    'config',
    'data',
    'edge_cases',
    'engine',
    'fsd',
    'patterns',
    'performance',
    'portfolio',
    'professional',
    'risk',
    'session',
    'timeframes',
    'universe',
    'logging',
]


def __getattr__(name: str) -> ModuleType:  # pragma: no cover
    """Lazy-load top-level module attributes to avoid importing heavy deps at package import time."""
    if name in __all__:
        module = importlib.import_module(f'{__name__}.{name}')
        globals()[name] = module
        return module
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__() -> list[str]:  # pragma: no cover
    return sorted(set(list(globals()) + __all__))
