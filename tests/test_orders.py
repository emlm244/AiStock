# tests/test_orders.py
"""Tests for order assembly and bracket order creation."""

import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from managers.order_manager import OrderManager
from managers.portfolio_manager import PortfolioManager


@pytest.fixture
def mock_api():
    """Create a mock IBKR API."""
    api = Mock()
    api.place_order = Mock(return_value=True)
    api.nextOrderId = 1000
    api.get_next_order_id = Mock(side_effect=lambda: api.nextOrderId)
    return api


@pytest.fixture
def settings():
    """Create settings."""
    s = Settings()
    s.ORDER_TYPE = 'MKT'
    return s


@pytest.fixture
def portfolio_manager(settings):
    """Create portfolio manager."""
    logger = Mock()
    pm = PortfolioManager(settings, logger)
    pm.total_equity = 10000.0
    return pm


@pytest.fixture
def order_manager(mock_api, portfolio_manager, settings):
    """Create order manager."""
    logger = Mock()
    return OrderManager(mock_api, portfolio_manager, settings, logger)


def test_bracket_order_creation(order_manager, mock_api):
    """Test that bracket orders are created with correct structure."""
    parent_id, stop_id, profit_id = order_manager.create_and_place_bracket_order(
        symbol='TEST',
        action='BUY',
        quantity=10.0,
        entry_price=100.0,
        stop_loss_price=95.0,
        take_profit_price=110.0,
        strategy_name='test_strategy',
    )

    assert parent_id is not None
    assert stop_id is not None
    assert profit_id is not None
    assert parent_id != stop_id != profit_id

    # API should have been called 3 times (parent + 2 children)
    assert mock_api.place_order.call_count == 3


def test_bracket_order_sell_direction(order_manager, mock_api):
    """Test bracket order for SELL direction."""
    parent_id, stop_id, profit_id = order_manager.create_and_place_bracket_order(
        symbol='TEST',
        action='SELL',
        quantity=5.0,
        entry_price=100.0,
        stop_loss_price=105.0,  # SL above for short
        take_profit_price=90.0,  # TP below for short
        strategy_name='short_test',
    )

    assert parent_id is not None
    assert stop_id is not None
    assert profit_id is not None


def test_invalid_bracket_order_parameters(order_manager):
    """Test that invalid bracket parameters are rejected."""
    # SL should be below entry for BUY
    result = order_manager.create_and_place_bracket_order(
        symbol='TEST',
        action='BUY',
        quantity=10.0,
        entry_price=100.0,
        stop_loss_price=105.0,  # Invalid: above entry
        take_profit_price=110.0,
        strategy_name='invalid_test',
    )

    # Should return None or fail gracefully
    # Depending on implementation, may return (None, None, None)
    assert result[0] is None or result == (None, None, None)


def test_order_tracking(order_manager):
    """Test that orders are tracked correctly."""
    parent_id, stop_id, profit_id = order_manager.create_and_place_bracket_order(
        symbol='TEST',
        action='BUY',
        quantity=10.0,
        entry_price=100.0,
        stop_loss_price=95.0,
        take_profit_price=110.0,
        strategy_name='tracking_test',
    )

    # Check that parent order is tracked
    assert parent_id in order_manager.orders
    order_info = order_manager.orders[parent_id]
    assert order_info['symbol'] == 'TEST'
    assert order_info['action'] == 'BUY'
    assert order_info['quantity'] == 10.0


def test_zero_quantity_rejection(order_manager):
    """Test that zero or negative quantities are rejected."""
    result = order_manager.create_and_place_bracket_order(
        symbol='TEST',
        action='BUY',
        quantity=0.0,
        entry_price=100.0,
        stop_loss_price=95.0,
        take_profit_price=110.0,
        strategy_name='zero_qty',
    )

    assert result[0] is None


def test_negative_prices_rejection(order_manager):
    """Test that negative prices are rejected."""
    result = order_manager.create_and_place_bracket_order(
        symbol='TEST',
        action='BUY',
        quantity=10.0,
        entry_price=-100.0,  # Invalid
        stop_loss_price=95.0,
        take_profit_price=110.0,
        strategy_name='negative_price',
    )

    assert result[0] is None
