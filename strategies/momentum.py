# strategies/momentum.py
import sys
import os
# Ensure correct path (though main.py should handle this)
# parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if parent_dir not in sys.path:
#     sys.path.append(parent_dir)

import numpy as np
import pandas as pd

try:
    from utils.logger import setup_logger
    from config.settings import Settings
except ImportError as e:
    print(f"Error importing modules in MomentumStrategy: {e}")
    raise


class MomentumStrategy:
    def __init__(self):
        # Keep settings instance to read parameters dynamically
        self.settings = Settings()
        self.logger = setup_logger(
            'Momentum', 'logs/strategies.log', level=self.settings.LOG_LEVEL
        )
        # Store initial period for min_data_points calculation
        try:
            self._initial_price_change_period = self.settings.MOMENTUM_PRICE_CHANGE_PERIOD
            if not isinstance(self._initial_price_change_period, int) or self._initial_price_change_period <= 0:
                 self.logger.warning(f"Initial MOMENTUM_PRICE_CHANGE_PERIOD ({self._initial_price_change_period}) invalid. Using default 5 for min_data_points.")
                 self._initial_price_change_period = 5
        except AttributeError:
             self.logger.error("MOMENTUM_PRICE_CHANGE_PERIOD not found in settings. Using default 5 for min_data_points.")
             self._initial_price_change_period = 5


    def generate_signal(self, data):
        """Generates +1 (buy), -1 (sell), or 0 (hold) signal based on price and volume momentum."""
        try:
            # Read parameters dynamically from settings each time
            price_change_period = self.settings.MOMENTUM_PRICE_CHANGE_PERIOD
            price_change_threshold = self.settings.MOMENTUM_PRICE_CHANGE_THRESHOLD
            volume_multiplier = self.settings.MOMENTUM_VOLUME_MULTIPLIER

            # --- Input Validation ---
            if not isinstance(price_change_period, int) or price_change_period <= 0:
                 self.logger.error(f"Invalid momentum period: {price_change_period}. No signal.")
                 return 0
            if not isinstance(price_change_threshold, (int, float)) or price_change_threshold <= 0:
                 self.logger.error(f"Invalid momentum threshold: {price_change_threshold}. No signal.")
                 return 0
            if not isinstance(volume_multiplier, (int, float)) or volume_multiplier <= 0:
                 self.logger.error(f"Invalid momentum volume multiplier: {volume_multiplier}. No signal.")
                 return 0

            required_data = self.min_data_points(current_period=price_change_period)
            if data is None or len(data) < required_data:
                # self.logger.debug(f"Not enough data ({len(data) if data is not None else 0}/{required_data}) for Momentum({price_change_period}).")
                return 0 # Not enough data

            # Ensure data has 'close' and 'volume' columns
            if 'close' not in data.columns or 'volume' not in data.columns:
                self.logger.error("MomentumStrategy requires 'close' and 'volume' columns. No signal.")
                return 0

            # --- Calculate Indicators ---
            # Calculate percentage price change over the period
            data['price_change'] = data['close'].pct_change(periods=price_change_period)

            # Calculate average volume over the same period (excluding the current bar for comparison)
            # Ensure rolling window size matches price change period
            rolling_volume = data['volume'].rolling(window=price_change_period, min_periods=price_change_period)
            data['avg_volume'] = rolling_volume.mean().shift(1) # Shift to exclude current bar

            # --- Get Latest Values & Check NaNs ---
            latest_data = data.iloc[-1] # Access last row

            # Check for NaNs in the latest calculated values
            if latest_data[['price_change', 'volume', 'avg_volume']].isnull().any():
                 self.logger.warning("NaN values encountered in latest data for Momentum check (PriceChg/Vol/AvgVol). No signal.")
                 return 0

            latest_price_change = latest_data['price_change']
            latest_volume = latest_data['volume']
            latest_avg_volume = latest_data['avg_volume']

            # Log intermediate values for debugging
            self.logger.debug(
                 f"Momentum Check: Price Change({price_change_period}p): {latest_price_change:.4f}, "
                 f"Threshold: {price_change_threshold:.4f}, Vol: {latest_volume:.0f}, "
                 f"Avg Vol: {latest_avg_volume:.2f}, Vol Mult: {volume_multiplier:.1f}"
            )

            # --- Signal Logic ---
            # Check volume condition (handle potential zero avg_volume)
            volume_condition_met = False
            if latest_avg_volume > 1e-9: # Avoid division by zero or comparing against tiny volume
                 volume_condition_met = latest_volume > (latest_avg_volume * volume_multiplier)
            elif latest_volume > 0: # If avg volume is zero/tiny, require *any* volume? Or specific threshold?
                 # Let's require volume > 0 if avg is zero/tiny
                 volume_condition_met = True

            # Generate signal based on price change threshold AND volume confirmation
            if latest_price_change >= price_change_threshold and volume_condition_met:
                # self.logger.info("Positive momentum detected - Buy signal generated.")
                return 1  # Buy signal
            elif latest_price_change <= -price_change_threshold and volume_condition_met:
                # self.logger.info("Negative momentum detected - Sell signal generated.")
                return -1  # Sell signal
            else:
                # No significant momentum or volume confirmation failed
                # self.logger.debug("No significant momentum detected or volume condition not met.")
                return 0  # No signal

        except AttributeError as e:
             self.logger.error(f"Missing attribute in settings (e.g., MOMENTUM_...): {e}. No signal.")
             return 0
        except Exception as e:
            self.logger.error(f"Error in MomentumStrategy.generate_signal: {e}", exc_info=True)
            return 0  # Fail safe to no signal

    def min_data_points(self, current_period=None):
        """Minimum data points required based on the momentum period."""
        # Need period for pct_change + period for rolling volume mean + 1 for shift
        period = current_period if current_period is not None else self._initial_price_change_period
        # Ensure period is valid integer > 0
        period = max(1, int(period)) if isinstance(period, (int, float)) else 1
        return period + 1 # Need 'period' prior bars for pct_change, and 1 more for rolling avg shift
