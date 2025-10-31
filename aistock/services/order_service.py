"""Order management service."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ..execution import Order, OrderSide, OrderType
from ..idempotency import OrderIdempotencyTracker

if TYPE_CHECKING:
    from ..interfaces.broker import BrokerProtocol
    from ..interfaces.risk import RiskEngineProtocol


class OrderService:
    """Order submission and tracking service.

    Encapsulates order lifecycle management with idempotency.
    """

    def __init__(
        self,
        broker: BrokerProtocol,
        risk_engine: RiskEngineProtocol,
        idempotency_tracker: OrderIdempotencyTracker,
    ):
        self.broker = broker
        self.risk_engine = risk_engine
        self.idempotency = idempotency_tracker

        self._order_tracking: dict[int, dict[str, Any]] = {}
        self.logger = logging.getLogger(__name__)

    def submit_market_order(
        self,
        symbol: str,
        quantity: Decimal,
        side: OrderSide,
        timestamp: datetime,
        last_prices: dict[str, Decimal],
        equity: Decimal,
    ) -> dict[str, Any]:
        """Submit a market order with safety checks.

        Returns:
            Dict with 'success', 'order_id', 'reason'
        """
        # Generate idempotent order ID
        signed_qty = quantity if side == OrderSide.BUY else -quantity
        client_order_id = self.idempotency.generate_client_order_id(
            symbol, timestamp, signed_qty
        )

        # Check for duplicate
        if self.idempotency.is_duplicate(client_order_id):
            return {
                'success': False,
                'reason': 'duplicate_order',
                'client_order_id': client_order_id,
            }

        # Risk check
        current_price = last_prices.get(symbol, Decimal('0'))
        if current_price <= 0:
            return {'success': False, 'reason': 'invalid_price'}

        try:
            self.risk_engine.check_pre_trade(
                symbol, signed_qty, current_price, equity, last_prices
            )
        except Exception as exc:
            return {'success': False, 'reason': f'risk_violation: {exc}'}

        # Submit order
        try:
            order = Order(
                symbol=symbol,
                quantity=abs(signed_qty),
                side=side,
                order_type=OrderType.MARKET,
                submit_time=timestamp,
                client_order_id=client_order_id,
            )

            self.risk_engine.record_order_submission(timestamp)
            self.idempotency.mark_submitted(client_order_id)

            order_id = self.broker.submit(order)

            # Track order
            self._order_tracking[order_id] = {
                'symbol': symbol,
                'quantity': float(quantity),
                'side': side.value,
                'submit_time': timestamp,
                'client_order_id': client_order_id,
            }

            self.logger.info(f'Order submitted: {symbol} {order_id}')

            return {
                'success': True,
                'order_id': order_id,
                'client_order_id': client_order_id,
                'symbol': symbol,
                'quantity': float(quantity),
                'side': side.value,
            }

        except Exception as exc:
            self.logger.error(f'Order submission failed: {exc}')
            return {'success': False, 'reason': f'submission_error: {exc}'}

    def cancel_order(self, order_id: int) -> dict[str, Any]:
        """Cancel an order.

        Returns:
            Dict with 'success', 'reason'
        """
        try:
            success = self.broker.cancel(order_id)

            if success:
                self._order_tracking.pop(order_id, None)
                self.logger.info(f'Order cancelled: {order_id}')

            return {'success': success, 'order_id': order_id}

        except Exception as exc:
            self.logger.error(f'Cancel failed: {exc}')
            return {'success': False, 'reason': f'cancel_error: {exc}'}

    def get_pending_orders(self) -> list[dict[str, Any]]:
        """Get all pending orders."""
        return list(self._order_tracking.values())

    def order_filled(self, order_id: int) -> None:
        """Mark order as filled."""
        self._order_tracking.pop(order_id, None)
