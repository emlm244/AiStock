"""Immutable state snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable snapshot of trading state at a point in time.

    Provides read-only view of state for components.
    """

    timestamp: datetime

    # Portfolio state
    cash: Decimal
    equity: Decimal
    positions: dict[str, dict[str, Any]]  # symbol -> position details

    # Risk state
    daily_pnl: Decimal
    peak_equity: Decimal
    is_halted: bool
    halt_reason: str | None

    # Trading state
    pending_orders: list[dict[str, Any]]
    last_prices: dict[str, Decimal]

    # Session state
    trade_count: int
    session_start: datetime | None

    def get_position_qty(self, symbol: str) -> Decimal:
        """Get position quantity for symbol."""
        pos = self.positions.get(symbol, {})
        return Decimal(str(pos.get('quantity', 0)))

    def get_last_price(self, symbol: str) -> Decimal | None:
        """Get last price for symbol."""
        return self.last_prices.get(symbol)

    def get_exposure(self) -> Decimal:
        """Get total exposure across all positions."""
        total = Decimal('0')
        for symbol, pos in self.positions.items():
            qty = Decimal(str(pos.get('quantity', 0)))
            price = self.last_prices.get(symbol, Decimal('0'))
            total += abs(qty) * price
        return total
