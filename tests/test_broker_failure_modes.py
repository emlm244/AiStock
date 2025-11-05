"""
Focused broker and order-flow edge case tests.

These cover the scenarios that were previously identified but ensure
they interact with the current PaperBroker implementation correctly.
"""

from datetime import datetime, timezone
from decimal import Decimal

from aistock.brokers.paper import PaperBroker
from aistock.config import ExecutionConfig
from aistock.data import Bar
from aistock.execution import Order, OrderSide, OrderStatus


def _build_broker() -> PaperBroker:
    """Helper to construct a PaperBroker with default execution config."""
    return PaperBroker(ExecutionConfig(partial_fill_probability=0.0))


def test_paper_broker_tracks_open_orders_until_fill():
    """Orders should remain tracked in the broker until a fill occurs."""
    broker = _build_broker()

    order = Order(
        client_order_id='TEST-001',
        symbol='AAPL',
        side=OrderSide.BUY,
        quantity=Decimal('10'),
        limit_price=Decimal('150'),
    )

    order_id = broker.submit(order)

    # Order should be marked as submitted and tracked internally.
    assert order.status == OrderStatus.SUBMITTED
    assert order_id in broker._open_orders  # type: ignore[attr-defined]

    # Process a bar to generate a fill.
    bar = Bar(
        symbol='AAPL',
        timestamp=datetime.now(timezone.utc),
        open=Decimal('150'),
        high=Decimal('151'),
        low=Decimal('149'),
        close=Decimal('150'),
        volume=10_000,
    )
    broker.process_bar(bar, bar.timestamp)

    # After fill, order should be removed from tracking.
    assert order_id not in broker._open_orders  # type: ignore[attr-defined]


def test_order_apply_fill_rejects_overfill():
    """Order.apply_fill should guard against fills that exceed remaining size."""
    order = Order(
        client_order_id='FILL-001',
        symbol='AAPL',
        side=OrderSide.BUY,
        quantity=Decimal('5'),
    )

    # First partial fill is acceptable.
    order.apply_fill(Decimal('3'))
    assert order.remaining_quantity == Decimal('2')

    # Filling more than the remaining quantity should raise.
    try:
        order.apply_fill(Decimal('3'))
    except ValueError as exc:
        assert 'exceeds remaining' in str(exc)
    else:
        raise AssertionError('Expected ValueError when over-filling an order')
