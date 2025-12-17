"""
Tests for stop_control module (manual stops and graceful shutdown).

Coverage for:
- StopConfig dataclass
- StopController lifecycle (request_stop, is_stop_requested, reset)
- End-of-day flatten logic (regular close, early close, DST transitions)
- Graceful shutdown with retry logic
- Liquidation order creation
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest

from aistock.execution import Order, OrderSide, OrderType
from aistock.portfolio import Position
from aistock.stop_control import (
    StopConfig,
    StopController,
    create_liquidation_orders,
)

# ==================== Fixtures ====================


@pytest.fixture
def default_config():
    """Default StopConfig for testing."""
    return StopConfig(
        enable_manual_stop=True,
        enable_eod_flatten=True,
        eod_flatten_time=time(15, 45),  # 3:45 PM ET
        emergency_liquidation_timeout=2.0,  # Short timeout for tests
    )


@pytest.fixture
def mock_broker():
    """Mock broker for testing shutdown logic."""
    broker = MagicMock()
    broker.cancel_all_orders.return_value = 5  # 5 orders cancelled
    broker.submit.return_value = None
    return broker


@pytest.fixture
def mock_portfolio():
    """Mock portfolio with sample positions."""
    portfolio = MagicMock()

    # Create sample positions: AAPL long, MSFT short
    aapl_pos = Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150.00'))
    msft_pos = Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300.00'))

    portfolio.snapshot_positions.return_value = {'AAPL': aapl_pos, 'MSFT': msft_pos}

    return portfolio


@pytest.fixture
def empty_portfolio():
    """Mock portfolio with no positions."""
    portfolio = MagicMock()
    portfolio.snapshot_positions.return_value = {}
    return portfolio


# ==================== StopConfig Tests ====================


def test_stopconfig_default_values():
    """Test StopConfig initializes with expected defaults."""
    config = StopConfig()

    assert config.enable_manual_stop is True
    assert config.enable_eod_flatten is False  # Disabled by default
    assert config.eod_flatten_time == time(15, 45)
    assert config.emergency_liquidation_timeout == 30.0


def test_stopconfig_custom_values():
    """Test StopConfig accepts custom values."""
    config = StopConfig(
        enable_manual_stop=False,
        enable_eod_flatten=True,
        eod_flatten_time=time(15, 30),
        emergency_liquidation_timeout=60.0,
    )

    assert config.enable_manual_stop is False
    assert config.enable_eod_flatten is True
    assert config.eod_flatten_time == time(15, 30)
    assert config.emergency_liquidation_timeout == 60.0


# ==================== StopController Basic Tests ====================


def test_stopcontroller_init(default_config):
    """Test StopController initialization."""
    controller = StopController(default_config)

    assert controller.config == default_config
    assert not controller.is_stop_requested()
    assert controller.get_stop_reason() is None


def test_request_stop_manual(default_config):
    """Test manual stop request sets flag and reason."""
    controller = StopController(default_config)

    controller.request_stop('user_clicked_stop_button')

    assert controller.is_stop_requested()
    assert controller.get_stop_reason() == 'user_clicked_stop_button'


def test_request_stop_when_manual_disabled():
    """Test manual stop is ignored when disabled in config."""
    config = StopConfig(enable_manual_stop=False)
    controller = StopController(config)

    controller.request_stop('manual')  # Should be ignored

    assert not controller.is_stop_requested()
    assert controller.get_stop_reason() is None


def test_request_stop_eod_always_allowed():
    """Test EOD stop is allowed even when manual stops disabled."""
    config = StopConfig(enable_manual_stop=False)
    controller = StopController(config)

    controller.request_stop('end_of_day')  # EOD should always work

    assert controller.is_stop_requested()
    assert controller.get_stop_reason() == 'end_of_day'


def test_request_stop_idempotent(default_config):
    """Test multiple stop requests don't overwrite reason."""
    controller = StopController(default_config)

    controller.request_stop('first_reason')
    controller.request_stop('second_reason')  # Should be ignored

    assert controller.get_stop_reason() == 'first_reason'  # First reason preserved


