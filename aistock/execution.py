"""
Paper-trading execution primitives with P1 partial fill support.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """P1 Enhancement: Order lifecycle states."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    symbol: str
    quantity: Decimal
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: str = "DAY"
    submit_time: datetime | None = None
    client_order_id: str | None = None  # P0 Fix: For idempotency
    # P1 Enhancement: Partial fill tracking
    filled_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal | None = None  # Auto-computed
    status: OrderStatus = OrderStatus.PENDING

    def __post_init__(self):
        """Initialize remaining quantity."""
        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity

    def apply_fill(self, fill_qty: Decimal) -> None:
        """
        P1 Enhancement: Update order state after partial/full fill.

        Raises:
            ValueError: If fill exceeds remaining quantity
        """
        if fill_qty <= 0:
            raise ValueError(f"Fill quantity must be positive, got {fill_qty}")
        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity
        if fill_qty > self.remaining_quantity:
            raise ValueError(
                f"Fill quantity {fill_qty} exceeds remaining {self.remaining_quantity}"
            )

        self.filled_quantity += fill_qty
        self.remaining_quantity -= fill_qty

        if self.remaining_quantity <= Decimal("0"):
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    def is_complete(self) -> bool:
        """Check if order is fully filled."""
        return self.status == OrderStatus.FILLED

    def fill_ratio(self) -> float:
        """Return fraction of order filled (0.0 to 1.0)."""
        if self.quantity == 0:
            return 0.0
        return float(self.filled_quantity / self.quantity)


@dataclass
class ExecutionReport:
    order_id: int
    symbol: str
    quantity: Decimal  # P1: This is the FILL quantity, not order quantity
    price: Decimal
    side: OrderSide
    timestamp: datetime
    # P1 Enhancement: Partial fill metadata
    is_partial: bool = False
    cumulative_filled: Decimal | None = None  # Total filled so far
    remaining: Decimal | None = None  # Remaining to fill

