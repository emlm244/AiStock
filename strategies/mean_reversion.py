# strategies/mean_reversion.py
# Ensure correct path (though main.py should handle this)
# parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if parent_dir not in sys.path:
#     sys.path.append(parent_dir)

import pandas as pd

try:
    from config.settings import Settings
    from indicators.oscillators import calculate_rsi
    from utils.logger import setup_logger
except ImportError as e:
    print(f'Error importing modules in MeanReversionStrategy: {e}')
    raise


class MeanReversionStrategy:
    def __init__(self):
        # Keep settings instance to read parameters dynamically
        self.settings = Settings()
        self.logger = setup_logger('MeanReversion', 'logs/strategies.log', level=self.settings.LOG_LEVEL)
        # Store initial period for min_data_points calculation
        try:
            self._initial_rsi_period = self.settings.RSI_PERIOD
            if not isinstance(self._initial_rsi_period, int) or self._initial_rsi_period <= 1:
                self.logger.warning(
                    f'Initial RSI period ({self._initial_rsi_period}) invalid. Using default 14 for min_data_points.'
                )
                self._initial_rsi_period = 14
        except AttributeError:
            self.logger.error('RSI_PERIOD not found in settings. Using default 14 for min_data_points.')
            self._initial_rsi_period = 14

    def generate_signal(self, data):
        """Generates +1 (buy), -1 (sell), or 0 (hold) signal based on RSI."""
        try:
            # Read RSI period and thresholds dynamically from settings
            rsi_period = self.settings.RSI_PERIOD
            oversold_threshold = self.settings.RSI_OVERSOLD
            overbought_threshold = self.settings.RSI_OVERBOUGHT

            # --- Input Validation ---
            if not isinstance(rsi_period, int) or rsi_period <= 1:
                self.logger.error(f'Invalid RSI period in settings: {rsi_period}. No signal.')
                return 0
            if (
                not (0 < oversold_threshold < 100)
                or not (0 < overbought_threshold < 100)
                or oversold_threshold >= overbought_threshold
            ):
                self.logger.error(
                    f'Invalid RSI thresholds: OB={overbought_threshold}, OS={oversold_threshold}. No signal.'
                )
                return 0

            required_data = self.min_data_points()  # Use method to get requirement
            if data is None or len(data) < required_data:
                # self.logger.debug(f"Not enough data ({len(data) if data is not None else 0}/{required_data}) for RSI({rsi_period}).")
                return 0  # Not enough data

            # --- Calculate Indicator ---
            # calculate_rsi handles insufficient data internally by returning NaNs
            data['rsi'] = calculate_rsi(data, rsi_period)
            latest_rsi = data['rsi'].iloc[-1]

            # --- Check for NaNs ---
            if pd.isna(latest_rsi):
                self.logger.warning(
                    f'NaN value encountered in calculated RSI({rsi_period}). Check data quality. No signal.'
                )
                return 0

            # Log the latest RSI value for debugging
            self.logger.debug(
                f'MeanRev Check: RSI({rsi_period})={latest_rsi:.2f} (OS:{oversold_threshold}, OB:{overbought_threshold})'
            )

            # --- Signal Logic ---
            # Generate signals based on thresholds
            if latest_rsi < oversold_threshold:
                # Potential Buy signal (entering oversold)
                # Could add condition: only buy if PREVIOUS RSI was >= oversold? (i.e., crossing down)
                # prev_rsi = data['rsi'].iloc[-2] if len(data) > required_data else np.nan
                # if prev_rsi >= oversold_threshold:
                #    return 1 # Buy signal on cross
                return 1  # Simpler: Buy if below threshold
            elif latest_rsi > overbought_threshold:
                # Potential Sell signal (entering overbought)
                # Could add condition: only sell if PREVIOUS RSI was <= overbought?
                # prev_rsi = data['rsi'].iloc[-2] if len(data) > required_data else np.nan
                # if prev_rsi <= overbought_threshold:
                #    return -1 # Sell signal on cross
                return -1  # Simpler: Sell if above threshold
            else:
                # RSI is within neutral zone
                # self.logger.debug("RSI between thresholds - No signal.")
                return 0  # No signal (hold)

        except AttributeError as e:
            self.logger.error(f'Missing attribute in settings (e.g., RSI_PERIOD): {e}. No signal.')
            return 0
        except Exception as e:
            self.logger.error(f'Error in MeanReversionStrategy.generate_signal: {e}', exc_info=True)
            return 0  # Fail safe to no signal

    def min_data_points(self):
        """Minimum data points required for RSI calculation."""
        # RSI needs period + 1 for diff() calculation, plus buffer for smoothing convergence
        return self._initial_rsi_period + 5  # Add small buffer