# ==================== EOD Flatten Tests ====================


def test_check_eod_flatten_disabled(default_config):
    """Test EOD flatten returns False when disabled."""
    config = StopConfig(enable_eod_flatten=False)
    controller = StopController(config)

    current_time = datetime(2025, 1, 15, 19, 50, tzinfo=timezone.utc)  # 3:50 PM ET (after flatten time)

    assert not controller.check_eod_flatten(current_time)


def test_check_eod_flatten_before_time(default_config):
    """Test EOD flatten returns False before flatten time."""
    controller = StopController(default_config)

    # 3:00 PM ET = 20:00 UTC (before 3:45 PM flatten time)
    current_time = datetime(2025, 1, 15, 20, 0, tzinfo=timezone.utc)

    with patch('aistock.stop_control.nyse_trading_hours', return_value=(time(9, 30), time(16, 0))):
        assert not controller.check_eod_flatten(current_time)


def test_check_eod_flatten_after_time_regular_close(default_config):
    """Test EOD flatten triggers after flatten time on regular close day."""
    controller = StopController(default_config)

    # 3:50 PM ET = 20:50 UTC (after 3:45 PM flatten time)
    current_time = datetime(2025, 1, 15, 20, 50, tzinfo=timezone.utc)

    with patch('aistock.stop_control.nyse_trading_hours', return_value=(time(9, 30), time(16, 0))):
        assert controller.check_eod_flatten(current_time)


def test_check_eod_flatten_early_close_1pm(default_config):
    """Test EOD flatten handles early close at 1 PM correctly."""
    controller = StopController(default_config)

    # Config is 3:45 PM (15 min before regular 4 PM close)
    # On early close (1 PM), should flatten at 12:45 PM (15 min before 1 PM)
    # 12:50 PM ET = 17:50 UTC (after 12:45 PM flatten time)
    current_time = datetime(2025, 7, 3, 17, 50, tzinfo=timezone.utc)  # Day before July 4

    with patch('aistock.stop_control.nyse_trading_hours', return_value=(time(9, 30), time(13, 0))):  # 1 PM close
        assert controller.check_eod_flatten(current_time)


def test_check_eod_flatten_idempotent(default_config):
    """Test EOD flatten executes only once per day."""
    controller = StopController(default_config)

    current_time = datetime(2025, 1, 15, 20, 50, tzinfo=timezone.utc)

    with patch('aistock.stop_control.nyse_trading_hours', return_value=(time(9, 30), time(16, 0))):
        # First call should trigger
        assert controller.check_eod_flatten(current_time)

        # Second call should return False (already executed)
        assert not controller.check_eod_flatten(current_time)


def test_reset_eod_flatten(default_config):
    """Test reset_eod_flatten allows re-execution next day."""
    controller = StopController(default_config)

    current_time = datetime(2025, 1, 15, 20, 50, tzinfo=timezone.utc)

    with patch('aistock.stop_control.nyse_trading_hours', return_value=(time(9, 30), time(16, 0))):
        # Execute first time
        controller.check_eod_flatten(current_time)

        # Reset for new trading day
        controller.reset_eod_flatten()

        # Should now trigger again
        assert controller.check_eod_flatten(current_time)


def test_check_eod_flatten_naive_datetime_converted(default_config):
    """Test naive datetime is converted to UTC automatically."""
    controller = StopController(default_config)

    # Pass naive datetime (no timezone)
    current_time = datetime(2025, 1, 15, 15, 50)  # Naive (assumed ET time)

    with patch('aistock.stop_control.nyse_trading_hours', return_value=(time(9, 30), time(16, 0))):
        # Should handle gracefully and convert to UTC
        # Note: This tests defensive coding, but inputs SHOULD be timezone-aware
        result = controller.check_eod_flatten(current_time)
        # Result depends on conversion - just verify it doesn't crash
        assert isinstance(result, bool)


