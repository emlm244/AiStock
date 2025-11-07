"""Broker protocol interface."""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Callable, Protocol

from ..execution import ExecutionReport, Order


class BrokerProtocol(Protocol):
    """Protocol defining the broker interface.

    This defines the contract that all broker implementations must follow,
    whether paper trading, IBKR, or other brokers.
    """

    def set_fill_handler(self, handler: Callable[[ExecutionReport], None]) -> None:
        """Set the callback for fill notifications."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Start the broker connection."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop the broker connection."""
        ...

    @abstractmethod
    def submit(self, order: Order) -> int:
        """Submit an order and return order ID."""
        ...

    @abstractmethod
    def cancel(self, order_id: int) -> bool:
        """Cancel an order."""
        ...

    def cancel_all_orders(self) -> int:
        """Cancel all pending orders.

        Returns:
            Number of orders cancelled
        """
        ...

    def subscribe_realtime_bars(
        self,
        symbol: str,
        handler: Callable[[datetime, str, float, float, float, float, float], None],
        bar_size: int = 5,
    ) -> int:
        """Subscribe to real-time bars (optional)."""
        ...

    def unsubscribe(self, req_id: int) -> None:
        """Unsubscribe from data feed (optional)."""
        ...

    def get_positions(self) -> dict[str, tuple[float, float]]:
        """Get current broker positions (optional)."""
        ...
