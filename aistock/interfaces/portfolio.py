"""Portfolio protocol interface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from ..portfolio import Position


class PortfolioProtocol(Protocol):
    """Protocol defining the portfolio interface.

    This allows swapping portfolio implementations for testing or
    different tracking strategies.
    """

    def get_cash(self) -> Decimal:
        """Get current cash balance."""
        ...

    def get_equity(self, last_prices: dict[str, Decimal]) -> Decimal:
        """Get total equity (cash + positions)."""
        ...

    def total_equity(self, last_prices: dict[str, Decimal]) -> Decimal:
        """Alias for get_equity for backward compatibility."""
        ...

    def position(self, symbol: str) -> Position:
        """Get position for a symbol."""
        ...

    def position_count(self) -> int:
        """Get number of open positions."""
        ...

    def apply_fill(
        self,
        symbol: str,
        signed_quantity: Decimal,
        price: Decimal,
        commission: Decimal,
        timestamp: datetime,
    ) -> Decimal:
        """Apply a fill and return realized P&L."""
        ...

    def snapshot_positions(self) -> dict[str, Position]:
        """Get a snapshot of all positions."""
        ...