def test_check_eod_flatten_market_hours_exception(default_config):
    """Test EOD flatten handles nyse_trading_hours exception gracefully."""
    controller = StopController(default_config)

    current_time = datetime(2025, 1, 15, 20, 50, tzinfo=timezone.utc)

    with patch('aistock.stop_control.nyse_trading_hours', side_effect=ValueError('Invalid date')):
        # Should fall back to default 4 PM close
        assert controller.check_eod_flatten(current_time)


# ==================== Graceful Shutdown Tests ====================


def test_execute_graceful_shutdown_all_positions_close(mock_broker, mock_portfolio, default_config):
    """Test graceful shutdown when all positions close successfully."""
    controller = StopController(default_config)

    # Simulate positions closing immediately
    # Call sequence: submit_liquidation, monitor (initial), monitor (poll), check_remaining, final_check
    mock_portfolio.snapshot_positions.side_effect = [
        # submit_liquidation_orders (line 305)
        {
            'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
            'MSFT': Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300')),
        },
        # monitor_fills initial (line 346)
        {
            'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
            'MSFT': Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300')),
        },
        # monitor_fills poll 1 (line 350) - all closed
        {},
        # check_remaining after monitor (line 250)
        {},
        # final position check (line 266)
        {},
    ]

    last_prices = {'AAPL': Decimal('151.00'), 'MSFT': Decimal('302.00')}

    status = controller.execute_graceful_shutdown(mock_broker, mock_portfolio, last_prices)

    assert status['status'] == 'success'
    assert len(status['fully_closed']) == 2
    assert status['partially_closed'] == {}
    assert status['orders_cancelled'] == 5
    assert status['retry_attempts'] == 1


def test_execute_graceful_shutdown_no_positions(mock_broker, empty_portfolio, default_config):
    """Test graceful shutdown with no open positions."""
    controller = StopController(default_config)

    status = controller.execute_graceful_shutdown(mock_broker, empty_portfolio, {})

    assert status['status'] == 'success'
    assert status['fully_closed'] == []
    assert status['orders_cancelled'] == 5


def test_execute_graceful_shutdown_partial_close(mock_broker, mock_portfolio, default_config):
    """Test graceful shutdown when some positions remain open."""
    controller = StopController(default_config)

    # AAPL closes, MSFT remains
    # Need enough return values for: submit + (monitor initial + poll * N) * 3 retries + final check
    msft_open = {'MSFT': Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300'))}

    # Provide unlimited return values by using a generator function
    def position_generator():
        # Initial submit_liquidation
        yield {
            'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
            'MSFT': Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300')),
        }
        # All subsequent calls - MSFT remains open
        while True:
            yield msft_open.copy()

    mock_portfolio.snapshot_positions.side_effect = position_generator()

    last_prices = {'AAPL': Decimal('151.00'), 'MSFT': Decimal('302.00')}

    status = controller.execute_graceful_shutdown(mock_broker, mock_portfolio, last_prices)

    assert status['status'] == 'partial'  # Some closed
    assert status['partially_closed'] == {'MSFT': -50.0}
    assert status['retry_attempts'] == 3  # Max retries reached


def test_execute_graceful_shutdown_all_fail(mock_broker, mock_portfolio, default_config):
    """Test graceful shutdown when no positions close."""
    controller = StopController(default_config)

    # Positions never close
    mock_portfolio.snapshot_positions.return_value = {
        'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
        'MSFT': Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300')),
    }

    last_prices = {'AAPL': Decimal('151.00'), 'MSFT': Decimal('302.00')}

    status = controller.execute_graceful_shutdown(mock_broker, mock_portfolio, last_prices)

    assert status['status'] == 'failed'
    assert len(status['failed']) == 2
    assert status['retry_attempts'] == 3


def test_execute_graceful_shutdown_cancel_orders_exception(mock_broker, mock_portfolio, default_config):
    """Test graceful shutdown handles cancel_all_orders exception."""
    controller = StopController(default_config)

    mock_broker.cancel_all_orders.side_effect = RuntimeError('Broker disconnected')

    # Simulate positions closing despite cancel failure
    # submit_liquidation, monitor initial, monitor poll, check_remaining, final check
    mock_portfolio.snapshot_positions.side_effect = [
        {'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150'))},
        {'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150'))},
        {},  # monitor poll - closed
        {},  # check_remaining
        {},  # final check
    ]

    last_prices = {'AAPL': Decimal('151.00')}

    status = controller.execute_graceful_shutdown(mock_broker, mock_portfolio, last_prices)

    # Should still proceed with liquidation despite cancel failure
    assert status['status'] == 'success'
    assert status['orders_cancelled'] == 0  # Exception prevented cancellation


