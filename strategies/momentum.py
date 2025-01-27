import sys
sys.path.append('..')  # To access config and utils modules

from config.settings import Settings
from utils.logger import setup_logger
import pandas as pd

class MomentumStrategy:
    def __init__(self):
        self.settings = Settings()
        self.logger = setup_logger('strategies_logger', 'logs/strategies.log', level=self.settings.LOG_LEVEL)
        # Parameters for the strategy
        self.price_change_period = getattr(self.settings, 'MOMENTUM_PRICE_CHANGE_PERIOD', 5)
        self.price_change_threshold = getattr(self.settings, 'MOMENTUM_PRICE_CHANGE_THRESHOLD', 0.02)
        self.volume_multiplier = getattr(self.settings, 'MOMENTUM_VOLUME_MULTIPLIER', 1.5)

    def generate_signal(self, data):
        try:
            # Update parameters from settings in case they have been adjusted
            self.price_change_period = getattr(self.settings, 'MOMENTUM_PRICE_CHANGE_PERIOD', 5)
            self.price_change_threshold = getattr(self.settings, 'MOMENTUM_PRICE_CHANGE_THRESHOLD', 0.02)
            self.volume_multiplier = getattr(self.settings, 'MOMENTUM_VOLUME_MULTIPLIER', 1.5)

            if len(data) < self.min_data_points():
                self.logger.warning("Not enough data to generate signal.")
                return 0  # No signal

            # Ensure data has 'close' and 'volume' columns
            if 'close' not in data.columns or 'volume' not in data.columns:
                self.logger.error("Data does not contain 'close' or 'volume' columns.")
                return 0  # No signal

            # Calculate percentage price change over the desired period
            data['price_change'] = data['close'].pct_change(periods=self.price_change_period)

            # Calculate average volume over the desired period
            data['avg_volume'] = data['volume'].rolling(window=self.price_change_period).mean()

            # Drop NaNs
            data = data.dropna()

            # Get the latest data point
            latest_data = data.iloc[-1]
            latest_price_change = latest_data['price_change']
            latest_volume = latest_data['volume']
            latest_avg_volume = latest_data['avg_volume']

            # Log intermediate values
            self.logger.debug(f"Latest Price Change ({self.price_change_period}): {latest_price_change}")
            self.logger.debug(f"Latest Volume: {latest_volume}, Average Volume: {latest_avg_volume}")

            # Check for momentum conditions
            if (
                latest_price_change >= self.price_change_threshold and
                latest_volume >= latest_avg_volume * self.volume_multiplier
            ):
                self.logger.info("Positive momentum detected - Buy signal generated.")
                return 1  # Buy signal
            elif (
                latest_price_change <= -self.price_change_threshold and
                latest_volume >= latest_avg_volume * self.volume_multiplier
            ):
                self.logger.info("Negative momentum detected - Sell signal generated.")
                return -1  # Sell signal
            else:
                self.logger.info("No momentum detected - No signal generated.")
                return 0  # No signal
        except Exception as e:
            self.logger.error(f"Error in MomentumStrategy.generate_signal: {e}", exc_info=True)
            return 0  # No signal

    def min_data_points(self):
        # Return the maximum number of periods used in rolling calculations
        return self.price_change_period + 1  # Plus one to account for pct_change
