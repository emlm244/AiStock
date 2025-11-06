"""State persistence protocol interface."""

from __future__ import annotations

from typing import Any, Protocol

from ..portfolio import Portfolio
from ..risk import RiskState
from .portfolio import PortfolioProtocol


class StateManagerProtocol(Protocol):
    """Protocol defining the state persistence interface.

    This allows swapping storage backends (file, database, cloud)
    without changing the trading logic.
    """

    def save_checkpoint(
        self,
        portfolio: PortfolioProtocol,
        risk_state: RiskState,
        checkpoint_dir: str,
    ) -> None:
        """Save a checkpoint."""
        ...

    def load_checkpoint(
        self,
        checkpoint_dir: str,
    ) -> tuple[Portfolio, RiskState]:
        """Load a checkpoint.

        Raises:
            FileNotFoundError: If checkpoint doesn't exist
        """
        ...

    def save_state(self, state: dict[str, Any], filepath: str) -> None:
        """Save arbitrary state to file."""
        ...

    def load_state(self, filepath: str) -> dict[str, Any]:
        """Load state from file.

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        ...
