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
import time as time_module
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, TypedDict
from zoneinfo import ZoneInfo

from .calendar import nyse_trading_hours
from .execution import Order, OrderSide, OrderType

if TYPE_CHECKING:
    from .brokers.base import BaseBroker
    from .interfaces.portfolio import PortfolioProtocol


class ShutdownStatus(TypedDict):
    status: Literal['success', 'partial', 'failed']
    fully_closed: list[str]
    partially_closed: dict[str, float]
    failed: list[str]
    orders_cancelled: int
    retry_attempts: int
    total_wait_time: float
    reason: str


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
            # Honor enable_manual_stop config for manual stops
            if not self.config.enable_manual_stop and reason == 'manual':
                self.logger.info(f'Manual stop ignored (manual stops disabled): {reason}')
                return

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

        Handles both regular closes (4 PM ET) and early closes (1 PM ET).
        Flattens at configured time before close (e.g., 15 minutes).

        Args:
            current_time: Current UTC datetime

        Returns:
            True if flatten should execute now

        Example:
            >>> if controller.check_eod_flatten(datetime.now(timezone.utc)):
            ...     # Execute position flattening
        """
        with self._lock:
            if not self.config.enable_eod_flatten:
                return False

            if self._eod_flatten_executed:
                return False  # Already done today

            # Ensure current_time is timezone-aware UTC
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)

            # Get actual market close time for today (handles early closes)
            try:
                _open_time, close_time = nyse_trading_hours(current_time)
            except Exception as e:
                self.logger.warning(f'Could not get market hours: {e}, using default 4 PM')
                close_time = time(16, 0)  # Default to 4 PM ET

            # Calculate minutes before close that config specifies
            # E.g., if config is 15:45 and regular close is 16:00, that's 15 minutes before
            regular_close_minutes = 16 * 60  # 4 PM in minutes
            config_time_minutes = self.config.eod_flatten_time.hour * 60 + self.config.eod_flatten_time.minute
            minutes_before_close = regular_close_minutes - config_time_minutes

            # Clamp to prevent negative offset (if user set time after market close)
            if minutes_before_close < 0:
                self.logger.warning(
                    f'EOD flatten time {self.config.eod_flatten_time} is after regular market close '
                    f'(4 PM ET). Using market close time instead.'
                )
                minutes_before_close = 0  # Flatten exactly at close

            # Apply same offset to actual close time
            actual_close_minutes = close_time.hour * 60 + close_time.minute
            flatten_time_minutes = actual_close_minutes - minutes_before_close

            # Clamp to valid range to prevent negative values on early-close days
            flatten_time_minutes = max(0, min(actual_close_minutes, flatten_time_minutes))

            flatten_hour = flatten_time_minutes // 60
            flatten_minute = flatten_time_minutes % 60
            flatten_time_et = time(flatten_hour, flatten_minute)

            # Build flatten datetime in ET timezone (timezone-aware)
            # Using ZoneInfo ensures proper DST handling at transition boundaries
            flatten_datetime_et = datetime.combine(current_time.date(), flatten_time_et).replace(
                tzinfo=ZoneInfo('America/New_York')
            )

            # Convert ET to UTC (automatic DST handling)
            flatten_datetime_utc = flatten_datetime_et.astimezone(timezone.utc)

            # Check if we've reached flatten time
            if current_time >= flatten_datetime_utc:
                self._eod_flatten_executed = True
                self.logger.info(
                    f'End-of-day flatten triggered at {current_time.strftime("%H:%M:%S UTC")} '
                    f'(target: {flatten_time_et} ET, {minutes_before_close} min before {close_time} close)'
                )
                return True

            return False

    def reset_eod_flatten(self) -> None:
        """Reset end-of-day flatten flag (call at start of each trading day)."""
        self._eod_flatten_executed = False

    def execute_graceful_shutdown(
        self, broker: BaseBroker, portfolio: PortfolioProtocol, last_prices: dict[str, Decimal]
    ) -> ShutdownStatus:
        """
        Execute graceful shutdown sequence with advanced fill monitoring and retry logic.

        Steps:
        1. Cancel all pending orders
        2. Close all open positions (market orders)
        3. Monitor fills with polling (every 0.5s)
        4. Retry unfilled positions up to 3 times
        5. Return detailed status

        Args:
            broker: Broker instance to use
            portfolio: Portfolio instance
            last_prices: Current market prices (used for logging only)

        Returns:
            Dict with detailed shutdown status including:
            - status: 'success' (all closed), 'partial' (some closed), or 'failed'
            - fully_closed: List of symbols successfully liquidated
            - partially_closed: Dict of symbol -> remaining quantity
            - failed: List of symbols that couldn't be closed
            - retry_attempts: Number of retry rounds executed
            - total_wait_time: Seconds spent waiting for fills

        Example:
            >>> status = controller.execute_graceful_shutdown(broker, portfolio, prices)
            >>> print(status['status'])  # 'success', 'partial', or 'failed'
        """
        self.logger.warning('Executing graceful shutdown sequence...')
        self.logger.info(f'Current market prices: {dict(list(last_prices.items())[:5])}...')  # Log sample of prices
        start_time = time_module.time()

        # Step 1: Cancel all pending orders
        num_cancelled = 0
        try:
            self.logger.info('Cancelling all pending orders...')
            num_cancelled = broker.cancel_all_orders()
            self.logger.info(f'Cancelled {num_cancelled} pending orders')
        except Exception as e:
            self.logger.error(f'Failed to cancel orders: {e}')

        # Step 2: Submit initial liquidation orders
        submitted_symbols = self._submit_liquidation_orders(broker, portfolio)

        # Step 3: Monitor fills with retry logic
        max_retries = 3
        retry_count = 0
        fully_closed = []

        for retry_count in range(max_retries):
            if retry_count > 0:
                self.logger.info(f'Retry attempt {retry_count}/{max_retries-1}')

            # Monitor fills
            closed_this_round = self._monitor_fills(
                portfolio, self.config.emergency_liquidation_timeout, poll_interval=0.5
            )
            fully_closed.extend(closed_this_round)

            # Check remaining positions
            positions = portfolio.snapshot_positions()
            remaining = {sym: pos.quantity for sym, pos in positions.items() if abs(pos.quantity) > Decimal('0.01')}

            if not remaining:
                # All positions closed!
                break

            # Some positions remain, log and retry
            self.logger.warning(f'Positions still open: {list(remaining.keys())}')

            # Re-submit liquidation orders for remaining positions
            if retry_count < max_retries - 1:
                self.logger.info('Re-submitting liquidation orders for remaining positions')
                self._submit_liquidation_orders(broker, portfolio)

        # Calculate final status
        positions = portfolio.snapshot_positions()
        final_remaining = {
            sym: float(pos.quantity) for sym, pos in positions.items() if abs(pos.quantity) > Decimal('0.01')
        }

        total_time = time_module.time() - start_time

        if not final_remaining:
            status_str = 'success'
        elif len(final_remaining) < len(submitted_symbols):
            status_str = 'partial'
        else:
            status_str = 'failed'

        status: ShutdownStatus = {
            'status': status_str,
            'fully_closed': fully_closed,
            'partially_closed': final_remaining,
            'failed': list(final_remaining.keys()) if status_str == 'failed' else [],
            'orders_cancelled': num_cancelled,
            'retry_attempts': retry_count + 1,
            'total_wait_time': round(total_time, 2),
            'reason': self._stop_reason or 'unknown',
        }

        self.logger.warning(
            f'Shutdown complete: {status_str} - '
            f'{len(fully_closed)} closed, {len(final_remaining)} remaining, '
            f'{retry_count + 1} attempts, {total_time:.1f}s'
        )
        return status

    def _submit_liquidation_orders(self, broker: BaseBroker, portfolio: PortfolioProtocol) -> list[str]:
        """Submit liquidation orders for all open positions.

        Returns:
            List of symbols for which orders were submitted
        """
        submitted_symbols = []
        positions = portfolio.snapshot_positions()

        for symbol, position in positions.items():
            if abs(position.quantity) < Decimal('0.01'):
                continue  # Skip flat positions

            try:
                # Create closing order (opposite direction)
                close_qty = abs(position.quantity)
                # SELL if we have a long position (positive qty), BUY if short (negative qty)
                close_side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY

                self.logger.info(f'Closing position: {symbol} qty={position.quantity:.2f} side={close_side}')

                # Submit market order to close
                order = Order(
                    symbol=symbol,
                    side=close_side,
                    quantity=close_qty,
                    order_type=OrderType.MARKET,
                )
                broker.submit(order)
                submitted_symbols.append(symbol)

            except Exception as e:
                self.logger.error(f'Failed to submit close order for {symbol}: {e}')

        return submitted_symbols

    def _monitor_fills(self, portfolio: PortfolioProtocol, timeout: float, poll_interval: float = 0.5) -> list[str]:
        """Monitor portfolio positions until they're closed or timeout.

        Args:
            portfolio: Portfolio to monitor
            timeout: Maximum seconds to wait
            poll_interval: Seconds between polls

        Returns:
            List of symbols that were closed during monitoring
        """
        start_time = time_module.time()
        initial_positions = {sym: pos.quantity for sym, pos in portfolio.snapshot_positions().items()}
        closed_symbols: list[str] = []

        while time_module.time() - start_time < timeout:
            current_positions = portfolio.snapshot_positions()

            # Check which positions have closed
            for symbol in list(initial_positions.keys()):
                if symbol in closed_symbols:
                    continue
                current_pos = current_positions.get(symbol)
                if current_pos is None or abs(current_pos.quantity) < Decimal('0.01'):
                    closed_symbols.append(symbol)
                    self.logger.info(f'Position closed: {symbol}')

            # Check if all initial positions are now closed
            all_closed = True
            for sym in initial_positions:
                if sym in closed_symbols:
                    continue
                pos = current_positions.get(sym)
                qty = pos.quantity if pos is not None else Decimal('0')
                if abs(qty) >= Decimal('0.01'):
                    all_closed = False
                    break

            if all_closed:
                self.logger.info(f'All positions closed after {time_module.time() - start_time:.1f}s')
                return closed_symbols

            time_module.sleep(poll_interval)

        elapsed = time_module.time() - start_time
        self.logger.warning(f'Fill monitoring timeout after {elapsed:.1f}s, {len(closed_symbols)} closed')
        return closed_symbols


def create_liquidation_orders(portfolio: PortfolioProtocol) -> list[tuple[str, Decimal]]:
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
