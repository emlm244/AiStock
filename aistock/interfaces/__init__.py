"""Protocol interfaces for AIStock components.

This module defines abstract protocols (interfaces) for all major components,
enabling dependency injection, testability, and swappable implementations.
"""

from .broker import BrokerProtocol
from .decision import DecisionEngineProtocol
from .market_data import MarketDataProviderProtocol
from .persistence import StateManagerProtocol
from .portfolio import PortfolioProtocol
from .risk import RiskEngineProtocol

__all__ = [
    'BrokerProtocol',
    'DecisionEngineProtocol',
    'MarketDataProviderProtocol',
    'PortfolioProtocol',
    'RiskEngineProtocol',
    'StateManagerProtocol',
]
