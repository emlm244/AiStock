# tests/test_aggregator.py
"""Tests for data aggregation (tick to bar conversion)."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import queue
import time
import threading
from unittest.mock import Mock, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aggregator.data_aggregator import DataAggregator


@pytest.fixture
def mock_api():
    """Create a mock API with a live ticks queue."""
    api = Mock()
    api.live_ticks_queue = queue.Queue()
    return api


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    return Mock()


@pytest.fixture
def aggregator(mock_api, mock_logger):
    """Create a DataAggregator instance."""
    bar_size = timedelta(seconds=30)
    return DataAggregator(mock_api, bar_size, mock_logger)


def test_aggregator_initialization(aggregator):
    """Test aggregator initializes with correct state."""
    assert aggregator.bar_size == timedelta(seconds=30)
    assert aggregator.running == False
    assert len(aggregator.subscribed_symbols) == 0


def test_subscribe_symbols(aggregator):
    """Test subscribing to symbols creates bar queues."""
    symbols = ['BTC/USD', 'ETH/USD']
    aggregator.subscribe_symbols(symbols)

    assert 'BTC/USD' in aggregator.subscribed_symbols
    assert 'ETH/USD' in aggregator.subscribed_symbols
    assert 'BTC/USD' in aggregator.bar_queues
    assert 'ETH/USD' in aggregator.bar_queues


def test_bar_size_validation():
    """Test that invalid bar sizes raise errors."""
    api = Mock()
    logger = Mock()

    with pytest.raises(ValueError, match="Bar size must be a positive timedelta"):
        DataAggregator(api, timedelta(seconds=-1), logger)

    with pytest.raises(ValueError, match="Bar size must be a positive timedelta"):
        DataAggregator(api, timedelta(seconds=0), logger)


def test_bar_completion_edge_case():
    """Test bar completion at exact boundary times."""
    api = Mock()
    api.live_ticks_queue = queue.Queue()
    logger = Mock()
    aggregator = DataAggregator(api, timedelta(minutes=1), logger)
    aggregator.subscribe_symbols(['TEST'])

    # Create ticks at exact minute boundaries
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=pytz.utc)

    ticks = [
        {'symbol': 'TEST', 'time_utc': base_time, 'price': 100.0, 'size': 10, 'tick_type': 'LAST'},
        {'symbol': 'TEST', 'time_utc': base_time + timedelta(seconds=30), 'price': 101.0, 'size': 20, 'tick_type': 'LAST'},
        {'symbol': 'TEST', 'time_utc': base_time + timedelta(minutes=1), 'price': 102.0, 'size': 15, 'tick_type': 'LAST'},  # New bar
    ]

    for tick in ticks:
        api.live_ticks_queue.put(tick)

    # Stop after processing
    api.live_ticks_queue.put(None)

    # Process ticks
    aggregator._aggregation_loop()

    # Check that a bar was completed
    bar_queue = aggregator.get_bar_queue('TEST')
    assert bar_queue is not None
    assert not bar_queue.empty()

    completed_bar = bar_queue.get()
    assert isinstance(completed_bar, pd.DataFrame)
    assert len(completed_bar) == 1
    assert completed_bar['close'].iloc[0] == 101.0  # Last price before bar close


def test_missing_tick_data():
    """Test handling of ticks with missing fields."""
    api = Mock()
    api.live_ticks_queue = queue.Queue()
    logger = Mock()
    aggregator = DataAggregator(api, timedelta(seconds=30), logger)
    aggregator.subscribe_symbols(['TEST'])

    # Tick missing price
    bad_tick = {'symbol': 'TEST', 'time_utc': datetime.now(pytz.utc), 'size': 10, 'tick_type': 'LAST'}
    api.live_ticks_queue.put(bad_tick)
    api.live_ticks_queue.put(None)  # Stop signal

    # Should handle gracefully without crashing
    aggregator._aggregation_loop()

    # Logger should have recorded an error
    assert logger.error.called or logger.warning.called


def test_concurrent_symbol_subscription():
    """Test thread safety when subscribing multiple symbols."""
    api = Mock()
    api.live_ticks_queue = queue.Queue()
    logger = Mock()
    aggregator = DataAggregator(api, timedelta(seconds=30), logger)

    symbols = [f'SYM{i}' for i in range(10)]

    # Subscribe in multiple threads
    threads = []
    for symbol in symbols:
        t = threading.Thread(target=aggregator.subscribe_symbols, args=([symbol],))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All symbols should be subscribed
    assert len(aggregator.subscribed_symbols) == len(symbols)
    for symbol in symbols:
        assert symbol in aggregator.subscribed_symbols
