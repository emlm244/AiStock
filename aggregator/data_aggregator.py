import threading
import queue
import pandas as pd
import numpy as np
from datetime import datetime

class DataAggregator:
    """
    DataAggregator will:
    1. Continuously read ticks (price, size, etc.) from IBKRApi's live_ticks_queue.
    2. Build/finalize bars (candles) based on bar_size intervals.
    3. Push the completed bars into a thread-safe queue (bar_queues) for consumption by the main trading loop.
    """

    def __init__(self, api, bar_size, logger, max_errors=5, error_callback=None):
        """
        :param api: IBKRApi instance or any data source that provides live_ticks_queue
        :param bar_size: Timedelta representing bar size (e.g., timedelta(minutes=1))
        :param logger: Logger instance
        :param max_errors: Maximum number of aggregator errors before aggregator stops/shuts down.
        :param error_callback: Callable to notify the main bot of repeated aggregator errors.
        """
        self.api = api
        self.bar_size = bar_size
        self.logger = logger

        # One queue per symbol for completed bars
        self.bar_queues = {}

        # Track the "in-progress" bar for each symbol
        self.current_bars = {}
        self.last_bar_timestamp = {}

        # Thread control
        self.running = False
        self.thread = None

        # Error handling
        self.error_count = 0
        self.max_errors = max_errors
        self.error_callback = error_callback  # e.g. a method in TradingBot to handle aggregator crash

    def subscribe_symbols(self, symbols):
        """
        1. Create a bar queue for each symbol.
        2. Instruct IBKRApi to subscribe real-time data for each symbol (if not already done).
        3. Start the aggregator thread (if not already running).
        """
        for symbol in symbols:
            self.bar_queues[symbol] = queue.Queue()
            self.api.subscribe_market_data(symbol)  # Subscribes via IBKRApi
            self.current_bars[symbol] = None
            self.last_bar_timestamp[symbol] = None

        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._build_bars_loop, daemon=True)
            self.thread.start()

    def _build_bars_loop(self):
        """
        Main aggregator loop:
        1. Grab the next tick from IBKRApi's live_ticks_queue.
        2. Update or finalize bars based on self.bar_size.
        3. Push completed bars to self.bar_queues for each symbol.
        """
        while self.running:
            try:
                # This blocks until a new tick is available or times out
                tick_data = self.api.live_ticks_queue.get(timeout=1)
                # tick_data format: (symbol, tickType, price, size, timestamp)
                symbol, _, price, size, timestamp = tick_data

                if symbol not in self.current_bars:
                    # Symbol may have been unsubscribed or not properly initialized
                    continue

                if self.current_bars[symbol] is None:
                    self._start_new_bar(symbol, price, size, timestamp)
                else:
                    delta = timestamp - self.last_bar_timestamp[symbol]
                    if delta >= self.bar_size:
                        # Finalize current bar and push into bar_queues
                        finished_bar = self.current_bars[symbol]
                        bar_df = pd.DataFrame([finished_bar])
                        self.bar_queues[symbol].put(bar_df)

                        # Start a new bar
                        self._start_new_bar(symbol, price, size, timestamp)
                    else:
                        # Update the in-progress bar
                        self._update_bar(symbol, price, size, timestamp)

                # Reset error count upon success
                self.error_count = 0

            except queue.Empty:
                # No new tick after 1 second, just continue
                continue
            except Exception as e:
                self.logger.error(f"Error in aggregator loop: {e}", exc_info=True)
                self.error_count += 1
                if self.error_count >= self.max_errors:
                    self.logger.error(
                        f"DataAggregator hit {self.error_count} errors. Triggering error_callback."
                    )
                    self.running = False
                    if callable(self.error_callback):
                        self.error_callback()
                    break

    def _start_new_bar(self, symbol, price, size, timestamp):
        self.last_bar_timestamp[symbol] = timestamp
        self.current_bars[symbol] = {
            'timestamp': timestamp,
            'open': price,
            'high': price,
            'low': price,
            'close': price,
            'volume': size if size else 0
        }
        self.logger.debug(f"Started new bar for {symbol} at {timestamp}, open={price}")

    def _update_bar(self, symbol, price, size, timestamp):
        bar = self.current_bars[symbol]

        if price is not None:
            bar['high'] = max(bar['high'], price)
            bar['low'] = min(bar['low'], price)
            bar['close'] = price

        if size is not None:
            bar['volume'] += size

    def stop(self):
        """Stop the aggregator thread gracefully."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join()

    def get_bar_queue(self, symbol):
        """Return the queue for a specific symbol so the main loop can read completed bars."""
        return self.bar_queues.get(symbol)

    def feed_mock_ticks(self, tick_list):
        """
        Feeds a list of mock ticks into the aggregator loop for simulation.
        Each tick in tick_list: (symbol, tickType, price, size, timestamp)
        """
        for tick in tick_list:
            self.api.live_ticks_queue.put(tick)
