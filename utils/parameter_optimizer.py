# utils/parameter_optimizer.py

from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pytz
from collections import defaultdict # Keep defaultdict

try:
    from utils.logger import setup_logger
    from utils.market_analyzer import MarketRegimeDetector # Requires regime info
    from config.settings import Settings
except ImportError as e:
    print(f"Error importing modules in ParameterOptimizer: {e}")
    raise


class AdaptiveParameterOptimizer:
    """
    Adaptively adjusts strategy parameters based on recent trading performance
    and detected market regime. Operates primarily in AUTONOMOUS_MODE.
    NOTE: This uses HEURISTICS, not formal optimization algorithms. Use with caution.
    Designed to run within the main bot loop thread.
    """

    def __init__(self, settings, trade_history_getter, regime_detector, logger=None):
        self.settings = settings # Direct reference to mutable Settings object
        self.trade_history_getter = trade_history_getter # Function to get trade history (e.g., pm.get_trade_history)
        self.regime_detector = regime_detector # MarketRegimeDetector instance
        self.logger = logger or setup_logger('ParamOptimizer', 'logs/app.log', level=self.settings.LOG_LEVEL)
        self.error_logger = setup_logger('OptimizerError', 'logs/error_logs/errors.log', level='ERROR')

        # --- Configuration from Settings ---
        self.optimization_interval = timedelta(hours=getattr(settings, 'OPTIMIZER_INTERVAL_HOURS', 4))
        self.min_trades_for_eval = getattr(settings, 'OPTIMIZER_MIN_TRADES', 15)
        self.lookback_period = timedelta(days=getattr(settings, 'OPTIMIZER_LOOKBACK_DAYS', 1))
        self.last_optimization_time = datetime.min.replace(tzinfo=pytz.utc) # Use aware datetime

        # --- Parameter Bounds ---
        # Define bounds for parameters intended for adaptation. Read from settings where possible.
        # Ensure keys match the structure within the Settings class instance.
        self.parameter_bounds = {
            # Strategy Params (Example structure, adjust if Settings structure differs)
            'MOVING_AVERAGE_PERIODS.short_term': (5, 30),
            'MOVING_AVERAGE_PERIODS.long_term': (20, 100),
            'RSI_PERIOD': (7, 25),
            'RSI_OVERBOUGHT': (65, 85),
            'RSI_OVERSOLD': (15, 35),
            'MOMENTUM_PRICE_CHANGE_PERIOD': (3, 15),
            'MOMENTUM_PRICE_CHANGE_THRESHOLD': (0.005, 0.05),
            'MOMENTUM_VOLUME_MULTIPLIER': (1.2, 3.5),
            # MACD settings often related to ML features, maybe less adapted here?
            # 'MACD_SETTINGS.fast_period': (8, 20), ...

            # Adaptive Risk Params (Only relevant if ENABLE_ADAPTIVE_RISK is True)
            # Bounds for the *base* multipliers/ratios in settings
            'STOP_LOSS_ATR_MULTIPLIER': (1.0, 4.0),
            'TAKE_PROFIT_ATR_MULTIPLIER': (1.5, 8.0),
            'TAKE_PROFIT_RR_RATIO': (1.0, 5.0),
        }

        # --- Filter bounds based on configured SL/TP types ---
        # Remove bounds for parameters not relevant to the current config
        if self.settings.STOP_LOSS_TYPE != 'ATR': self.parameter_bounds.pop('STOP_LOSS_ATR_MULTIPLIER', None)
        if self.settings.TAKE_PROFIT_TYPE != 'ATR': self.parameter_bounds.pop('TAKE_PROFIT_ATR_MULTIPLIER', None)
        if self.settings.TAKE_PROFIT_TYPE != 'RATIO': self.parameter_bounds.pop('TAKE_PROFIT_RR_RATIO', None)

        self.logger.info(f"Parameter Optimizer initialized. Adaptable params: {list(self.parameter_bounds.keys())}")
        # Store performance snapshot per symbol/strategy used for optimization cycle
        # {symbol: {strat_name: {'win_rate': WR, 'trades': N}}} - Updated each cycle
        self.strategy_performance_snapshot = defaultdict(lambda: defaultdict(lambda: {'trades': 0, 'wins': 0, 'win_rate': 0.0}))

        # No internal lock needed if only run from main thread


    def _get_setting(self, setting_path, default=None):
        """ Safely gets a potentially nested setting from the Settings object. """
        try:
            keys = setting_path.split('.')
            value = self.settings # Start with the settings instance
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key) # Access dict item
                else:
                    value = getattr(value, key) # Access object attribute
                if value is None: return default # Stop if intermediate key not found
            return value
        except (AttributeError, KeyError, TypeError) as e:
            self.error_logger.debug(f"Optimizer: Error getting setting '{setting_path}': {e}")
            return default

    def _set_setting(self, setting_path, new_value):
        """ Safely sets a potentially nested setting in the Settings object. """
        try:
            keys = setting_path.split('.')
            obj = self.settings # Start with the settings instance
            # Navigate to the parent object/dict
            for key in keys[:-1]:
                if isinstance(obj, dict):
                    if key not in obj: obj[key] = {} # Create dict if needed for path
                    obj = obj.get(key)
                else:
                    # If attribute doesn't exist or isn't a container, try creating one? Risky.
                    # Assume structure exists based on parameter_bounds definition.
                    if not hasattr(obj, key):
                         self.error_logger.error(f"Optimizer: Cannot navigate setting path '{setting_path}'. Missing intermediate attribute '{key}'.")
                         return False
                    obj = getattr(obj, key)

                if not isinstance(obj, (dict, object)): # Check if parent is valid container
                     self.error_logger.error(f"Optimizer: Invalid intermediate object type for path '{setting_path}' at key '{key}'. Type: {type(obj)}")
                     return False


            final_key = keys[-1]
            current_value = None

            # Get current value before setting
            if isinstance(obj, dict):
                current_value = obj.get(final_key)
            elif hasattr(obj, final_key):
                 current_value = getattr(obj, final_key)

            # Convert new_value type to match current_value type if possible
            if current_value is not None and not isinstance(new_value, type(current_value)):
                 try:
                     new_value = type(current_value)(new_value)
                 except (ValueError, TypeError) as e:
                     self.error_logger.warning(f"Optimizer: Type mismatch for '{setting_path}'. Cannot convert {new_value} to {type(current_value)}. Error: {e}")
                     # Keep original type or skip setting? Let's skip.
                     return False


            # Set the value only if it has changed significantly
            # Use isclose for floats, direct compare for others
            changed = False
            if isinstance(new_value, float) and isinstance(current_value, float):
                if not np.isclose(current_value, new_value): changed = True
            elif current_value != new_value:
                 changed = True

            if changed:
                 if isinstance(obj, dict):
                     obj[final_key] = new_value
                 elif hasattr(obj, final_key):
                     setattr(obj, final_key, new_value)
                 else:
                     # This case shouldn't happen if navigation worked
                     self.error_logger.error(f"Optimizer: Cannot set setting '{setting_path}'. Parent is not dict and has no attribute '{final_key}'. Parent type: {type(obj)}")
                     return False

                 self.logger.info(f"Optimizer updated setting '{setting_path}': {current_value} -> {new_value}")
                 return True
            else:
                 # self.logger.debug(f"Optimizer: No change needed for '{setting_path}' (current={current_value}, new={new_value})")
                 return True # No change needed, but operation considered successful

        except Exception as e:
            self.error_logger.error(f"Optimizer: Failed to set setting '{setting_path}' to {new_value}: {e}", exc_info=True)
            return False

    def _clamp(self, value, min_val, max_val):
        """ Clamps a value within the min/max bounds. """
        if value is None: return min_val # Or some other default?
        # Ensure bounds are valid
        if min_val is None or max_val is None or min_val > max_val: return value
        return max(min_val, min(value, max_val))

    def _discretize(self, value, step=1):
        """ Rounds value to the nearest step (e.g., integers for periods). """
        if value is None or step is None or step <= 0: return value
        # Round to nearest step, ensuring type consistency (int if step is int)
        rounded = round(value / step) * step
        return int(rounded) if isinstance(step, int) else rounded


    def update_parameters(self, force=False):
        """ Main function to potentially update parameters based on recent performance and regime. """
        # Check if optimization should run
        if not self.settings.AUTONOMOUS_MODE:
            # self.logger.debug("Parameter optimizer skipped: AUTONOMOUS_MODE is False.")
            return

        current_time_utc = datetime.now(pytz.utc)
        if not force and (current_time_utc - self.last_optimization_time) < self.optimization_interval:
            return # Too soon

        if not self.regime_detector:
             self.logger.warning("Optimizer cannot run: MarketRegimeDetector not provided.")
             return
        if not callable(self.trade_history_getter):
             self.logger.warning("Optimizer cannot run: Trade history getter function not provided.")
             return


        self.logger.info(f"--- Running Parameter Optimization Heuristics ({current_time_utc.strftime(self.settings.LOG_TIMESTAMP_FORMAT)}) ---")
        self.last_optimization_time = current_time_utc

        # 1. Get Recent Trade History
        try:
            # Call the provided function to get a copy of trade history
            full_trade_history = self.trade_history_getter()
            if not full_trade_history:
                 self.logger.info("Optimizer: No recent trade history available.")
                 return
        except Exception as e:
            self.error_logger.error(f"Optimizer: Error getting trade history: {e}", exc_info=True)
            return

        lookback_start_time = current_time_utc - self.lookback_period

        # 2. Calculate Performance Snapshot per Symbol/Strategy for this cycle
        # Reset snapshot before recalculating
        self.strategy_performance_snapshot = defaultdict(lambda: defaultdict(lambda: {'trades': 0, 'wins': 0}))

        for trade in full_trade_history:
             trade_time_utc = trade.get('time_utc') # Expecting aware UTC datetime
             # Validate trade time
             if not isinstance(trade_time_utc, datetime) or trade_time_utc.tzinfo is None: continue

             # Filter trades within lookback period and having required info
             if trade_time_utc >= lookback_start_time:
                 symbol = trade.get('symbol')
                 # Map trade strategy (e.g., 'TrendFollowing_SL') back to base strategy name
                 base_name = trade.get('strategy', '').split('_')[0]
                 pnl = trade.get('pnl') # Should include commission

                 # Only track performance for strategies we might optimize
                 if symbol and base_name in self.parameter_bounds and pnl is not None:
                     snapshot = self.strategy_performance_snapshot[symbol][base_name]
                     snapshot['trades'] += 1
                     if pnl > 0:
                         snapshot['wins'] += 1

        # Calculate win rates in snapshot after counting
        for symbol_data in self.strategy_performance_snapshot.values():
             for strat_name, strat_data in symbol_data.items():
                  if strat_data['trades'] > 0:
                      strat_data['win_rate'] = strat_data['wins'] / strat_data['trades']
                  else:
                      strat_data['win_rate'] = 0.0


        # 3. Optimize Parameters for each Symbol/Strategy with sufficient trade data
        symbols_to_optimize = list(self.strategy_performance_snapshot.keys())
        if not symbols_to_optimize:
             self.logger.info("Optimizer: No symbols with recent optimizable trade history found.")
             return

        self.logger.info(f"Optimizer: Analyzing trades from last {self.lookback_period} across {len(symbols_to_optimize)} symbols for potential adaptation.")

        # Iterate through defined adaptable parameters
        for setting_path, bounds in self.parameter_bounds.items():
             # Determine which strategy this parameter belongs to (heuristic mapping)
             strategy_key = self._get_strategy_key_from_setting(setting_path)
             if not strategy_key: continue # Skip if parameter doesn't map to a known strategy type

             # Apply optimization across all symbols where this strategy was traded sufficiently
             for symbol in symbols_to_optimize:
                  # Ensure performance data exists for this symbol and strategy
                  if symbol in self.strategy_performance_snapshot and strategy_key in self.strategy_performance_snapshot[symbol]:
                      perf_data = self.strategy_performance_snapshot[symbol][strategy_key]
                      # Check if enough trades occurred for meaningful adaptation
                      if perf_data['trades'] >= self.min_trades_for_eval:
                         # Get regime for this specific symbol
                         regime_info = self.regime_detector.get_regime(symbol)
                         trend_regime = regime_info.get('trend', 'Unknown')
                         vol_regime = regime_info.get('volatility', 'Unknown')
                         self.logger.debug(f"Optimizing '{setting_path}' for {symbol} (WinRate: {perf_data['win_rate']:.1%}, Trades: {perf_data['trades']}, Trend: {trend_regime}, Vol: {vol_regime})")
                         self._optimize_parameter(setting_path, bounds, perf_data['win_rate'], trend_regime, vol_regime)
                      # else:
                      #    self.logger.debug(f"Skipping optimization for '{setting_path}' on {symbol}: Insufficient trades ({perf_data['trades']}/{self.min_trades_for_eval}).")


        self.logger.info(f"--- Parameter Optimization Heuristics Finished ---")


    def _get_strategy_key_from_setting(self, setting_path):
        """ Maps a setting path to its corresponding strategy class name (best effort). """
        # This mapping needs to be kept in sync with Settings structure and strategy class names
        path_lower = setting_path.lower()
        if 'moving_average' in path_lower: return 'TrendFollowingStrategy'
        if 'rsi' in path_lower: return 'MeanReversionStrategy'
        if 'momentum' in path_lower: return 'MomentumStrategy'
        if 'macd' in path_lower: return 'MLStrategy' # Or common indicator pool? Assume ML features for now.
        if 'stop_loss' in path_lower or 'take_profit' in path_lower: return 'Risk' # Special category for risk params
        return None


    def _optimize_parameter(self, setting_path, bounds, win_rate, trend_regime, vol_regime):
        """
        Optimizes a single parameter based on performance and market regime heuristics.
        Modifies the self.settings object directly.
        """
        current_value = self._get_setting(setting_path)
        if current_value is None:
            self.logger.warning(f"Optimizer: Cannot get current value for '{setting_path}'. Skipping.")
            return

        min_bound, max_bound = bounds
        if min_bound is None or max_bound is None:
             self.logger.warning(f"Optimizer: Invalid bounds for '{setting_path}'. Skipping.")
             return

        # Skip risk param adaptation if globally disabled
        is_risk_param = 'STOP_LOSS' in setting_path or 'TAKE_PROFIT' in setting_path
        if is_risk_param and not self.settings.ENABLE_ADAPTIVE_RISK:
             # self.logger.debug(f"Skipping risk parameter '{setting_path}' adaptation: ENABLE_ADAPTIVE_RISK is False.")
             return

        # --- Heuristic Adjustment Logic ---
        adjustment_direction = 0 # -1: Decrease, 0: No change, +1: Increase
        is_float = isinstance(current_value, float)
        # Base step size: 1 for integers, ~5-10% of range for floats
        base_step = 1
        if is_float:
             range_ = max_bound - min_bound
             base_step = max(1e-6, range_ * 0.05) # 5% of range, minimum step
        adjustment_magnitude = base_step # Start with base step

        strategy_key = self._get_strategy_key_from_setting(setting_path)
        target_win_rate = 0.50 # Target ~50% win rate? Adjust as needed.

        # Trend Following (MA periods)
        if strategy_key == 'TrendFollowingStrategy':
            adjustment_magnitude = 1 # Integer step for periods
            if 'Trending' in trend_regime: # Trending Market -> favor TF
                if win_rate < target_win_rate - 0.05: adjustment_direction = -1 # Shorten periods if losing (missing trends?)
                # else: Keep if performance is okay/good in trend
            else: # Ranging/Unknown Market -> penalize TF
                if win_rate < target_win_rate - 0.10: adjustment_direction = 1 # Lengthen periods significantly if losing (choppy)
            # Invert adjustment for long_term period (longer is slower)
            if 'long_term' in setting_path: adjustment_direction *= -1

        # Mean Reversion (RSI Period, Levels)
        elif strategy_key == 'MeanReversionStrategy':
            if 'RSI_PERIOD' in setting_path:
                adjustment_magnitude = 1
                if 'Ranging' in trend_regime: # Ranging Market -> favor MR
                    if win_rate < target_win_rate - 0.05: adjustment_direction = -1 # Shorten period if losing (missing reversals?)
                else: # Trending Market -> penalize MR
                    if win_rate < target_win_rate - 0.10: adjustment_direction = 1 # Lengthen period if losing (fighting trend)
            elif 'RSI_OVERBOUGHT' in setting_path: # OB Threshold
                adjustment_magnitude = 1
                if win_rate < target_win_rate: adjustment_direction = -1 # Lower threshold if losing (selling too early?)
            elif 'RSI_OVERSOLD' in setting_path: # OS Threshold
                adjustment_magnitude = 1
                if win_rate < target_win_rate: adjustment_direction = 1 # Raise threshold if losing (buying too early?)

        # Momentum
        elif strategy_key == 'MomentumStrategy':
            if 'PERIOD' in setting_path:
                adjustment_magnitude = 1
                if 'Trending' in trend_regime or vol_regime == 'High': # Momentum might work here
                    if win_rate < target_win_rate - 0.05: adjustment_direction = -1 # Faster lookback if missing moves
                else: # Ranging / Low Vol / Squeeze -> penalize Momentum
                    if win_rate < target_win_rate - 0.10: adjustment_direction = 1 # Slower lookback if false signals
            elif 'THRESHOLD' in setting_path: # Price Change Threshold
                adjustment_magnitude = max(1e-4, (max_bound - min_bound) * 0.1) # 10% of range step
                if vol_regime == 'High':
                    if win_rate < target_win_rate: adjustment_direction = 1 # Increase threshold if too sensitive
                else: # Lower Vol
                    if win_rate < target_win_rate: adjustment_direction = -1 # Decrease threshold if too insensitive
            elif 'VOLUME_MULTIPLIER' in setting_path:
                adjustment_magnitude = 0.1
                if vol_regime == 'High' and win_rate < target_win_rate:
                    adjustment_direction = 1 # Require more volume confirmation
                elif vol_regime in ['Low', 'Squeeze'] and win_rate < target_win_rate:
                    adjustment_direction = -1 # Relax volume confirmation

        # Risk Parameters (Base Multipliers/Ratio)
        elif strategy_key == 'Risk':
             adjustment_magnitude = 0.05 # Smaller steps for risk params (e.g., 0.05 for multipliers)
             if setting_path == 'TAKE_PROFIT_RR_RATIO': adjustment_magnitude = 0.1 # Slightly larger for ratio

             # Simple logic: If win rate is poor (<40%), tighten risk slightly. If good (>60%), loosen slightly.
             if win_rate < 0.40:
                 if 'STOP_LOSS' in setting_path: adjustment_direction = -1 # Tighten SL slightly (e.g., reduce ATR mult)
                 if 'TAKE_PROFIT' in setting_path: adjustment_direction = -1 # Reduce TP target slightly
             elif win_rate > 0.60:
                  if 'STOP_LOSS' in setting_path: adjustment_direction = 1 # Loosen SL slightly (controversial)
                  if 'TAKE_PROFIT' in setting_path: adjustment_direction = 1 # Increase TP target slightly

        # --- Apply Adjustment ---
        if adjustment_direction != 0:
            new_value_raw = current_value + (adjustment_direction * adjustment_magnitude)

            # Clamp within bounds
            new_value_clamped = self._clamp(new_value_raw, min_bound, max_bound)

            # Discretize/Round if necessary (integers or specific float precision)
            final_value = new_value_clamped
            if not is_float: # Integer parameter
                 final_value = int(self._discretize(new_value_clamped, step=1))
            else: # Float parameter - round to reasonable precision
                 # Infer precision from bounds or step? Or fixed precision?
                 precision = 6 # Default high precision for floats
                 if '.' in str(base_step): precision = len(str(base_step).split('.')[-1])
                 final_value = round(final_value, precision)

            # --- Cross-parameter validation (ensure logical consistency) ---
            # Example: Ensure short MA < long MA
            if setting_path == 'MOVING_AVERAGE_PERIODS.short_term':
                long_val = self._get_setting('MOVING_AVERAGE_PERIODS.long_term')
                if long_val is not None: final_value = min(final_value, long_val - 1)
            elif setting_path == 'MOVING_AVERAGE_PERIODS.long_term':
                short_val = self._get_setting('MOVING_AVERAGE_PERIODS.short_term')
                if short_val is not None: final_value = max(final_value, short_val + 1)
            # Example: Ensure RSI OS < OB
            elif setting_path == 'RSI_OVERSOLD':
                ob_val = self._get_setting('RSI_OVERBOUGHT')
                if ob_val is not None: final_value = min(final_value, ob_val - 5) # Ensure some gap
            elif setting_path == 'RSI_OVERBOUGHT':
                os_val = self._get_setting('RSI_OVERSOLD')
                if os_val is not None: final_value = max(final_value, os_val + 5) # Ensure some gap

            # Final clamp after cross-validation
            final_value = self._clamp(final_value, min_bound, max_bound)

            # --- Set New Value (if changed) ---
            # _set_setting handles type conversion and checks for actual change before logging
            self._set_setting(setting_path, final_value)

        # else: self.logger.debug(f"Optimizer: No adjustment needed for '{setting_path}' based on rules.")

    # --- State Management ---
    # Currently modifies Settings object directly. No separate state needed for optimizer itself.
    # If optimizer had internal evolving state (e.g., tracking learning rates),
    # get_state/load_state would be needed here and integrated with StateManager.