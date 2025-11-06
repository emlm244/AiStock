"""
Portfolio tracking for backtesting.

P0-NEW-1 Fix: Thread-safe portfolio for concurrent access from IBKR callbacks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from threading import Lock
from typing import Any

from .performance import calculate_realized_pnl


@dataclass
class Position:
    """Represents a position in a portfolio."""

    symbol: str
    quantity: Decimal = Decimal('0')
    average_price: Decimal = Decimal('0')
    entry_time_utc: datetime | None = None
    last_update_utc: datetime | None = None
    total_volume: Decimal = Decimal('0')

    def __post_init__(self):
        if self.entry_time_utc is None:
            self.entry_time_utc = datetime.now(timezone.utc)
        if self.last_update_utc is None:
            self.last_update_utc = self.entry_time_utc

    @property
    def market_value(self) -> Decimal:
        """Calculate market value (requires current price)."""
        return self.quantity * self.average_price

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.quantity < 0

    def realise(self, quantity_delta: Decimal, price: Decimal, timestamp: datetime | None = None):
        """
        Update position with a fill (for paper broker).

        Args:
            quantity_delta: Change in quantity (positive for buy, negative for sell)
            price: Fill price
            timestamp: Fill timestamp
        """
        new_qty = self.quantity + quantity_delta

        # Update average price
        if new_qty == 0:
            self.quantity = Decimal('0')
            self.average_price = Decimal('0')
        elif (self.quantity > 0 and new_qty < 0) or (self.quantity < 0 and new_qty > 0):
            # Reversal - new basis
            self.quantity = new_qty
            self.average_price = price
        elif (self.quantity >= 0 and quantity_delta > 0) or (self.quantity <= 0 and quantity_delta < 0):
            # Adding to position
            if self.quantity == 0:
                self.average_price = price
            else:
                total_cost = (self.quantity * self.average_price) + (quantity_delta * price)
                self.average_price = total_cost / new_qty
            self.quantity = new_qty
        else:
            # Reducing position - keep average price
            self.quantity = new_qty

        # Update timestamps
        if timestamp:
            if self.entry_time_utc is None:
                self.entry_time_utc = timestamp
            self.last_update_utc = timestamp


class Portfolio:
    """
    Simple portfolio tracker for backtest engines.

    Tracks:
    - Cash balance
    - Position quantities
    - Average entry prices
    - Realized P&L
    """

    def __init__(self, cash: Decimal | None = None, initial_cash: Decimal | None = None):
        # P0-NEW-1 Fix: Add lock for thread safety (IBKR callbacks run on separate thread)
        self._lock = Lock()

        starting_cash = cash if cash is not None else (initial_cash if initial_cash is not None else Decimal('10000'))
        self.initial_cash = starting_cash
        self.cash = starting_cash
        self.positions: dict[str, Position] = {}
        self.realised_pnl = Decimal('0')
        self.commissions_paid = Decimal('0')
        self.trade_log: list[dict[str, Any]] = []
        self.logger = logging.getLogger(__name__)

    def get_cash(self) -> Decimal:
        """Get current cash balance (thread-safe)."""
        with self._lock:
            return self.cash

    def get_position(self, symbol: str) -> Decimal:
        """Get current position quantity for symbol (thread-safe)."""
        with self._lock:
            pos = self.positions.get(symbol)
            return pos.quantity if pos else Decimal('0')

    def get_avg_price(self, symbol: str) -> Decimal | None:
        """Get average entry price for symbol (thread-safe)."""
        with self._lock:
            pos = self.positions.get(symbol)
            return pos.average_price if pos else None

    def update_position(self, symbol: str, quantity_delta: Decimal, price: Decimal, commission: Decimal = Decimal('0')):
        """
        Update position and cash after a trade (thread-safe).

        CRITICAL FIX: Atomic transaction - validate position update before committing cash change.

        Args:
            symbol: Trading symbol
            quantity_delta: Change in position (positive for buy, negative for sell)
            price: Execution price
            commission: Transaction cost
        """
        with self._lock:
            # CRITICAL FIX: Calculate cash delta but don't apply yet
            cash_delta = -(quantity_delta * price) - commission

            existing_position = self.positions.get(symbol)
            original_state = replace(existing_position) if existing_position else None

            if existing_position is None:
                self.positions[symbol] = Position(symbol=symbol)

            pos = self.positions[symbol]

            # CRITICAL FIX: Try position update first (may raise exception)
            try:
                pos.realise(quantity_delta, price, datetime.now(timezone.utc))

                # Only update cash if position update succeeded
                self.cash += cash_delta

                # Remove position if closed
                if pos.quantity == 0:
                    del self.positions[symbol]

            except Exception as exc:
                # Position update failed - restore previous state and surface detailed context
                if original_state is None:
                    self.positions.pop(symbol, None)
                else:
                    self.positions[symbol] = original_state

                self.logger.error(
                    'Position update failed',
                    exc_info=True,
                    extra={
                        'symbol': symbol,
                        'quantity_delta': str(quantity_delta),
                        'price': str(price),
                        'commission': str(commission),
                    },
                )
                raise exc

    def record_pnl(self, pnl: Decimal):
        """Record realized P&L (thread-safe)."""
        with self._lock:
            self.realised_pnl += pnl

    def get_equity(self, current_prices: dict[str, Decimal]) -> Decimal:
        """
        Calculate total equity (cash + position values) [thread-safe].

        Args:
            current_prices: Dict of symbol -> current price

        Returns:
            Total equity value
        """
        with self._lock:
            position_value = Decimal('0')

            for symbol, pos in self.positions.items():
                if symbol in current_prices:
                    position_value += pos.quantity * current_prices[symbol]

            return self.cash + position_value

    def total_equity(self, current_prices: dict[str, Decimal]) -> Decimal:
        """Alias for get_equity for compatibility (thread-safe)."""
        return self.get_equity(current_prices)

    def apply_fill(
        self, symbol: str, quantity: Decimal, price: Decimal, commission: Decimal, timestamp: datetime
    ) -> Decimal:
        """
        Apply a fill to the portfolio and return realized P&L (thread-safe).

        Args:
            symbol: Trading symbol
            quantity: Quantity filled (positive for buy, negative for sell)
            price: Fill price
            commission: Commission paid
            timestamp: Fill timestamp

        Returns:
            Realized P&L from this fill
        """
        with self._lock:
            # Compute realized P&L using current position snapshot via shared helper
            existing_position = self.positions.get(symbol)
            realized_pnl = (
                calculate_realized_pnl(
                    position_quantity=existing_position.quantity,
                    average_price=existing_position.average_price,
                    fill_quantity=quantity,
                    fill_price=price,
                )
                if existing_position
                else Decimal('0')
            )

            # Update cash and position atomically
            cash_delta = -(quantity * price) - commission
            self.cash += cash_delta

            if symbol not in self.positions:
                self.positions[symbol] = Position(symbol=symbol)

            position = self.positions[symbol]
            position.realise(quantity, price, timestamp)
            if position.quantity == 0:
                del self.positions[symbol]

            if realized_pnl:
                self.realised_pnl += realized_pnl

            return realized_pnl

    def position(self, symbol: str) -> Position:
        """
        Get position object for a symbol (thread-safe).

        Args:
            symbol: Trading symbol

        Returns:
            Position object (may have zero quantity if no position)
        """
        with self._lock:
            if symbol in self.positions:
                # Return a copy to prevent external modification
                pos = self.positions[symbol]
                return Position(
                    symbol=pos.symbol,
                    quantity=pos.quantity,
                    average_price=pos.average_price,
                    entry_time_utc=pos.entry_time_utc,
                    last_update_utc=pos.last_update_utc,
                    total_volume=pos.total_volume,
                )
            return Position(symbol=symbol)

    def snapshot_positions(self) -> dict[str, Position]:
        """Return a deep copy of all positions for thread-safe inspection."""
        with self._lock:
            return {symbol: replace(pos) for symbol, pos in self.positions.items()}

    def position_count(self) -> int:
        """Return the number of open positions (thread-safe)."""
        with self._lock:
            return len(self.positions)

    def get_trade_log_snapshot(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return a copy of the most recent trade log entries (thread-safe)."""
        with self._lock:
            entries = self.trade_log if limit is None else self.trade_log[-limit:]
            return [dict(entry) for entry in entries]

    def replace_positions(self, positions: dict[str, Position]) -> None:
        """Replace the internal positions map with a copy of the provided positions (thread-safe)."""
        with self._lock:
            self.positions = {symbol: replace(pos) for symbol, pos in positions.items()}

    def get_realised_pnl(self) -> Decimal:
        """Return the realised P&L (thread-safe)."""
        with self._lock:
            return self.realised_pnl

    def get_commissions_paid(self) -> Decimal:
        """Return the total commissions paid (thread-safe)."""
        with self._lock:
            return self.commissions_paid
