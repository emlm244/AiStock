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

from . import (
    config,
    data,
    edge_cases,
    engine,
    fsd,
    logging,
    patterns,
    performance,
    portfolio,
    professional,
    risk,
    session,
    timeframes,
    universe,
)

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
