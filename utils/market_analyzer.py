# utils/market_analyzer.py

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

try:
    from config.settings import Settings
    from utils.logger import setup_logger
    # Import necessary indicators directly
    from indicators.trend import calculate_adx
    from indicators.volatility import calculate_bollinger_bands_width, calculate_atr
except ImportError as e:
    print(f"Error importing modules in MarketRegimeDetector: {e}")
    raise

class MarketRegimeDetector:
    """
    Analyzes market data to determine the current market regime
    (e.g., trend strength, volatility level) for a specific symbol.
    """

    def __init__(self, settings, logger=None):
        self.settings = settings
        self.logger = logger or setup_logger('MarketAnalyzer', 'logs/app.log', level=settings.LOG_LEVEL)
        self.error_logger = setup_logger('MarketAnalyzerError', 'logs/error_logs/errors.log', level='ERROR')

        # --- Regime Thresholds from Settings ---
        try:
            self.adx_trend_threshold = getattr(settings, 'ADX_TREND_THRESHOLD', 25)
            self.volatility_threshold_atr_pct_high = getattr(settings, 'VOLATILITY_THRESHOLD_ATR_PCT', 0.02)
            self.volatility_threshold_atr_pct_low = getattr(settings, 'LOW_VOLATILITY_THRESHOLD_ATR_PCT', 0.005)
            self.bbw_squeeze_threshold = getattr(settings, 'BBW_SQUEEZE_THRESHOLD', 0.015)

            # Indicator periods from settings
            self.adx_period = getattr(settings, 'ADX_PERIOD', 14)
            self.bb_period = getattr(settings, 'BBANDS_PERIOD', 20)
            self.bb_stddev = getattr(settings, 'BBANDS_STDDEV', 2.0)
            self.atr_period = getattr(settings, 'ATR_PERIOD', 14)
            self.min_atr_value = getattr(settings, 'MIN_ATR_VALUE', 1e-8) # Prevent div by zero
        except AttributeError as e:
             self.error_logger.critical(f"Missing required setting for MarketRegimeDetector: {e}. Using defaults.")
             # Apply defaults explicitly if settings load fails partially
             self.adx_trend_threshold = 25
             self.volatility_threshold_atr_pct_high = 0.02
             self.volatility_threshold_atr_pct_low = 0.005
             self.bbw_squeeze_threshold = 0.015
             self.adx_period = 14
             self.bb_period = 20
             self.bb_stddev = 2.0
             self.atr_period = 14
             self.min_atr_value = 1e-8


        # Minimum data points required for ALL indicators used
        # ADX needs more data for smoothing
        self.min_data_points = max(self.adx_period * 2, self.bb_period, self.atr_period + 1) + 15 # Increased buffer

        # Cache for current regimes {symbol: regime_dict}
        self.current_regimes = {}
        # Lock if accessed/modified from multiple threads (unlikely in current design)
        # self._lock = threading.Lock()

    def detect_regime(self, symbol, market_data_df):
        """
        Analyzes market data (expecting UTC DatetimeIndex) for a symbol and determines the regime.

        Args:
            symbol (str): The trading symbol.
            market_data_df (pd.DataFrame): DataFrame with UTC DatetimeIndex and OHLCV columns.

        Returns:
            dict: Dictionary containing regime details, or default 'Unknown' state.
        """
        default_regime = {
            'trend': 'Unknown', 'volatility': 'Unknown', 'regime': 'Unknown',
            'indicators': {'adx': np.nan, 'plus_di': np.nan, 'minus_di': np.nan,
                           'bbw': np.nan, 'atr': np.nan, 'atr_pct': np.nan}
        }

        # --- Input Validation ---
        if market_data_df is None or market_data_df.empty:
            # self.logger.debug(f"Regime for {symbol}: Input data is None or empty.")
            self.current_regimes[symbol] = default_regime
            return default_regime.copy()

        if not isinstance(market_data_df.index, pd.DatetimeIndex) or market_data_df.index.tz is None:
             self.error_logger.warning(f"Regime detection for {symbol}: Data has invalid index. Requires UTC DatetimeIndex.")
             self.current_regimes[symbol] = default_regime
             return default_regime.copy()

        if len(market_data_df) < self.min_data_points:
            # self.logger.debug(f"Regime for {symbol}: Insufficient data ({len(market_data_df)}/{self.min_data_points}).")
            self.current_regimes[symbol] = default_regime
            return default_regime.copy()

        required_cols = ['high', 'low', 'close']
        if not all(col in market_data_df.columns for col in required_cols):
             self.error_logger.warning(f"Regime detection for {symbol}: Data missing required columns (high, low, close).")
             self.current_regimes[symbol] = default_regime
             return default_regime.copy()

        # --- Calculate Indicators ---
        try:
            df = market_data_df.copy() # Work on a copy

            adx, plus_di, minus_di = calculate_adx(df, period=self.adx_period)
            bbw = calculate_bollinger_bands_width(df, period=self.bb_period, std_dev=self.bb_stddev)
            atr = calculate_atr(df, period=self.atr_period)

            # Get latest values (ensure index access is valid)
            latest_index = df.index[-1]
            latest_adx = adx.loc[latest_index] if adx is not None else np.nan
            latest_plus_di = plus_di.loc[latest_index] if plus_di is not None else np.nan
            latest_minus_di = minus_di.loc[latest_index] if minus_di is not None else np.nan
            latest_bbw = bbw.loc[latest_index] if bbw is not None else np.nan
            latest_atr = atr.loc[latest_index] if atr is not None else np.nan
            latest_close = df['close'].loc[latest_index]

            # --- Check for NaN / Invalid Indicator Values ---
            indicators_valid = all(pd.notna(val) for val in [latest_adx, latest_plus_di, latest_minus_di, latest_bbw, latest_atr, latest_close])
            if not indicators_valid or latest_close <= 0 or latest_atr < self.min_atr_value:
                self.logger.warning(f"Regime calc warning for {symbol}: NaN or invalid indicator/price value found. "
                                    f"(ADX:{latest_adx}, +DI:{latest_plus_di}, -DI:{latest_minus_di}, BBW:{latest_bbw}, ATR:{latest_atr}, Close:{latest_close})")
                self.current_regimes[symbol] = default_regime
                return default_regime.copy()

            # --- Determine Trend Regime ---
            trend_regime = 'Ranging'
            if latest_adx > self.adx_trend_threshold:
                if latest_plus_di > latest_minus_di:
                    trend_regime = 'Trending Up'
                else: # +DI <= -DI
                    trend_regime = 'Trending Down'
            # else: ADX below threshold indicates ranging

            # --- Determine Volatility Regime ---
            atr_pct = (latest_atr / latest_close) if latest_close > 0 else 0.0
            volatility_regime = 'Normal' # Default
            is_squeeze = latest_bbw < self.bbw_squeeze_threshold

            if is_squeeze:
                volatility_regime = 'Squeeze'
            elif atr_pct > self.volatility_threshold_atr_pct_high:
                volatility_regime = 'High'
            elif atr_pct < self.volatility_threshold_atr_pct_low:
                volatility_regime = 'Low'
            # else: remains 'Normal'

            # --- Combine Regimes ---
            combined_regime = f"{trend_regime} - {volatility_regime}"

            # Store results
            indicator_values = {
                'adx': round(latest_adx, 2),
                'plus_di': round(latest_plus_di, 2),
                'minus_di': round(latest_minus_di, 2),
                'bbw': round(latest_bbw, 5),
                'atr': round(latest_atr, 5),
                'atr_pct': round(atr_pct, 5)
            }
            current_regime_info = {
                'trend': trend_regime,
                'volatility': volatility_regime,
                'regime': combined_regime,
                'indicators': indicator_values,
                'timestamp_utc': datetime.now(pytz.utc) # Add timestamp of calculation
            }

            # --- Update Cache and Log Changes ---
            previous_regime = self.current_regimes.get(symbol, {}).get('regime', 'Unknown')
            self.current_regimes[symbol] = current_regime_info # Update cache
            if previous_regime != combined_regime:
                 self.logger.info(f"Regime change for {symbol}: {previous_regime} -> {combined_regime} (Indicators: {indicator_values})")
            else:
                 self.logger.debug(f"Regime update for {symbol}: {combined_regime}")

            return current_regime_info.copy()

        except Exception as e:
            self.error_logger.error(f"Error detecting regime for {symbol}: {e}", exc_info=True)
            self.current_regimes[symbol] = default_regime # Reset cache on error
            return default_regime.copy()

    def get_regime(self, symbol):
        """ Returns the last calculated regime dictionary for a symbol (thread-safe read). """
        # Assumes reads are okay without lock if updates happen in single main thread
        # If updated from multiple threads, add lock here.
        # Return a copy to prevent external modification
        return self.current_regimes.get(symbol, {
            'trend': 'Unknown', 'volatility': 'Unknown', 'regime': 'Unknown',
            'indicators': {'adx': np.nan, 'bbw': np.nan, 'atr_pct': np.nan}
        }).copy()

    def get_volatility_level(self, symbol):
        """ Convenience method to get just the volatility level (thread-safe read). """
        # Assumes reads are okay without lock
        return self.get_regime(symbol).get('volatility', 'Unknown')
