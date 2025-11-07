from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable

from ..execution import ExecutionReport, Order


class BaseBroker(ABC):
    """
    Common interface for broker backends (paper, IBKR, etc.).
    """

    def __init__(self) -> None:
        self._fill_handler: Callable[[ExecutionReport], None] | None = None

    def set_fill_handler(self, handler: Callable[[ExecutionReport], None]) -> None:
        self._fill_handler = handler

    def _on_fill(self, report: ExecutionReport) -> None:
        if self._fill_handler:
            self._fill_handler(report)

    @abstractmethod
    def start(self) -> None:
        """Bring the broker connection online (no-op for offline simulators)."""

    @abstractmethod
    def stop(self) -> None:
        """Gracefully stop the broker connection."""

    @abstractmethod
    def submit(self, order: Order) -> int:
        """Submit an order and return broker-specific order id."""

    @abstractmethod
    def cancel(self, order_id: int) -> bool:
        """Attempt to cancel the order."""

    @abstractmethod
    def cancel_all_orders(self) -> int:
        """Cancel all pending orders.

        Returns:
            Number of orders cancelled
        """

    def subscribe_realtime_bars(
        self,
        symbol: str,
        handler: Callable[[datetime, str, float, float, float, float, float], None],
        bar_size: int = 5,
    ) -> int:
        raise NotImplementedError('Real-time bars not supported for this broker')

    def unsubscribe(self, req_id: int) -> None:
        return

    def get_positions(self) -> dict[str, tuple[float, float]]:
        """
        P0 Fix: Retrieve current broker positions for reconciliation.

        Returns:
            Dict mapping symbol -> (quantity, average_price)

        Raises:
            NotImplementedError: If broker doesn't support position retrieval
        """
        raise NotImplementedError('Position retrieval not supported for this broker')
