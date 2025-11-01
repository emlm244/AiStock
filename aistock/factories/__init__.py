"""Factory classes for dependency injection.

Factories encapsulate component instantiation and wiring,
enabling clean dependency injection.
"""

from .session_factory import SessionFactory
from .trading_components_factory import TradingComponentsFactory

__all__ = [
    'SessionFactory',
    'TradingComponentsFactory',
]
