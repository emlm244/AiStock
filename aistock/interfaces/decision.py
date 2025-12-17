"""Decision engine protocol interface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Protocol, runtime_checkable

from ..data import Bar


class DecisionEngineProtocol(Protocol):
    """Protocol defining the decision engine interface.

    This allows swapping decision algorithms (FSD, ML, rule-based, etc.)
    without changing the trading session logic.
    """

    def evaluate_opportunity(
        self,
        symbol: str,
        bars: list[Bar],
        last_prices: dict[str, Decimal],
    ) -> dict[str, Any]:
        """Evaluate a trading opportunity.

        Args:
            symbol: Trading symbol
            bars: Historical bars
            last_prices: Current prices for all symbols

        Returns:
            Decision dict with keys:
            - should_trade: bool
            - action: dict with trade details
            - confidence: float
            - state: dict
            - reason: str
        """
        ...

    def register_trade_intent(
        self,
        symbol: str,
        timestamp: datetime,
        decision: dict[str, Any],
        target_notional: float,
        target_quantity: float,
    ) -> None:
        """Log trade intent for learning."""
        ...

    def handle_fill(
        self,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float,
    ) -> None:
        """Handle fill and update learning."""
        ...

    def start_session(self) -> dict[str, Any]:
        """Start a new trading session."""
        ...

    def end_session(self) -> dict[str, Any]:
        """End trading session and return stats."""
        ...

    def save_state(self, filepath: str) -> None:
        """Save learned state."""
        ...

    def load_state(self, filepath: str) -> bool:
        """Load learned state."""
        ...


@runtime_checkable
class SupportsGuiLogCallback(Protocol):
    gui_log_callback: Callable[[str], None] | None