def test_execute_graceful_shutdown_submit_order_exception(mock_broker, mock_portfolio, default_config):
    """Test graceful shutdown handles order submission exception."""
    controller = StopController(default_config)

    mock_broker.submit.side_effect = RuntimeError('Order submission failed')

    # Positions don't close because orders never submitted
    mock_portfolio.snapshot_positions.return_value = {
        'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
    }

    last_prices = {'AAPL': Decimal('151.00')}

    status = controller.execute_graceful_shutdown(mock_broker, mock_portfolio, last_prices)

    # Should fail gracefully
    assert status['status'] == 'failed'
    assert 'AAPL' in status['failed']


def test_submit_liquidation_orders_long_position(mock_broker, default_config):
    """Test liquidation creates SELL order for long position."""
    controller = StopController(default_config)

    portfolio = MagicMock()
    portfolio.snapshot_positions.return_value = {
        'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
    }

    submitted = controller._submit_liquidation_orders(mock_broker, portfolio)

    assert submitted == ['AAPL']

    # Verify SELL order was submitted
    mock_broker.submit.assert_called_once()
    order_arg = mock_broker.submit.call_args[0][0]
    assert order_arg.symbol == 'AAPL'
    assert order_arg.side == OrderSide.SELL
    assert order_arg.quantity == Decimal('100')
    assert order_arg.order_type == OrderType.MARKET


def test_submit_liquidation_orders_short_position(mock_broker, default_config):
    """Test liquidation creates BUY order for short position."""
    controller = StopController(default_config)

    portfolio = MagicMock()
    portfolio.snapshot_positions.return_value = {
        'MSFT': Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300')),
    }

    submitted = controller._submit_liquidation_orders(mock_broker, portfolio)

    assert submitted == ['MSFT']

    # Verify BUY order was submitted
    mock_broker.submit.assert_called_once()
    order_arg = mock_broker.submit.call_args[0][0]
    assert order_arg.symbol == 'MSFT'
    assert order_arg.side == OrderSide.BUY
    assert order_arg.quantity == Decimal('50')  # Absolute value
    assert order_arg.order_type == OrderType.MARKET


def test_submit_liquidation_orders_skips_flat_positions(mock_broker, default_config):
    """Test liquidation skips positions with quantity near zero."""
    controller = StopController(default_config)

    portfolio = MagicMock()
    portfolio.snapshot_positions.return_value = {
        'FLAT': Position(symbol='FLAT', quantity=Decimal('0.005'), average_price=Decimal('100')),  # < 0.01
        'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
    }

    submitted = controller._submit_liquidation_orders(mock_broker, portfolio)

    assert submitted == ['AAPL']  # FLAT not submitted
    mock_broker.submit.assert_called_once()


