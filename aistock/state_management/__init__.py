"""Centralized state management.

Provides unified state ownership and access patterns.
"""

from .manager import StateManager
from .state_snapshot import StateSnapshot

__all__ = [
    'StateManager',
    'StateSnapshot',
]
