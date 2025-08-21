# aggregator/data_aggregator.py

import threading
import queue
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time
import pytz # Import pytz

# Removed TickTypeEnum import as types are passed directly

class DataAggregator:
    """
    Aggregates real-time ticks (with UTC timestamps) from the API's queue
    into time-based bars (candles) with UTC timestamps.
    Pushes completed bars as DataFrames to symbol-specific queues.
    Logs errors and continues operation instead of halting.
    """

    def __init__(self, api, bar_size_timedelta, logger, error_callback=None):
        """
        Args:
            api: IBKRApi instance providing live_ticks_queue with UTC timestamps.
            bar_size_timedelta: timedelta object representing bar duration.
            logger: Logger instance.
            error_callback (Optional): Function to call on significant errors (though it no longer stops).
        """
        self.api = api # IBKRApi instance
        self.bar_size = bar_size_timedelta
        if self.bar_size.total_seconds() <= 0:
             raise ValueError("Bar size must be a positive timedelta.")

        self.logger = logger
        # Use main logger for errors unless a specific one is needed
        self.error_logger = logger # setup_logger('AggregatorError', 'logs/error_logs/errors.log', level='ERROR')

        # --- State (Protected by _subscribe_lock) ---
        # Queues for completed bars {symbol: Queue[pd.DataFrame]}
        self.bar_queues = {}
        # Internal state for building bars {symbol: current_bar_dict_with_utc_timestamp}
        self.current_bars = {}
        # {symbol: last_utc_tick_timestamp_processed}
        self.last_tick_time = {}
        self.subscribed_symbols = set()
        # --- End State ---

        self._subscribe_lock = threading.Lock() # Lock for accessing shared state

        self.running = False
        self.thread = None
        self.error_count = 0 # Track consecutive errors (can be used for logging frequency)
        # self.max_errors = max_errors # No longer using max_errors to halt
        self.error_callback = error_callback # Callback still useful for reporting issues

    def subscribe_symbols(self, symbols):
        """ Prepares aggregator for symbols. Starts thread if needed (thread-safe). """
        with self._subscribe_lock:
            newly_subscribed = False
            for symbol in symbols:
                if symbol not in self.subscribed_symbols:
                    self.bar_queues[symbol] = queue.Queue(maxsize=1000) # Add maxsize to prevent memory leak
                    self.current_bars[symbol] = None
                    self.last_tick_time[symbol] = None
                    self.subscribed_symbols.add(symbol)
                    self.logger.info(f"DataAggregator subscribed to symbol: {symbol}")
                    newly_subscribed = True

            # Start thread only if running flag is false AND we have subscriptions
            if not self.running and self.subscribed_symbols:
                self.running = True
                self.thread = threading.Thread(target=self._aggregation_loop, name="DataAggregatorLoop", daemon=True)
                self.thread.start()
                self.logger.info("Data Aggregator thread started.")
            elif newly_subscribed:
                 self.logger.info(f"Aggregator already running. Added symbols: {symbols}")


    def _aggregation_loop(self):
        """ Main loop getting ticks (UTC) and aggregating them. Logs errors and continues. """
        self.logger.info("Data Aggregation loop entering...")
        error_streak = 0 # Track consecutive errors for logging modulation

        while self.running:
            try:
                # Timeout allows checking for time-based finalization and shutdown signal
                tick_data = self.api.live_ticks_queue.get(timeout=0.2) # Shorter timeout?
                # Expected format: (symbol, tickType (int), price (float/None), size (float/None), timestamp_utc (aware datetime))

                symbol, tick_type, price, size, timestamp_utc = tick_data

                # --- Timestamp Validation ---
                if not isinstance(timestamp_utc, datetime) or timestamp_utc.tzinfo is None:
                     self.error_logger.warning(f"Aggregator received tick for {symbol} with invalid/naive timestamp: {timestamp_utc}. Using current UTC time.")
                     timestamp_utc = datetime.now(pytz.utc) # Use current time as fallback
                elif timestamp_utc.tzinfo != pytz.utc:
                     timestamp_utc = timestamp_utc.astimezone(pytz.utc) # Ensure UTC

                # Process tick if symbol is subscribed
                if symbol in self.subscribed_symbols:
                    self._process_tick(symbol, tick_type, price, size, timestamp_utc)

                # Reset error streak on successful processing
                error_streak = 0

            except queue.Empty:
                # No tick received, check for time-based finalization
                self._check_time_based_finalization()
                continue # Continue loop
            except Exception as e:
                self.error_logger.error(f"Error in Data Aggregator loop: {e}", exc_info=True)
                error_streak += 1
                # Log frequently at first, then less often if errors persist
                if error_streak < 5 or error_streak % 60 == 0: # Log first 5 errors, then once per minute approx
                    self.logger.warning(f"Data Aggregator error streak: {error_streak}")

                # Call error callback if provided (without stopping the aggregator)
                if callable(self.error_callback):
                    try: self.error_callback(f"Aggregator error: {e}")
                    except Exception as cb_e: self.error_logger.error(f"Error calling aggregator error callback: {cb_e}", exc_info=True)

                time.sleep(1) # Small sleep after error to prevent tight error loops

        self.logger.warning("Data Aggregation loop finished.")


    def _process_tick(self, symbol, tick_type, price, size, timestamp_utc):
        """ Processes a single tick (with aware UTC time) to update the bar state. """
        # Tick types: 1=BID, 2=ASK, 4=LAST, 5=LAST_SIZE, 8=VOLUME, 9=CLOSE etc.
        # Primarily use LAST price (4) and LAST size (5) for OHLCV bars
        is_price_update_tick = tick_type in [1, 2, 4, 9] and price is not None and price > 0
        is_volume_update_tick = tick_type == 5 and size is not None and size >= 0 # Use LAST_SIZE for volume

        # Get price to use for OHLC updates (prefer LAST, fallback to CLOSE, BID, ASK?)
        ohlc_price = None
        if tick_type == 4: ohlc_price = price # Use LAST price for OHLC
        # Could add logic here: if tick_type == 9 and last_price_update was long ago, use CLOSE?

        if not is_price_update_tick and not is_volume_update_tick:
             # self.logger.debug(f"Ignoring tick type {tick_type} for {symbol}")
             return

        # Acquire lock to modify shared state (current_bars, last_tick_time)
        with self._subscribe_lock:
            current_bar = self.current_bars.get(symbol)
            last_processed_time = self.last_tick_time.get(symbol)

            # --- Prevent processing out-of-order ticks ---
            # Allow processing ticks within the same second, but not older ones
            if last_processed_time is not None and timestamp_utc < last_processed_time:
                self.logger.warning(f"Ignoring out-of-order tick for {symbol}: Tick time {timestamp_utc} < Last processed {last_processed_time}")
                return

            # Quantize current tick timestamp to its bar start time (in UTC)
            try:
                bar_start_time_utc = self._calculate_bar_start_time(timestamp_utc)
            except ValueError as ve:
                 self.error_logger.error(f"Cannot process tick for {symbol}: {ve}")
                 return

            # --- Bar Logic ---
            if current_bar is None:
                # Start first bar ONLY if we have a valid OHLC price
                if ohlc_price is not None:
                    self._start_new_bar(symbol, ohlc_price, size if is_volume_update_tick else 0.0, bar_start_time_utc)
                # Else: Ignore volume-only tick if no bar exists yet
            else:
                # Get the start time of the currently open bar
                current_bar_start_utc = current_bar['timestamp']

                if bar_start_time_utc > current_bar_start_utc:
                    # Tick belongs to a *new* bar interval. Finalize the old one.
                    self._finalize_bar(symbol)
                    # Start the new bar using the current tick's data
                    self._start_new_bar(symbol, ohlc_price, size if is_volume_update_tick else 0.0, bar_start_time_utc)

                elif bar_start_time_utc == current_bar_start_utc:
                    # Tick belongs to the current bar. Update it.
                    self._update_bar(symbol, ohlc_price, size if is_volume_update_tick else None, timestamp_utc)
                # Else: bar_start_time_utc < current_bar_start_utc (late tick already handled above)

            # Update the last tick time processed for this symbol (always UTC)
            self.last_tick_time[symbol] = timestamp_utc
        # Lock released


    def _check_time_based_finalization(self):
         """ Checks if current bars should be finalized based on wall clock UTC time. """
         now_utc = datetime.now(pytz.utc)
         # Acquire lock to safely iterate and modify current_bars
         with self._subscribe_lock:
             symbols_to_check = list(self.current_bars.keys()) # Check all symbols with potentially open bars

             for symbol in symbols_to_check:
                 current_bar = self.current_bars.get(symbol)
                 if current_bar:
                     bar_start_time_utc = current_bar['timestamp']
                     # Calculate expected end time in UTC (exclusive)
                     bar_end_time_utc = bar_start_time_utc + self.bar_size

                     # If current time is >= the expected end time, finalize the bar
                     if now_utc >= bar_end_time_utc:
                         self.logger.debug(f"Time-based finalization for {symbol} bar starting {bar_start_time_utc}")
                         # The 'close' price is the last price recorded within _update_bar
                         # No price update needed here unless filling forward missing bars.
                         self._finalize_bar(symbol) # Finalizes and sets current_bars[symbol] to None


    def _calculate_bar_start_time(self, timestamp_utc):
        """ Calculates the quantized UTC start time for the bar containing the timestamp. """
        # Ensure input is aware UTC (already checked in _process_tick)
        total_seconds_epoch = timestamp_utc.timestamp()
        bar_interval_seconds = self.bar_size.total_seconds()
        if bar_interval_seconds <= 0: # Should be caught in init
            raise ValueError("Internal Error: Bar size is zero or negative.")

        # Floor division to find the start of the interval
        quantized_seconds_epoch = (total_seconds_epoch // bar_interval_seconds) * bar_interval_seconds
        # Return as aware UTC datetime
        return datetime.fromtimestamp(quantized_seconds_epoch, tz=timezone.utc)


    def _start_new_bar(self, symbol, price, volume, bar_start_time_utc):
        """ Initializes a new bar dictionary with UTC timestamp (MUST be called within lock). """
        # Price is required to start a bar in this logic
        if price is None:
            self.logger.debug(f"Cannot start bar for {symbol} at {bar_start_time_utc}: Price is None.")
            return

        self.current_bars[symbol] = {
            'timestamp': bar_start_time_utc, # Aware UTC timestamp
            'open': price,
            'high': price,
            'low': price,
            'close': price,
            'volume': float(volume) if volume is not None else 0.0 # Ensure volume is float
        }
        self.logger.debug(f"Started new UTC bar for {symbol} at {bar_start_time_utc}, Open={price:.5f}")


    def _update_bar(self, symbol, price, size, timestamp_utc):
        """ Updates the current bar with price/size tick data (MUST be called within lock). """
        bar = self.current_bars.get(symbol)
        if not bar: return # Should not happen if called correctly

        # Update OHLC only if a valid price is provided for this tick
        if price is not None:
             bar['high'] = max(bar['high'], price)
             bar['low'] = min(bar['low'], price)
             bar['close'] = price # Update close with the latest valid price

        # Accumulate volume from 'Last Size' ticks
        if size is not None:
             bar['volume'] += float(size) # Ensure float addition


    def _finalize_bar(self, symbol):
        """ Pushes the completed bar to the queue (MUST be called within lock). """
        if symbol not in self.current_bars or self.current_bars[symbol] is None: return

        finished_bar = self.current_bars[symbol].copy()
        # Create DataFrame with the single finished bar row
        bar_df = pd.DataFrame([finished_bar])
        bar_df = bar_df.set_index('timestamp') # Set the timestamp as index

        # Ensure correct dtypes (should be okay, but belt-and-suspenders)
        try:
             for col in ['open', 'high', 'low', 'close', 'volume']:
                 bar_df[col] = pd.to_numeric(bar_df[col])
        except Exception as type_e:
             self.error_logger.error(f"Error converting bar data types for {symbol}: {type_e}")
             # Don't push bar if types are wrong? Or try anyway? Let's skip.
             self.current_bars[symbol] = None # Reset even on error
             return

        try:
            # Check queue size before putting to avoid blocking indefinitely if consumer stuck
            q = self.bar_queues.get(symbol)
            if q:
                 if q.full():
                      self.logger.warning(f"Bar queue for {symbol} is full! Discarding oldest bar.")
                      try: q.get_nowait() # Remove oldest item
                      except queue.Empty: pass # Ignore if became empty concurrently
                 q.put(bar_df) # Put the new bar DataFrame
                 ts_str = finished_bar['timestamp'].strftime(self.settings.LOG_TIMESTAMP_FORMAT)
                 self.logger.info(f"Finalized UTC bar for {symbol}: {ts_str} O={finished_bar['open']:.5f} H={finished_bar['high']:.5f} L={finished_bar['low']:.5f} C={finished_bar['close']:.5f} V={finished_bar['volume']:.2f}")
            else:
                 self.logger.error(f"Cannot finalize bar for {symbol}: Queue not found.")

        except Exception as e:
            self.error_logger.error(f"Error putting bar onto queue for {symbol}: {e}", exc_info=True)

        finally:
            # Always reset the current bar for the symbol after attempting finalization
            self.current_bars[symbol] = None


    def stop(self):
        """ Stops the aggregator thread gracefully. """
        if not self.running: return
        self.logger.info("Stopping Data Aggregator...")
        self.running = False # Signal loop to exit
        if self.thread and self.thread.is_alive():
            self.logger.info("Waiting for Data Aggregator thread to join...")
            self.thread.join(timeout=5) # Wait up to 5 seconds
            if self.thread.is_alive(): self.logger.warning("Data Aggregator thread did not join cleanly.")
            else: self.logger.info("Data Aggregator thread joined.")
        self.thread = None
        self.logger.info("Data Aggregator stopped.")


    def get_bar_queue(self, symbol):
        """ Returns the queue for a specific symbol (thread-safe). """
        with self._subscribe_lock: # Protect access to bar_queues dict
            return self.bar_queues.get(symbol)