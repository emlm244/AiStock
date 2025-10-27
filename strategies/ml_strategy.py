# strategies/ml_strategy.py

import os
import threading  # For class-level lock
from collections import deque
from datetime import datetime, timedelta

import joblib
import numpy as np

# Ensure correct path (though main.py should handle this)
# parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if parent_dir not in sys.path:
#     sys.path.append(parent_dir)
import pandas as pd
import pytz  # Import pytz

try:
    from sklearn.preprocessing import StandardScaler  # Keep specific import

    from config.settings import Settings
    from indicators.moving_averages import calculate_sma

    # Import all indicators needed for feature engineering
    from indicators.oscillators import calculate_macd, calculate_rsi
    from indicators.volatility import calculate_atr  # Example if ATR is used
    from utils.logger import setup_logger
except ImportError as e:
    print(f'Error importing modules in MLStrategy: {e}')
    raise


class MLStrategy:
    # --- Class variables for managing retraining requests globally ---
    _retraining_lock = threading.Lock()  # Lock for accessing class variables below
    _retraining_requested = False
    _last_retrain_trigger_time = datetime.min.replace(tzinfo=pytz.utc)
    _retrain_cooldown = timedelta(hours=1)  # Don't trigger retrain too often

    def __init__(self):
        self.settings = Settings()  # Keep settings instance
        self.logger = setup_logger('MLStrategy', 'logs/strategies.log', level=self.settings.LOG_LEVEL)
        self.error_logger = setup_logger('MLError', 'logs/error_logs/errors.log', level='ERROR')

        # Model and Scaler Paths
        self.model_dir = 'models'
        self.model_base_name = 'trading_model'
        self.scaler_base_name = 'scaler'
        self.model_path = os.path.join(self.model_dir, f'{self.model_base_name}.pkl')
        self.scaler_path = os.path.join(self.model_dir, f'{self.scaler_base_name}.pkl')

        self.model = None
        self.scaler = None
        self.is_model_loaded = False
        self.model_load_time = None  # Aware UTC time when model was loaded
        self.last_model_check_time = datetime.min.replace(tzinfo=pytz.utc)  # Aware UTC time

        # Performance tracking for retraining trigger (instance specific)
        # Deque stores {'time_utc': datetime, 'pnl': float}
        self.recent_trades = deque(maxlen=getattr(self.settings, 'RETRAINING_TRADE_HISTORY_LENGTH', 100))
        self.last_perf_check_time = datetime.min.replace(tzinfo=pytz.utc)
        self.perf_check_interval = timedelta(hours=getattr(self.settings, 'ML_PERF_CHECK_INTERVAL_HOURS', 4))

        # Feature list (MUST match train_model.py FEATURES list EXACTLY)
        self.features = [
            'volatility',
            'momentum',
            'sma_ratio',
            'rsi',
            'macd',
            'macd_signal',
            'macd_hist',
            # Add/remove features here AND in train_model.py
        ]
        # Match feature parameters with train_model.py (read from Settings)
        self._volatility_window = 5  # Fixed for this example feature
        self._momentum_window = self.settings.MOMENTUM_PRICE_CHANGE_PERIOD
        self._sma_window = self.settings.MOVING_AVERAGE_PERIODS.get('short_term', 10)
        self._rsi_period = self.settings.RSI_PERIOD
        self._macd_fast = self.settings.MACD_SETTINGS['fast_period']
        self._macd_slow = self.settings.MACD_SETTINGS['slow_period']
        self._macd_signal = self.settings.MACD_SETTINGS['signal_period']

        # Calculate initial minimum data points based on feature requirements
        self._initial_min_data_points = self._calculate_min_points(
            self._rsi_period, self._macd_slow, self._momentum_window, self._sma_window, self._volatility_window
        )

        # Load initial model during initialization
        self.load_model()

    # --- Class methods for retraining requests (thread-safe) ---
    @classmethod
    def request_retraining(cls, reason=''):
        """Thread-safe method to request retraining."""
        with cls._retraining_lock:
            now_utc = datetime.now(pytz.utc)
            if not cls._retraining_requested and (now_utc - cls._last_retrain_trigger_time > cls._retrain_cooldown):
                cls._retraining_requested = True
                cls._last_retrain_trigger_time = now_utc
                # Log the request once
                setup_logger('MLStrategy').warning(f'ML Strategy requesting automated retraining. Reason: {reason}')
            # else: Already requested or in cooldown

    @classmethod
    def is_retraining_requested(cls):
        """Thread-safe check if retraining is requested."""
        with cls._retraining_lock:
            return cls._retraining_requested

    @classmethod
    def clear_retraining_request(cls):
        """Thread-safe method to clear the retraining request."""
        with cls._retraining_lock:
            if cls._retraining_requested:
                cls._retraining_requested = False
                setup_logger('MLStrategy').info('ML retraining request cleared.')

    # --- Instance methods ---

    def _calculate_min_points(self, *periods):
        """Helper to calculate min points based on indicator/feature periods."""
        # Add buffer for smoothing convergence, diffs, shifts etc.
        # Needs longest period + potential lookbacks + buffer
        base_requirement = max(periods) if periods else 0
        # Add extra based on complexity (e.g., MACD needs slow+signal periods effectively)
        buffer = 15  # Increased buffer
        return base_requirement + buffer

    def _find_latest_model(self):
        """Finds the 'latest' model/scaler pair based fixed names."""
        model_path = os.path.join(self.model_dir, f'{self.model_base_name}.pkl')
        scaler_path = os.path.join(self.model_dir, f'{self.scaler_base_name}.pkl')

        if os.path.exists(model_path) and os.path.exists(scaler_path):
            try:
                # Use UTC modification time
                model_mod_time_ts = os.path.getmtime(model_path)
                model_mod_time_utc = datetime.fromtimestamp(model_mod_time_ts, tz=pytz.utc)
                return model_path, scaler_path, model_mod_time_utc
            except Exception as e:
                self.error_logger.error(f'Error getting modification time for model/scaler: {e}')
                return None, None, None
        else:
            # Log if files not found, helps debugging initial setup
            if not self.is_model_loaded:  # Log only once if never loaded
                self.logger.warning(f'Latest model/scaler files not found: {model_path}, {scaler_path}')
            return None, None, None

    def load_model(self, force_reload=False):
        """Loads the latest model and scaler. Returns True if successful."""
        try:
            latest_model_path, latest_scaler_path, latest_mod_time_utc = self._find_latest_model()

            if not latest_model_path:
                # Don't log error repeatedly if files are just missing
                self.is_model_loaded = False
                return False  # Cannot load if files don't exist

            # Check if already loaded and up-to-date
            if (
                not force_reload
                and self.is_model_loaded
                and self.model_load_time
                and latest_mod_time_utc
                and self.model_load_time >= latest_mod_time_utc
            ):
                # self.logger.debug("ML model already up-to-date.")
                return True  # Already have the latest loaded model

            self.logger.info(
                f'Attempting to load ML model from: {latest_model_path} (Modified: {latest_mod_time_utc or "N/A"})'
            )
            loaded_model = joblib.load(latest_model_path)
            self.logger.info(f'Attempting to load Scaler from: {latest_scaler_path}')
            loaded_scaler = joblib.load(latest_scaler_path)

            # Basic validation of loaded objects
            if not hasattr(loaded_model, 'predict') or not hasattr(loaded_scaler, 'transform'):
                raise ValueError('Loaded model or scaler object is invalid (missing required methods).')

            # Successfully loaded, update instance state
            self.model = loaded_model
            self.scaler = loaded_scaler
            self.is_model_loaded = True
            self.model_load_time = latest_mod_time_utc or datetime.now(pytz.utc)  # Use mod time or now
            self.model_path = latest_model_path
            self.scaler_path = latest_scaler_path
            self.logger.info(f'Successfully loaded ML model and scaler. Load time: {self.model_load_time}')

            # Clear recent trades as performance relates to the previous model
            if force_reload:
                self.recent_trades.clear()
                self.logger.info('Cleared recent trade history due to model reload.')
            return True

        except FileNotFoundError:
            self.error_logger.error(
                f'ML model or scaler file not found during load attempt: {latest_model_path} / {latest_scaler_path}'
            )
            self.is_model_loaded = False
            self.model = None
            self.scaler = None
            return False
        except Exception as e:
            self.error_logger.critical(f'CRITICAL Error loading ML model/scaler: {e}', exc_info=True)
            self.is_model_loaded = False
            self.model = None
            self.scaler = None
            return False

    def _engineer_features(self, data):
        """Calculates features required by the model. Ensure this matches train_model.py"""
        # This function needs read-only access to settings, should be safe concurrently
        df = data.copy()  # Work on a copy

        # --- Ensure DatetimeIndex ---
        # Data passed should already have UTC DatetimeIndex from main loop
        if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
            self.logger.warning('Data passed to ML features has incorrect index. Attempting conversion.')
            try:
                df = df.set_index(pd.to_datetime(df.index, utc=True))
            except Exception:
                self.error_logger.error('Failed to set UTC DatetimeIndex in ML features.')
                return pd.DataFrame()  # Return empty df on failure
        df = df.sort_index()

        # --- Calculate Features ---
        try:
            df['return'] = df['close'].pct_change()
            df['volatility'] = df['return'].rolling(window=self._volatility_window).std()
            df['momentum'] = df['close'].pct_change(periods=self._momentum_window)
            sma = calculate_sma(df, self._sma_window)
            df['sma_ratio'] = df['close'] / sma  # Handle potential division by zero later
            df['rsi'] = calculate_rsi(df, period=self._rsi_period)
            macd_line, macd_signal_line, macd_hist = calculate_macd(
                df, fast_period=self._macd_fast, slow_period=self._macd_slow, signal_period=self._macd_signal
            )
            df['macd'] = macd_line
            df['macd_signal'] = macd_signal_line
            df['macd_hist'] = macd_hist
            # Add more features here if needed, matching train_model.py

        except Exception as e:
            self.error_logger.error(f'Error calculating features in MLStrategy: {e}', exc_info=True)
            return pd.DataFrame()  # Return empty on error

        # --- Clean and Select ---
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        # Only return rows where ALL required features are non-NaN
        df.dropna(subset=self.features, inplace=True)

        return df[self.features]  # Return only the feature columns

    def _check_performance_and_trigger_retrain(self, current_time_utc):
        """Checks recent performance and triggers retraining if needed (uses instance data)."""
        # Check only if autonomous mode and auto-retraining are enabled
        if not self.settings.AUTONOMOUS_MODE or not self.settings.ENABLE_AUTO_RETRAINING:
            return

        # Check periodically based on time interval
        if current_time_utc - self.last_perf_check_time < self.perf_check_interval:
            return
        self.last_perf_check_time = current_time_utc

        # Check 1: Retrain based on time interval since last load/retrain
        retrain_interval = timedelta(hours=self.settings.RETRAINING_INTERVAL_HOURS)
        if self.model_load_time and (current_time_utc - self.model_load_time > retrain_interval):
            self.logger.info(
                f'ML model age ({current_time_utc - self.model_load_time}) exceeds retraining interval ({retrain_interval}).'
            )
            self.request_retraining('Scheduled Interval')  # Use class method to request
            return  # Don't check performance if interval triggered

        # Check 2: Retrain based on performance (win rate below threshold)
        num_trades = len(self.recent_trades)
        if num_trades >= self.settings.RETRAINING_MIN_TRADES_THRESHOLD:
            wins = sum(1 for trade in self.recent_trades if trade.get('pnl', 0) > 0)
            win_rate = wins / num_trades
            perf_threshold = self.settings.RETRAINING_PERFORMANCE_THRESHOLD

            self.logger.info(
                f'ML Strategy Performance Check: Win Rate={win_rate:.2%} ({wins}/{num_trades} trades), Threshold={perf_threshold:.1%}'
            )

            if win_rate < perf_threshold:
                self.logger.warning(
                    f'ML Strategy recent win rate ({win_rate:.1%}) is below threshold ({perf_threshold:.1%}).'
                )
                self.request_retraining(f'Performance dip (WR {win_rate:.1%})')  # Use class method
            # Optionally clear recent_trades after check? Or keep rolling? Keep rolling for now.

    def add_trade_result(self, trade_info):
        """Called by PortfolioManager when an ML trade closes. Adds PnL and time."""
        # Ensure this method is thread-safe if PM could call it from a different thread
        # If PM updates are always within its own lock, and this is called from there, it might be okay.
        # However, deque append itself is thread-safe.
        try:
            # Store only essential info: time and PnL
            trade_time = trade_info.get('time_utc', datetime.now(pytz.utc))
            trade_pnl = trade_info.get('pnl', 0.0)
            self.recent_trades.append({'time_utc': trade_time, 'pnl': trade_pnl})
            self.logger.debug(f'Added ML trade result: PnL={trade_pnl:.2f}')
        except Exception as e:
            self.error_logger.error(f'Error adding trade result to ML Strategy history: {e}', exc_info=True)

    def generate_signal(self, data):
        """Generates prediction and signal based on latest data."""
        now_utc = datetime.now(pytz.utc)

        # --- Auto-reload model check ---
        if self.settings.ML_MODEL_AUTO_RELOAD:
            check_interval = timedelta(minutes=self.settings.ML_MODEL_RELOAD_INTERVAL_MIN)
            if now_utc - self.last_model_check_time > check_interval:
                self.load_model()  # Attempt to load if newer version exists
                self.last_model_check_time = now_utc

        # --- Check if model is loaded ---
        if not self.is_model_loaded or self.model is None or self.scaler is None:
            # Logged during load_model if failed, avoid spamming here
            # self.logger.warning("ML model not loaded. Cannot generate signal.")
            return 0

        # --- Performance Check & Retraining Trigger ---
        self._check_performance_and_trigger_retrain(now_utc)

        # --- Check Data Sufficiency ---
        current_min_points = self.min_data_points()  # Use the method
        if data is None or len(data) < current_min_points:
            # self.logger.debug(f"Not enough data ({len(data) if data is not None else 'None'}) for ML features (requires {current_min_points}).")
            return 0

        try:
            # --- Feature Engineering ---
            features_df = self._engineer_features(data)  # Gets DF with only feature columns

            if features_df.empty:
                # self.logger.warning("DataFrame empty after feature engineering or NaN removal. Cannot generate signal.")
                return 0

            # Get the latest row of features
            latest_features = features_df.iloc[[-1]]  # Keep as DataFrame

            # Double check for NaNs just before scaling (should be handled by engineer_features)
            if latest_features.isnull().values.any():
                self.logger.warning(
                    'NaN values detected in the latest feature set before scaling. Cannot generate signal.'
                )
                return 0

            # --- Scaling & Prediction ---
            try:
                X_scaled = self.scaler.transform(latest_features)
            except Exception as scale_e:
                self.error_logger.error(f'Error scaling features: {scale_e}', exc_info=True)
                return 0

            try:
                prediction = self.model.predict(X_scaled)[0]
                prediction_proba = None
                if hasattr(self.model, 'predict_proba'):
                    prediction_proba = self.model.predict_proba(X_scaled)[0]
                    # self.logger.debug(f"ML Raw Prediction Probs: {prediction_proba}")
            except Exception as pred_e:
                self.error_logger.error(f'Error during model prediction: {pred_e}', exc_info=True)
                return 0  # No signal on prediction error

            # --- Signal Generation based on Prediction and Confidence ---
            signal = 0
            confidence_threshold = self.settings.ML_CONFIDENCE_THRESHOLD

            if prediction == 1:  # Predict UP
                prob = prediction_proba[1] if prediction_proba is not None and len(prediction_proba) > 1 else 1.0
                if prob >= confidence_threshold:
                    signal = 1
                    self.logger.debug(f'ML predicts UP (Prob: {prob:.2f} >= {confidence_threshold:.2f}) -> BUY Signal')
                else:
                    self.logger.debug(
                        f'ML predicts UP but prob ({prob:.2f}) below threshold {confidence_threshold:.2f}. No signal.'
                    )
            elif prediction == 0:  # Predict DOWN/FLAT
                prob = prediction_proba[0] if prediction_proba is not None and len(prediction_proba) > 0 else 1.0
                if prob >= confidence_threshold:
                    signal = -1
                    self.logger.debug(
                        f'ML predicts DOWN/FLAT (Prob: {prob:.2f} >= {confidence_threshold:.2f}) -> SELL Signal'
                    )
                else:
                    self.logger.debug(
                        f'ML predicts DOWN/FLAT but prob ({prob:.2f}) below threshold {confidence_threshold:.2f}. No signal.'
                    )
            # else: Unexpected prediction value?

            return signal

        except Exception as e:
            self.error_logger.error(f'Error in MLStrategy.generate_signal: {e}', exc_info=True)
            return 0  # Fail safe to no signal

    def min_data_points(self):
        """Calculates min points based on *current* settings for feature calculation."""
        # Read current settings dynamically if they might change
        # For now, use the initially calculated value based on settings at init time
        # If feature parameters can be optimized live, this needs to recalculate
        return self._initial_min_data_points
