import sys
sys.path.append('..')  # To access indicators and utils modules

from config.settings import Settings
from indicators.oscillators import calculate_rsi
from utils.logger import setup_logger
import numpy as np

class MeanReversionStrategy:
    def __init__(self):
        self.settings = Settings()
        self.rsi_period = self.settings.RSI_PERIOD
        self.logger = setup_logger(__name__, 'logs/strategies.log', level=self.settings.LOG_LEVEL)

    def generate_signal(self, data):
        try:
            # Update RSI period from settings in case it has been adjusted
            self.rsi_period = self.settings.RSI_PERIOD

            if len(data) < self.min_data_points():
                self.logger.warning("Not enough data to generate RSI.")
                return 0  # No signal

            data['rsi'] = calculate_rsi(data, self.rsi_period)
            latest_rsi = data['rsi'].iloc[-1]

            # Log the latest RSI value
            self.logger.debug(f"Latest RSI ({self.rsi_period}): {latest_rsi}")

            # Generate signals
            if latest_rsi < 30:
                self.logger.info("RSI below 30 - Buy signal generated.")
                return 1  # Buy signal
            elif latest_rsi > 70:
                self.logger.info("RSI above 70 - Sell signal generated.")
                return -1  # Sell signal
            else:
                self.logger.info("RSI between 30 and 70 - No signal.")
                return 0  # No signal
        except Exception as e:
            self.logger.error(f"Error in MeanReversionStrategy.generate_signal: {e}", exc_info=True)
            return 0  # No signal

    def min_data_points(self):
        return self.rsi_period
