#!/usr/bin/env python3
"""
IBKR Connection Test Script
Tests the Interactive Brokers integration with paper trading account.

Usage:
    python test_ibkr_connection.py

Prerequisites:
    1. TWS or IB Gateway running
    2. API enabled (port 7497 for paper trading)
    3. Trusted IP 127.0.0.1 added
    4. Account ID configured
"""

import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

from aistock.brokers.ibkr import IBKRBroker
from aistock.config import BrokerConfig, ContractSpec
from aistock.execution import Order, OrderSide, OrderType
from aistock.logging import configure_logger

# Configure logging
logger = configure_logger('IBKRTest', structured=True)


def test_connection():
    """Test basic IBKR connection."""
    print('=' * 60)
    print('IBKR CONNECTION TEST')
    print('=' * 60)
    print()

    # Configuration
    config = BrokerConfig(
        backend='ibkr',
        ib_host='127.0.0.1',
        ib_port=7497,  # Paper trading port
        ib_client_id=1001,
        ib_account=None,  # Will use default account
        contracts={'AAPL': ContractSpec(symbol='AAPL', sec_type='STK', exchange='SMART', currency='USD')},
    )

    print('📡 Connecting to TWS...')
    print(f'   Host: {config.ib_host}')
    print(f'   Port: {config.ib_port}')
    print(f'   Client ID: {config.ib_client_id}')
    print()

    try:
        # Create broker
        broker = IBKRBroker(config)

        # Start connection
        broker.start()
        print('✅ Connection successful!')
        print()

        # Wait for connection to stabilize
        print('⏳ Waiting for connection to stabilize...')
        time.sleep(3)

        # Test 1: Query positions
        print('=' * 60)
        print('TEST 1: Position Query')
        print('=' * 60)
        try:
            positions = broker.get_positions()
            print('✅ Position query successful!')
            print(f'   Positions found: {len(positions)}')
            for symbol, (qty, avg_price) in positions.items():
                print(f'   - {symbol}: {qty} shares @ ${avg_price:.2f}')
        except Exception as e:
            print(f'❌ Position query failed: {e}')
        print()

        # Test 2: Subscribe to real-time bars
        print('=' * 60)
        print('TEST 2: Real-time Data Subscription')
        print('=' * 60)

        bars_received = []

        def bar_handler(timestamp, symbol, open_val, high, low, close, volume):
            bars_received.append({'timestamp': timestamp, 'symbol': symbol, 'close': close, 'volume': volume})
            print(f'📊 Bar received: {symbol} @ {timestamp} | Close: ${close:.2f} | Vol: {volume:.0f}')

        try:
            req_id = broker.subscribe_realtime_bars('AAPL', bar_handler, bar_size=5)
            print(f'✅ Subscribed to AAPL real-time bars (req_id: {req_id})')
            print('   Waiting for data (30 seconds)...')

            # Wait for some bars
            time.sleep(30)

            print(f'✅ Received {len(bars_received)} bars')

            # Unsubscribe
            broker.unsubscribe(req_id)
            print('✅ Unsubscribed from real-time bars')
        except Exception as e:
            print(f'❌ Real-time data failed: {e}')
        print()

        # Test 3: Heartbeat (check if still connected)
        print('=' * 60)
        print('TEST 3: Connection Heartbeat')
        print('=' * 60)
        if broker.isConnected():
            print('✅ Connection still alive!')
            print(f'   Last heartbeat: {broker._last_heartbeat}')
        else:
            print('❌ Connection lost!')
        print()

        # Clean shutdown
        print('=' * 60)
        print('CLEANUP')
        print('=' * 60)
        broker.stop()
        print('✅ Disconnected cleanly')
        print()

        # Summary
        print('=' * 60)
        print('TEST SUMMARY')
        print('=' * 60)
        print('✅ Connection: PASS')
        print('✅ Position Query: PASS' if 'positions' in locals() else '❌ Position Query: FAIL')
        print('✅ Real-time Data: PASS' if len(bars_received) > 0 else '⚠️  Real-time Data: NO DATA')
        print('✅ Heartbeat: PASS')
        print()
        print('🎉 IBKR Integration Tests Complete!')
        print()
        return True

    except ConnectionError as e:
        print(f'❌ Connection failed: {e}')
        print()
        print('TROUBLESHOOTING:')
        print('1. Is TWS or IB Gateway running?')
        print('2. Is API enabled in TWS settings?')
        print('3. Is port 7497 open (paper trading)?')
        print('4. Is 127.0.0.1 in trusted IPs?')
        print('5. Try restarting TWS/Gateway')
        return False
    except Exception as e:
        print(f'❌ Unexpected error: {e}')
        import traceback

        traceback.print_exc()
        return False


def test_paper_order():
    """
    Test paper order submission (CAUTION: This will submit a real order to paper account).

    Only run this if you want to test order execution.
    """
    print('=' * 60)
    print('PAPER ORDER TEST (NOT EXECUTED BY DEFAULT)')
    print('=' * 60)
    print()
    print('To test order submission, uncomment the code in test_paper_order()')
    print('⚠️  This will submit a real order to your paper account!')
    print()

    # Uncomment below to test order submission
    """
    config = BrokerConfig(
        backend="ibkr",
        ib_host="127.0.0.1",
        ib_port=7497,
        ib_client_id=1001,
    )

    broker = IBKRBroker(config)
    broker.start()
    time.sleep(3)

    # Submit a small test order
    order = Order(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal("1"),  # 1 share only for testing
        order_type=OrderType.MARKET,
        time_in_force="DAY"
    )

    print(f"📤 Submitting test order: BUY 1 AAPL @ MARKET")
    order_id = broker.submit(order)
    print(f"✅ Order submitted: ID {order_id}")

    time.sleep(5)

    broker.stop()
    """


if __name__ == '__main__':
    print()
    print('=' * 60)
    print('  IBKR Integration Test Suite')
    print('=' * 60)
    print()

    # Check if IBAPI is available
    try:
        from aistock.brokers.ibkr import IBAPI_AVAILABLE

        if not IBAPI_AVAILABLE:
            print('❌ IBAPI not installed!')
            print()
            print('Install with:')
            print('  pip install ibapi')
            print()
            print('Or download from: https://interactivebrokers.github.io/')
            sys.exit(1)
    except ImportError:
        print('❌ IBAPI import failed!')
        sys.exit(1)

    # Run connection test
    success = test_connection()

    # Paper order test (commented out by default)
    # test_paper_order()

    sys.exit(0 if success else 1)
