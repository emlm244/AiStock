# strategies/trend_following.py
import sys
import os
# Ensure correct path (though main.py should handle this)
# parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if parent_dir not in sys.path:
#     sys.path.append(parent_dir)

import numpy as np
import pandas as pd

try:
    from indicators.moving_averages import calculate_sma
    from utils.logger import setup_logger
    from config.settings import Settings
except ImportError as e:
    print(f"Error importing modules in TrendFollowingStrategy: {e}")
    raise

class TrendFollowingStrategy:
    def __init__(self):
        # Keep settings instance to read parameters dynamically
        self.settings = Settings()
        self.logger = setup_logger(
            'TrendFollowing', 'logs/strategies.log', level=self.settings.LOG_LEVEL
        )
        # Store the required periods based on initial settings for min_data_points
        # This assumes the optimizer won't increase periods beyond a reasonable initial range
        try:
            self._initial_short_period = self.settings.MOVING_AVERAGE_PERIODS['short_term']
            self._initial_long_period = self.settings.MOVING_AVERAGE_PERIODS['long_term']
            if self._initial_short_period >= self._initial_long_period:
                 self.logger.warning(f"Initial MA config invalid: short ({self._initial_short_period}) >= long ({self._initial_long_period}). Using defaults 9/21 for min_data_points.")
                 self._initial_short_period = 9
                 self._initial_long_period = 21
        except (KeyError, TypeError) as e:
             self.logger.error(f"Could not read initial MA periods from settings: {e}. Using defaults 9/21 for min_data_points.")
             self._initial_short_period = 9
             self._initial_long_period = 21


    def generate_signal(self, data):
        """Generates +1 (buy), -1 (sell), or 0 (hold) signal based on MA crossover."""
        try:
            # Read moving average periods dynamically from settings each time
            # This allows the optimizer (or manual changes to settings) to take effect
            short_term_period = self.settings.MOVING_AVERAGE_PERIODS['short_term']
            long_term_period = self.settings.MOVING_AVERAGE_PERIODS['long_term']

            # --- Input Validation ---
            if not isinstance(short_term_period, int) or not isinstance(long_term_period, int) or short_term_period <= 0 or long_term_period <= 0:
                 self.logger.error(f"Invalid MA periods in settings: short={short_term_period}, long={long_term_period}. No signal.")
                 return 0
            if short_term_period >= long_term_period:
                 self.logger.error(f"Short MA period ({short_term_period}) must be less than Long MA period ({long_term_period}). No signal.")
                 return 0

            required_data = max(short_term_period, long_term_period)
            if data is None or len(data) < required_data:
                # Use debug level as this happens normally at startup
                # self.logger.debug(f"Not enough data ({len(data) if data is not None else 0}/{required_data}) for MAs ({short_term_period}, {long_term_period}).")
                return 0 # Not enough data

            # --- Calculate Indicators ---
            # Use calculate_sma which handles insufficient data internally by returning NaNs
            data['short_ma'] = calculate_sma(data, short_term_period)
            data['long_ma'] = calculate_sma(data, long_term_period)

            # --- Get Latest Values & Check for NaNs ---
            # Accessing .iloc[-1] is safe as we checked len(data) >= required_data
            latest_short_ma = data['short_ma'].iloc[-1]
            latest_long_ma = data['long_ma'].iloc[-1]

            # Check if calculation resulted in NaN (shouldn't if len check is correct and data clean)
            if pd.isna(latest_short_ma) or pd.isna(latest_long_ma):
                 self.logger.warning(f"NaN value encountered in calculated moving averages (Short: {latest_short_ma}, Long: {latest_long_ma}). Check data quality. No signal.")
                 return 0

            # Log the latest moving average values for debugging
            self.logger.debug(f"Trend Check: Short MA({short_term_period})={latest_short_ma:.5f}, Long MA({long_term_period})={latest_long_ma:.5f}")

            # --- Signal Logic ---
            # Simple state-based signal: Buy if short > long, Sell if short < long
            # Use numpy.isclose for robust float comparison
            if latest_short_ma > latest_long_ma and not np.isclose(latest_short_ma, latest_long_ma):
                # self.logger.info("Short MA > Long MA - Buy signal generated.")
                return 1  # Buy signal state
            elif latest_short_ma < latest_long_ma and not np.isclose(latest_short_ma, latest_long_ma):
                # self.logger.info("Short MA < Long MA - Sell signal generated.")
                return -1  # Sell signal state
            else:
                # MAs are equal or very close - No signal / stay neutral
                # self.logger.debug("MAs are equal or crossing - No signal.")
                return 0  # No signal state

        except KeyError as e:
             self.logger.error(f"Missing key in settings.MOVING_AVERAGE_PERIODS: {e}. No signal.")
             return 0
        except Exception as e:
            self.logger.error(f"Error in TrendFollowingStrategy.generate_signal: {e}", exc_info=True)
            return 0  # Fail safe to no signal

    def min_data_points(self):
        """Minimum data points required based on the LONGER of the initial periods."""
        # This provides a stable minimum requirement for data loading
        return max(self._initial_short_period, self._initial_long_period)