def test_monitor_fills_all_close_quickly(mock_portfolio, default_config):
    """Test monitor_fills detects all positions closed."""
    controller = StopController(default_config)

    # Simulate positions closing after 2 polls
    mock_portfolio.snapshot_positions.side_effect = [
        # Initial
        {'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150'))},
        # Poll 1 - still open
        {'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150'))},
        # Poll 2 - closed
        {},
    ]

    closed = controller._monitor_fills(mock_portfolio, timeout=5.0, poll_interval=0.1)

    assert 'AAPL' in closed


def test_monitor_fills_timeout(mock_portfolio, default_config):
    """Test monitor_fills returns early on timeout."""
    controller = StopController(default_config)

    # Positions never close
    mock_portfolio.snapshot_positions.return_value = {
        'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
    }

    closed = controller._monitor_fills(mock_portfolio, timeout=0.5, poll_interval=0.1)

    assert closed == []  # Timeout reached, nothing closed


# ==================== create_liquidation_orders Function Tests ====================


def test_create_liquidation_orders_long_position():
    """Test create_liquidation_orders flips sign for long position."""
    portfolio = MagicMock()
    portfolio.snapshot_positions.return_value = {
        'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
    }

    orders = create_liquidation_orders(portfolio)

    assert orders == [('AAPL', Decimal('-100'))]  # Negative to close long


def test_create_liquidation_orders_short_position():
    """Test create_liquidation_orders flips sign for short position."""
    portfolio = MagicMock()
    portfolio.snapshot_positions.return_value = {
        'MSFT': Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300')),
    }

    orders = create_liquidation_orders(portfolio)

    assert orders == [('MSFT', Decimal('50'))]  # Positive to close short


def test_create_liquidation_orders_mixed_positions():
    """Test create_liquidation_orders handles multiple positions."""
    portfolio = MagicMock()
    portfolio.snapshot_positions.return_value = {
        'AAPL': Position(symbol='AAPL', quantity=Decimal('100'), average_price=Decimal('150')),
        'MSFT': Position(symbol='MSFT', quantity=Decimal('-50'), average_price=Decimal('300')),
        'FLAT': Position(symbol='FLAT', quantity=Decimal('0'), average_price=Decimal('100')),
    }

    orders = create_liquidation_orders(portfolio)

    assert len(orders) == 2  # FLAT skipped (qty == 0)
    assert ('AAPL', Decimal('-100')) in orders
    assert ('MSFT', Decimal('50')) in orders


def test_create_liquidation_orders_empty_portfolio():
    """Test create_liquidation_orders with no positions."""
    portfolio = MagicMock()
    portfolio.snapshot_positions.return_value = {}

    orders = create_liquidation_orders(portfolio)

    assert orders == []


# ==================== Thread Safety Tests ====================


def test_request_stop_thread_safe(default_config):
    """Test request_stop is thread-safe for concurrent access."""
    import threading

    controller = StopController(default_config)
    results = []

    def request_stop_worker(reason):
        controller.request_stop(reason)
        results.append(controller.get_stop_reason())

    threads = [threading.Thread(target=request_stop_worker, args=(f'reason_{i}',)) for i in range(10)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Should have set stop flag
    assert controller.is_stop_requested()

    # Reason should be from first thread to acquire lock
    assert controller.get_stop_reason().startswith('reason_')


def test_check_eod_flatten_thread_safe(default_config):
    """Test check_eod_flatten is thread-safe for concurrent access."""
    import threading

    controller = StopController(default_config)
    current_time = datetime(2025, 1, 15, 20, 50, tzinfo=timezone.utc)
    results = []

    def check_eod_worker():
        with patch('aistock.stop_control.nyse_trading_hours', return_value=(time(9, 30), time(16, 0))):
            result = controller.check_eod_flatten(current_time)
            results.append(result)

    threads = [threading.Thread(target=check_eod_worker) for _ in range(10)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one thread should have returned True (first to execute)
    assert results.count(True) == 1
    assert results.count(False) == 9
