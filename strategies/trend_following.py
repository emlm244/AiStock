import sys
sys.path.append('..')  # To access indicators and utils modules

import numpy as np
import pandas as pd
from indicators.moving_averages import calculate_sma
from utils.logger import setup_logger
from config.settings import Settings

class TrendFollowingStrategy:
    def __init__(self):
        self.settings = Settings()
        self.logger = setup_logger(__name__, 'logs/strategies.log', level=self.settings.LOG_LEVEL)

    def generate_signal(self, data):
        try:
            # Update moving average periods from settings
            short_term_period = self.settings.MOVING_AVERAGE_PERIODS['short_term']
            long_term_period = self.settings.MOVING_AVERAGE_PERIODS['long_term']

            if len(data) < self.min_data_points():
                self.logger.warning("Not enough data to calculate moving averages.")
                return 0  # No signal

            data['short_ma'] = calculate_sma(data, short_term_period)
            data['long_ma'] = calculate_sma(data, long_term_period)

            # Log the latest moving average values
            self.logger.debug(f"Latest Short MA ({short_term_period}): {data['short_ma'].iloc[-1]}")
            self.logger.debug(f"Latest Long MA ({long_term_period}): {data['long_ma'].iloc[-1]}")

            # Generate signals
            if data['short_ma'].iloc[-1] > data['long_ma'].iloc[-1]:
                self.logger.info("Short MA crossed above Long MA - Buy signal generated.")
                return 1  # Buy signal
            elif data['short_ma'].iloc[-1] < data['long_ma'].iloc[-1]:
                self.logger.info("Short MA crossed below Long MA - Sell signal generated.")
                return -1  # Sell signal
            else:
                self.logger.info("No crossover detected - No signal.")
                return 0  # No signal
        except Exception as e:
            self.logger.error(f"Error in TrendFollowingStrategy.generate_signal: {e}", exc_info=True)
            return 0  # No signal

    def min_data_points(self):
        return max(self.settings.MOVING_AVERAGE_PERIODS.values())
