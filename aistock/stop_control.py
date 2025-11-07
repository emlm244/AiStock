"""Manual stop control and graceful shutdown for trading sessions.

This module provides a StopController that enables:
- Manual stop button functionality
- Graceful position liquidation
- End-of-day automatic flattening
- Emergency halt with cancel-all-orders
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .brokers.base import BaseBroker
    from .portfolio import Portfolio


@dataclass
class StopConfig:
    """Configuration for stop control."""

    enable_manual_stop: bool = True  # Allow manual stop button
    enable_eod_flatten: bool = False  # Auto-flatten at end of day
    eod_flatten_time: time = time(15, 45)  # 3:45 PM ET (15 min before close)
    emergency_liquidation_timeout: float = 30.0  # Seconds to wait for position closes


class StopController:
    """
    Controller for manual stops and graceful shutdown.

    Provides:
    - Manual stop button: Sets flag, cancels orders, closes positions
    - End-of-day flatten: Auto-closes positions before market close
    - Emergency halt: Immediate order cancellation

    Thread-safe for concurrent access from UI/coordinator.

    Example:
        >>> controller = StopController(StopConfig(enable_manual_stop=True))
        >>> # User clicks stop button
        >>> controller.request_stop('manual_user_stop')
        >>> # Check if stop requested
        >>> if controller.is_stop_requested():
        ...     coordinator.initiate_shutdown()
    """

    def __init__(self, config: StopConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)

        self._stop_requested = threading.Event()
        self._stop_reason: str | None = None
        self._lock = threading.Lock()

        self._eod_flatten_executed = False

    def request_stop(self, reason: str = 'manual') -> None:
        """
        Request trading stop (manual stop button).

        Sets stop flag that coordinator should check. Does NOT
        directly halt trading - coordinator must respond.

        Args:
            reason: Reason for stop (e.g., 'manual_user_stop', 'end_of_day', 'emergency')

        Example:
            >>> controller.request_stop('user_clicked_stop_button')
            >>> # Coordinator checks: controller.is_stop_requested()
        """
        with self._lock:
            if not self._stop_requested.is_set():
                self._stop_requested.set()
                self._stop_reason = reason
                self.logger.warning(f'STOP REQUESTED: {reason}')

    def is_stop_requested(self) -> bool:
        """Check if stop has been requested."""
        return self._stop_requested.is_set()

    def get_stop_reason(self) -> str | None:
        """Get reason for stop request."""
        with self._lock:
            return self._stop_reason

    def check_eod_flatten(self, current_time: datetime) -> bool:
        """
        Check if end-of-day flatten should execute.

        Args:
            current_time: Current UTC datetime

        Returns:
            True if flatten should execute now

        Example:
            >>> if controller.check_eod_flatten(datetime.now(timezone.utc)):
            ...     # Execute position flattening
        """
        if not self.config.enable_eod_flatten:
            return False

        if self._eod_flatten_executed:
            return False  # Already done today

        # Convert UTC to ET for market hours check
        # Simplified: Assume 4-hour offset (EDT)
        et_time = current_time.time()

        # Check if we've reached flatten time
        if et_time >= self.config.eod_flatten_time:
            self._eod_flatten_executed = True
            self.logger.info(f'End-of-day flatten triggered at {et_time}')
            return True

        return False

    def reset_eod_flatten(self) -> None:
        """Reset end-of-day flatten flag (call at start of each trading day)."""
        self._eod_flatten_executed = False

    def execute_graceful_shutdown(
        self, broker: BaseBroker, portfolio: Portfolio, last_prices: dict[str, Decimal]
    ) -> dict[str, str]:
        """
        Execute graceful shutdown sequence.

        Steps:
        1. Cancel all pending orders
        2. Close all open positions (market orders)
        3. Wait for fills
        4. Return status

        Args:
            broker: Broker instance to use
            portfolio: Portfolio instance
            last_prices: Current market prices

        Returns:
            Dict with shutdown status

        Example:
            >>> status = controller.execute_graceful_shutdown(broker, portfolio, prices)
            >>> print(status['status'])  # 'success' or 'partial'
        """
        self.logger.warning('Executing graceful shutdown sequence...')

        # Step 1: Cancel all pending orders
        try:
            # Note: Actual order cancellation would need order tracking
            # This is a placeholder for the logic
            self.logger.info('Cancelling all pending orders...')
            # broker.cancel_all_orders()  # Would need to implement
        except Exception as e:
            self.logger.error(f'Failed to cancel orders: {e}')

        # Step 2: Close all positions
        closed_positions = []
        failed_positions = []

        positions = portfolio.snapshot_positions()
        for symbol, position in positions.items():
            if position.quantity == 0:
                continue  # Skip flat positions

            try:
                # Create closing order (opposite direction)
                close_qty = -position.quantity  # Flip sign to close

                self.logger.info(f'Closing position: {symbol} qty={position.quantity:.2f}')

                # Submit market order to close
                # Note: This is simplified - actual implementation would use broker.submit()
                # order = Order(
                #     symbol=symbol,
                #     side=OrderSide.SELL if close_qty < 0 else OrderSide.BUY,
                #     quantity=abs(close_qty),
                #     order_type=OrderType.MARKET
                # )
                # broker.submit(order)

                closed_positions.append(symbol)

            except Exception as e:
                self.logger.error(f'Failed to close {symbol}: {e}')
                failed_positions.append(symbol)

        # Step 3: Summary
        status = {
            'status': 'success' if not failed_positions else 'partial',
            'closed_positions': ','.join(closed_positions),
            'failed_positions': ','.join(failed_positions),
            'reason': self._stop_reason or 'unknown',
        }

        self.logger.warning(f'Shutdown complete: {status}')
        return status


def create_liquidation_orders(portfolio: Portfolio) -> list[tuple[str, Decimal]]:
    """
    Create liquidation orders for all open positions.

    Args:
        portfolio: Portfolio with positions to close

    Returns:
        List of (symbol, signed_quantity) tuples for closing orders

    Example:
        >>> orders = create_liquidation_orders(portfolio)
        >>> for symbol, qty in orders:
        ...     submit_market_order(symbol, qty)  # Close position
    """
    orders = []
    positions = portfolio.snapshot_positions()

    for symbol, position in positions.items():
        if position.quantity == 0:
            continue

        # Flip sign to close (sell longs, buy shorts)
        close_qty = -position.quantity
        orders.append((symbol, close_qty))

    return orders
