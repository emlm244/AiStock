from __future__ import annotations

import itertools
import random
from datetime import datetime
from decimal import Decimal

from ..config import ExecutionConfig
from ..data import Bar
from ..execution import ExecutionReport, Order, OrderSide, OrderStatus, OrderType
from ..portfolio import Position
from .base import BaseBroker


class PaperBroker(BaseBroker):
    """
    Deterministic broker used for backtesting and paper trading.

    P1 Enhancement: Supports partial fills based on ExecutionConfig.partial_fill_probability.
    """

    def __init__(self, execution_config: ExecutionConfig, seed: int = 42) -> None:
        super().__init__()
        self._config = execution_config
        self._order_id_seq = itertools.count(start=1)
        self._open_orders: dict[int, Order] = {}
        self._rng = random.Random(seed)  # P1: Deterministic partial fills
        self._positions: dict[str, Position] = {}

    def start(self) -> None:  # pragma: no cover - no-op for paper mode
        return

    def stop(self) -> None:  # pragma: no cover - no-op for paper mode
        self._open_orders.clear()
        self._positions.clear()

    def submit(self, order: Order) -> int:
        order_id = next(self._order_id_seq)
        order.status = OrderStatus.SUBMITTED  # P1: Mark as submitted
        self._open_orders[order_id] = order
        return order_id

    def cancel(self, order_id: int) -> bool:
        return self._open_orders.pop(order_id, None) is not None

    def process_bar(self, bar: Bar, timestamp: datetime) -> None:
        """
        P1 Enhancement: Process bar with partial fill support.

        If partial_fill_probability > 0, orders may fill incrementally.
        """
        to_remove = []
        for order_id, order in list(self._open_orders.items()):
            fill_price = self._determine_fill_price(order, bar)
            if fill_price is None:
                continue

            # P1: Determine fill quantity (partial or full)
            fill_qty = self._determine_fill_quantity(order)

            # Update order state
            order.apply_fill(fill_qty)

            # Create execution report
            report = ExecutionReport(
                order_id=order_id,
                symbol=order.symbol,
                quantity=fill_qty,  # P1: Fill quantity, not order quantity
                price=fill_price,
                side=order.side,
                timestamp=timestamp,
                is_partial=(not order.is_complete()),
                cumulative_filled=order.filled_quantity,
                remaining=order.remaining_quantity,
            )
            self._update_position(report)
            self._on_fill(report)

            # P1: Only remove if fully filled
            if order.is_complete():
                to_remove.append(order_id)

        for oid in to_remove:
            self._open_orders.pop(oid, None)

    def _determine_fill_quantity(self, order: Order) -> Decimal:
        """
        P1 Enhancement: Determine fill quantity (partial or full).

        Returns:
            Fill quantity based on partial_fill_probability config.
        """
        if self._config.partial_fill_probability <= 0 or order.remaining_quantity is None:
            # Full fill
            return order.remaining_quantity or order.quantity

        # Partial fill: random dice roll
        if self._rng.random() < self._config.partial_fill_probability:
            # Fill 20-80% of remaining (random)
            fill_fraction = Decimal(str(self._rng.uniform(0.2, 0.8)))
            fill_qty = order.remaining_quantity * fill_fraction
            return max(Decimal("0.01"), fill_qty)  # At least 0.01 units

        # Full fill of remaining
        return order.remaining_quantity

    def _determine_fill_price(self, order: Order, bar: Bar) -> Decimal | None:
        if order.symbol != bar.symbol:
            return None
        price = bar.close
        slip = (price * Decimal(self._config.slip_bps_limit)) / Decimal("10000")
        if order.order_type == OrderType.MARKET:
            return price + slip if order.side == OrderSide.BUY else price - slip
        if order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and bar.low <= (order.limit_price or price):
                return min(price, order.limit_price or price)
            if order.side == OrderSide.SELL and bar.high >= (order.limit_price or price):
                return max(price, order.limit_price or price)
        if order.order_type == OrderType.STOP:
            if order.side == OrderSide.BUY and bar.high >= (order.stop_price or price):
                return price + slip
            if order.side == OrderSide.SELL and bar.low <= (order.stop_price or price):
                return price - slip
        return None

    def get_positions(self) -> dict[str, tuple[float, float]]:
        """
        Simulated position snapshot for reconciliation with the in-memory portfolio.
        """
        return {
            symbol: (float(position.quantity), float(position.average_price))
            for symbol, position in self._positions.items()
            if position.quantity != 0
        }

    def _update_position(self, report: ExecutionReport) -> None:
        """Track simulated broker positions for reconciliation."""
        signed_qty = report.quantity if report.side == OrderSide.BUY else -report.quantity
        position = self._positions.get(report.symbol)
        if position is None:
            position = Position(symbol=report.symbol)
            self._positions[report.symbol] = position

        position.realise(signed_qty, report.price, report.timestamp)

        if position.quantity == 0:
            # Drop flat positions to keep reconciliation output clean.
            self._positions.pop(report.symbol, None)
