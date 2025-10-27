# managers/strategy_manager.py

import threading  # Import threading for potential future lock needs
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytz

# Import strategy classes
from strategies import MeanReversionStrategy, MLStrategy, MomentumStrategy, TrendFollowingStrategy
from utils.logger import setup_logger


class StrategyManager:
    """
    Manages strategy instances, calculates performance metrics, determines
    adaptive strategy weights per symbol based on market regime and performance,
    and aggregates signals.
    Designed to be primarily accessed and updated from the main trading loop thread.
    """

    def __init__(self, settings, portfolio_manager, regime_detector, logger=None):
        self.settings = settings
        self.portfolio_manager = portfolio_manager  # Needs PortfolioManager instance
        self.regime_detector = regime_detector  # Use the passed detector instance
        self.logger = logger or setup_logger('StrategyManager', 'logs/app.log', level=settings.LOG_LEVEL)
        self.error_logger = setup_logger('StrategyError', 'logs/error_logs/errors.log', level='ERROR')

        # --- Strategy Loading ---
        self.strategies = self._load_strategies()
        if not self.strategies:
            # If no strategies load, the bot cannot trade. Raise critical error.
            msg = 'StrategyManager: No strategies were loaded successfully based on settings. Bot cannot function.'
            self.error_logger.critical(msg)
            raise RuntimeError(msg)
        self.strategy_names = [s.__class__.__name__ for s in self.strategies]

        # --- State (Protected by lock if accessed/modified concurrently) ---
        # Performance data {symbol: {strat_name: {'trades': N, ...}}}
        self.strategy_performance = defaultdict(
            lambda: {name: self._default_perf_metrics() for name in self.strategy_names}
        )
        # Weights {symbol: {strat_name: weight}}
        self.strategy_weights = defaultdict(lambda: dict.fromkeys(self.strategy_names, 1.0))
        # --- End State ---

        self._lock = threading.Lock()  # Lock for accessing/modifying performance and weights
        # Primarily needed if update_performance called from different thread.

        # Performance Update Timing
        self.last_perf_update_time = datetime.min.replace(tzinfo=pytz.utc)  # Use aware datetime
        self.perf_update_interval = timedelta(
            minutes=getattr(settings, 'STRAT_PERF_UPDATE_INTERVAL_MIN', 30)
        )  # Configurable interval
        self.perf_lookback_days = getattr(settings, 'STRAT_PERF_LOOKBACK_DAYS', 3)
        self.min_trades_for_weighting = getattr(settings, 'STRAT_MIN_TRADES_WEIGHTING', 10)

        # --- Regime-Based Weighting Configuration ---
        # Base weights define starting bias based on perceived market conditions.
        self.regime_base_weights = {
            # Trend Regime influences trend vs mean reversion preference
            'Trending Up': {
                'TrendFollowingStrategy': 1.5,
                'MeanReversionStrategy': 0.5,
                'MomentumStrategy': 1.2,
                'MLStrategy': 1.0,
            },
            'Trending Down': {
                'TrendFollowingStrategy': 1.5,
                'MeanReversionStrategy': 0.5,
                'MomentumStrategy': 1.2,
                'MLStrategy': 1.0,
            },
            'Ranging': {
                'TrendFollowingStrategy': 0.5,
                'MeanReversionStrategy': 1.5,
                'MomentumStrategy': 0.8,
                'MLStrategy': 1.0,
            },
            # Volatility Regime adjusts overall sensitivity / confidence
            'Low': {
                'TrendFollowingStrategy': 0.8,
                'MeanReversionStrategy': 1.2,
                'MomentumStrategy': 0.7,
                'MLStrategy': 0.9,
            },
            'Normal': {
                'TrendFollowingStrategy': 1.0,
                'MeanReversionStrategy': 1.0,
                'MomentumStrategy': 1.0,
                'MLStrategy': 1.0,
            },
            'High': {
                'TrendFollowingStrategy': 1.2,
                'MeanReversionStrategy': 0.8,
                'MomentumStrategy': 1.2,
                'MLStrategy': 1.1,
            },
            'Squeeze': {
                'TrendFollowingStrategy': 0.7,
                'MeanReversionStrategy': 1.1,
                'MomentumStrategy': 0.5,
                'MLStrategy': 0.8,
            },
            # Default if regime is Unknown
            'Default': dict.fromkeys(self.strategy_names, 1.0),
        }

    def _default_perf_metrics(self):
        """Returns the default structure for performance tracking."""
        return {'trades': 0, 'wins': 0, 'total_pnl': 0.0, 'pnl_list': [], 'win_rate': 0.0, 'sharpe_ratio': 0.0}

    def _load_strategies(self):
        """Loads strategy instances based on settings."""
        strategies = []
        enabled = self.settings.ENABLED_STRATEGIES
        if not isinstance(enabled, dict):
            self.error_logger.critical('ENABLED_STRATEGIES in settings is not a dictionary.')
            return []

        self.logger.info('Loading strategies based on settings...')
        try:
            # Instantiate strategies only if enabled
            if enabled.get('trend_following', False):
                strategies.append(TrendFollowingStrategy())
            if enabled.get('mean_reversion', False):
                strategies.append(MeanReversionStrategy())
            if enabled.get('momentum', False):
                strategies.append(MomentumStrategy())
            if enabled.get('machine_learning', False):
                # Check if ML model can be loaded before adding strategy
                try:
                    ml_strategy = MLStrategy()
                    if ml_strategy.is_model_loaded:
                        strategies.append(ml_strategy)
                    else:
                        self.error_logger.error(
                            'ML Strategy enabled but model failed to load during initialization. Strategy disabled.'
                        )
                except Exception as ml_init_e:
                    self.error_logger.error(f'Failed to initialize MLStrategy: {ml_init_e}', exc_info=True)

        except Exception as e:
            # Catch errors during instantiation of any strategy
            self.error_logger.critical(f'Failed to initialize one or more strategies: {e}', exc_info=True)

        loaded_names = [s.__class__.__name__ for s in strategies]
        self.logger.info(f'StrategyManager loaded strategies: {loaded_names if loaded_names else "None"}')
        return strategies

    def get_strategies(self):
        """Returns the list of loaded strategy instances."""
        # No lock needed as self.strategies is set at init and not modified later
        return self.strategies

    def get_min_data_points(self):
        """Calculates the maximum minimum data points required by any loaded strategy."""
        min_points = 0
        for s in self.strategies:
            try:
                # Ensure min_data_points() method exists and returns numeric
                required = s.min_data_points()
                if isinstance(required, (int, float)) and required > 0:
                    min_points = max(min_points, int(required))
                else:
                    self.error_logger.warning(
                        f'{s.__class__.__name__} returned invalid min_data_points: {required}. Using fallback 200.'
                    )
                    min_points = max(min_points, 200)  # Fallback
            except Exception as e:
                self.error_logger.error(f'Error getting min_data_points from {s.__class__.__name__}: {e}')
                min_points = max(min_points, 200)  # Fallback
        # Add a small buffer
        return min_points + 5

    def update_performance_and_weights(self, current_time_utc):
        """Updates strategy performance metrics and recalculates weights per symbol (thread-safe)."""
        # Check if dynamic weighting is enabled
        if not self.settings.AUTONOMOUS_MODE or not self.settings.ENABLE_DYNAMIC_STRATEGY_WEIGHTING:
            # If disabled, ensure weights are reset to 1.0 and skip update logic
            with self._lock:
                if any(w != 1.0 for weights in self.strategy_weights.values() for w in weights.values()):
                    self.logger.info('Dynamic strategy weighting disabled. Resetting all weights to 1.0.')
                    self.strategy_weights = defaultdict(lambda: dict.fromkeys(self.strategy_names, 1.0))
            return

        # Check if it's time to update based on interval
        with self._lock:  # Access last_perf_update_time safely
            time_since_last_update = current_time_utc - self.last_perf_update_time
            if time_since_last_update < self.perf_update_interval:
                return  # Too soon to update

            # Update last update time immediately to prevent concurrent updates
            self.last_perf_update_time = current_time_utc

        self.logger.info(f'Updating strategy performance and weights (Interval: {self.perf_update_interval})...')

        # 1. Get Recent Trade History (from PM, which should be thread-safe)
        try:
            full_trade_history = self.portfolio_manager.get_trade_history()  # Get copy
            if not full_trade_history:
                self.logger.warning('StrategyManager: No trade history available for performance update.')
                return
        except Exception as e:
            self.error_logger.error(f'StrategyManager: Error getting trade history: {e}', exc_info=True)
            return

        lookback_start_time = current_time_utc - timedelta(days=self.perf_lookback_days)

        # 2. Calculate Performance Metrics per Strategy, per Symbol
        # Temporary storage for new performance data
        new_strategy_performance = defaultdict(
            lambda: {name: self._default_perf_metrics() for name in self.strategy_names}
        )

        for trade in full_trade_history:
            trade_time_utc = trade.get('time_utc')  # Expecting aware UTC datetime
            if not isinstance(trade_time_utc, datetime) or trade_time_utc.tzinfo is None:
                self.logger.warning(f'Skipping trade with invalid time for perf calc: {trade.get("exec_id", "N/A")}')
                continue  # Skip trades with invalid time

            # Filter trades within the lookback period
            if trade_time_utc >= lookback_start_time:
                symbol = trade.get('symbol')
                # Map trade strategy (e.g., 'TrendFollowing_SL') back to base strategy name
                base_name = trade.get('strategy', '').split('_')[0]
                pnl = trade.get('pnl')  # PnL should include commission cost now

                if symbol and base_name in self.strategy_names and pnl is not None:
                    perf_entry = new_strategy_performance[symbol][base_name]
                    perf_entry['trades'] += 1
                    perf_entry['total_pnl'] += pnl
                    perf_entry['pnl_list'].append(pnl)
                    if pnl > 0:
                        perf_entry['wins'] += 1

        # Calculate derived metrics (Win Rate, Sharpe Ratio - simplified)
        252 * (24 * 60 * 60 / self.settings.TIMEFRAME_SECONDS) if hasattr(
            self.settings, 'TIMEFRAME_SECONDS'
        ) else 252  # Estimate periods/year

        for symbol, symbol_perf in new_strategy_performance.items():
            for name, data in symbol_perf.items():
                trades_count = data['trades']
                if trades_count > 1:  # Need at least 2 trades for std dev
                    data['win_rate'] = data['wins'] / trades_count
                    pnl_series = pd.Series(data['pnl_list'])
                    mean_pnl = pnl_series.mean()
                    std_dev_pnl = pnl_series.std()

                    # Simple Sharpe: Mean(PnL) / StdDev(PnL) (assuming 0 risk-free rate per period)
                    if std_dev_pnl is not None and not np.isnan(std_dev_pnl) and not np.isclose(std_dev_pnl, 0.0):
                        sharpe = mean_pnl / std_dev_pnl
                        # Optional: Annualize Sharpe (careful with assumptions)
                        # annualized_sharpe = sharpe * np.sqrt(periods_per_year)
                        data['sharpe_ratio'] = sharpe
                    else:
                        data['sharpe_ratio'] = 0.0  # Undefined or zero if std dev is zero/NaN
                elif trades_count == 1:
                    data['win_rate'] = data['wins'] / trades_count
                    data['sharpe_ratio'] = 0.0  # Cannot calculate Sharpe with 1 trade
                # else keep defaults (0.0)

        # --- Update shared performance state (under lock) ---
        with self._lock:
            self.strategy_performance = new_strategy_performance

        # 3. Update Weights based on Regime and Performance for each symbol traded
        symbols_traded = list(new_strategy_performance.keys())  # Symbols with recent trades
        new_strategy_weights = defaultdict(lambda: dict.fromkeys(self.strategy_names, 1.0))

        for symbol in symbols_traded:
            symbol_perf = new_strategy_performance[symbol]  # Use the newly calculated perf
            regime_info = self.regime_detector.get_regime(symbol)  # Assumes detector is updated elsewhere
            trend_regime = regime_info.get('trend', 'Unknown')
            vol_regime = regime_info.get('volatility', 'Unknown')

            # Get base weights for trend and volatility regimes
            trend_base = self.regime_base_weights.get(trend_regime, self.regime_base_weights['Default'])
            vol_base = self.regime_base_weights.get(vol_regime, self.regime_base_weights['Default'])

            # --- Calculate Performance Modifier ---
            # Use Sharpe ratio for performance adjustment
            symbol_sharpes = {}
            valid_sharpes_exist = False
            for name, data in symbol_perf.items():
                if data['trades'] >= self.min_trades_for_weighting:
                    symbol_sharpes[name] = data['sharpe_ratio']
                    valid_sharpes_exist = True

            # Normalize Sharpe scores for weighting (e.g., scale 0 to 1, or use relative rank)
            # Simple scaling: map min Sharpe to 0.5 modifier, max Sharpe to 1.5 modifier
            perf_modifiers = dict.fromkeys(self.strategy_names, 1.0)  # Default modifier
            if valid_sharpes_exist and len(symbol_sharpes) > 1:
                min_s = min(symbol_sharpes.values())
                max_s = max(symbol_sharpes.values())
                if max_s > min_s:  # Avoid division by zero if all sharpes are equal
                    for name, sharpe in symbol_sharpes.items():
                        # Scale sharpe between 0 and 1
                        scaled_sharpe = (sharpe - min_s) / (max_s - min_s)
                        # Map scaled sharpe to modifier range (e.g., 0.5 to 1.5)
                        perf_modifiers[name] = 0.5 + scaled_sharpe
                elif max_s > 0:  # All valid sharpes are equal and positive
                    for name in symbol_sharpes:
                        perf_modifiers[name] = 1.2  # Give slight boost
                elif max_s <= 0:  # All valid sharpes are equal and non-positive
                    for name in symbol_sharpes:
                        perf_modifiers[name] = 0.8  # Give slight penalty

            # --- Calculate Final Weights ---
            total_weight_sum = 0
            temp_weights = {}
            for name in self.strategy_names:
                # Combine base weights (e.g., multiplicative or additive?) - Let's use multiplicative
                base_weight = trend_base.get(name, 1.0) * vol_base.get(name, 1.0)
                perf_modifier = perf_modifiers[name]

                final_weight = base_weight * perf_modifier
                # Ensure weight is not negative
                final_weight = max(0.01, final_weight)  # Floor weight to avoid zero/negative
                temp_weights[name] = final_weight
                total_weight_sum += final_weight

            # Normalize weights for the symbol so they average to 1.0
            if total_weight_sum > 0:
                num_strategies = len(self.strategy_names)
                norm_factor = num_strategies / total_weight_sum
                for name in temp_weights:
                    new_strategy_weights[symbol][name] = round(temp_weights[name] * norm_factor, 3)
            # else: Keep default weights (1.0) if total_weight_sum is zero

            self.logger.info(
                f'Updated Weights for {symbol} (Regime: {regime_info.get("regime", "N/A")}): {new_strategy_weights[symbol]}'
            )

        # --- Update shared weight state (under lock) ---
        with self._lock:
            self.strategy_weights = new_strategy_weights

    def aggregate_signals(self, symbol, data_df):
        """
        Generates signals from all strategies and aggregates them using current weights (thread-safe read).

        Args:
            symbol (str): The trading symbol.
            data_df (pd.DataFrame): Market data for the symbol (should be a copy).

        Returns:
            tuple: (int: final_signal, dict: individual_signals)
        """
        individual_signals = {}
        weighted_signal_sum = 0.0
        sum_of_abs_weights_for_signal = 0.0  # Sum of absolute weights of strategies producing non-zero signal

        # Check for performance/weight update schedule (uses internal lock)
        now_utc = datetime.now(pytz.utc)
        self.update_performance_and_weights(now_utc)

        # Get current weights for this symbol (thread-safe read)
        with self._lock:
            # Use defaultdict behavior to get 1.0 if symbol is new
            current_weights = self.strategy_weights[symbol].copy()

        # Get signals from each strategy
        for strategy in self.strategies:
            name = strategy.__class__.__name__
            signal = 0
            try:
                # Check data requirement before calling strategy
                min_pts = strategy.min_data_points()
                if len(data_df) >= min_pts:
                    # Pass a copy to prevent strategy from modifying the original df affecting others
                    signal = strategy.generate_signal(data_df.copy())
                else:
                    # Log only if it's unexpected (should be caught earlier?)
                    self.logger.debug(
                        f'StrategyManager: Insufficient data for {name} on {symbol} ({len(data_df)}/{min_pts})'
                    )
            except Exception as e:
                self.error_logger.error(f'Error generating signal from {name} for {symbol}: {e}', exc_info=True)
                signal = 0  # Treat error as no signal

            individual_signals[name] = signal
            weight = current_weights.get(name, 1.0)  # Default to 1.0 if somehow missing
            # Aggregate weighted signals
            if signal != 0:
                weighted_signal_sum += signal * weight
                sum_of_abs_weights_for_signal += abs(weight)  # Use absolute weight for normalization base

        # --- Final Signal Aggregation ---
        final_signal = 0
        # Normalize the weighted sum by the sum of absolute weights of contributing strategies
        if abs(sum_of_abs_weights_for_signal) > 1e-6:  # Avoid division by zero
            # Normalized signal strength (ranges roughly -1 to +1)
            normalized_signal_strength = weighted_signal_sum / sum_of_abs_weights_for_signal
            signal_threshold = self.settings.AGGREGATION_SIGNAL_THRESHOLD

            if normalized_signal_strength >= signal_threshold:
                final_signal = 1  # Buy
            elif normalized_signal_strength <= -signal_threshold:
                final_signal = -1  # Sell
            # else: Signal strength below threshold, remain neutral (0)

        # Log details only if a final signal is generated
        if final_signal != 0:
            contributing = {k: v for k, v in individual_signals.items() if v != 0}
            weights_contrib = {k: round(current_weights.get(k, 1.0), 2) for k in contributing}
            self.logger.info(
                f'Aggregated Signal for {symbol}: {final_signal} '
                f'(NormSignal: {normalized_signal_strength:.3f}, Threshold: {signal_threshold:.2f}, '
                f'Contributing: {contributing}, Weights: {weights_contrib})'
            )

        return final_signal, individual_signals

    # --- State Management (Optional but recommended for weights) ---
    def get_state(self):
        """Returns state for persistence (thread-safe)."""
        with self._lock:
            # Convert defaultdicts to regular dicts for JSON serialization
            state = {
                'strategy_weights': {k: dict(v) for k, v in self.strategy_weights.items()},
                # Performance is recalculated, maybe don't save? Or save limited version?
                'last_perf_update_time': self.last_perf_update_time.isoformat(),
            }
            return state

    def load_state(self, state):
        """Loads state from persistence (thread-safe)."""
        with self._lock:
            loaded_weights = state.get('strategy_weights', {})
            # Rebuild defaultdict structure
            self.strategy_weights = defaultdict(lambda: dict.fromkeys(self.strategy_names, 1.0))
            for symbol, weights in loaded_weights.items():
                # Ensure only weights for currently loaded strategies are applied
                self.strategy_weights[symbol] = {name: w for name, w in weights.items() if name in self.strategy_names}

            last_update_str = state.get('last_perf_update_time')
            if last_update_str:
                try:
                    self.last_perf_update_time = datetime.fromisoformat(last_update_str.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    self.last_perf_update_time = datetime.min.replace(tzinfo=pytz.utc)
            else:
                self.last_perf_update_time = datetime.min.replace(tzinfo=pytz.utc)

            self.logger.info(f'StrategyManager state loaded. Weights for {len(self.strategy_weights)} symbols.')
            # Performance will be rebuilt on the next update cycle.
