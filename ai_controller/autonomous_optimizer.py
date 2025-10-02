# ai_controller/autonomous_optimizer.py

"""
Autonomous Optimizer - Core AI Brain for Parameter Optimization

Uses Bayesian optimization to automatically tune trading parameters,
select strategies, and adjust position sizing based on market conditions.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from dataclasses import dataclass
import json

try:
    from skopt import gp_minimize
    from skopt.space import Real, Integer
    BAYESIAN_OPTIMIZATION_AVAILABLE = True
except ImportError:
    BAYESIAN_OPTIMIZATION_AVAILABLE = False
    logging.warning("scikit-optimize not available. Install with: pip install scikit-optimize")


@dataclass
class OptimizationResult:
    """Result from an optimization run"""
    optimized_params: Dict[str, Any]
    score: float
    timestamp: datetime
    iteration_count: int
    improvement_pct: float


class AutonomousOptimizer:
    """
    Autonomous AI Controller for parameter optimization

    Responsibilities:
    1. Optimize strategy parameters using Bayesian optimization
    2. Select which strategies to enable based on market regime
    3. Adjust position sizing using Kelly Criterion
    """

    def __init__(self, settings, logger=None, error_logger=None):
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.error_logger = error_logger or logging.getLogger(f"{__name__}.error")

        # Track optimization history
        self.optimization_history = []
        self.last_optimization_time = None
        self.last_strategy_selection_time = None
        self.last_position_sizing_update = None
        self.trades_since_last_optimization = 0

        # Define parameter search space (what AI can optimize)
        self.parameter_bounds = self._define_search_space()

        # Track current best parameters
        self.current_best_params = None
        self.current_best_score = -np.inf

    def _define_search_space(self) -> Dict[str, Tuple[float, float]]:
        """Define the search space for Bayesian optimization"""
        bounds = {}

        # Get bounds from settings if available
        if hasattr(self.settings, 'AUTO_OPTIMIZE_BOUNDS'):
            auto_bounds = self.settings.AUTO_OPTIMIZE_BOUNDS
            bounds.update({
                'risk_per_trade': (
                    auto_bounds.get('risk_per_trade_min', 0.005),
                    auto_bounds.get('risk_per_trade_max', 0.02)
                ),
                'stop_loss_atr_multiplier': (
                    auto_bounds.get('stop_loss_atr_min', 1.0),
                    auto_bounds.get('stop_loss_atr_max', 4.0)
                ),
                'take_profit_rr_ratio': (
                    auto_bounds.get('take_profit_rr_min', 1.5),
                    auto_bounds.get('take_profit_rr_max', 4.0)
                ),
            })
        else:
            # Default bounds if not specified
            bounds.update({
                'risk_per_trade': (0.005, 0.02),  # 0.5% to 2%
                'stop_loss_atr_multiplier': (1.0, 4.0),
                'take_profit_rr_ratio': (1.5, 4.0),
            })

        # Indicator parameters
        bounds.update({
            'rsi_period': (5, 30),
            'ma_short_period': (5, 30),
            'ma_long_period': (15, 100),
            'atr_period': (10, 20),
        })

        return bounds

    def should_optimize_parameters(self) -> bool:
        """Check if it's time to run parameter optimization"""
        if not hasattr(self.settings, 'AUTO_OPTIMIZE_INTERVAL_HOURS'):
            return False

        # Check time-based trigger
        if self.last_optimization_time is None:
            return True

        hours_since_last = (datetime.now() - self.last_optimization_time).total_seconds() / 3600
        time_trigger = hours_since_last >= self.settings.AUTO_OPTIMIZE_INTERVAL_HOURS

        # Check trade-based trigger
        min_trades = getattr(self.settings, 'AUTO_OPTIMIZE_MIN_TRADES', 50)
        trade_trigger = self.trades_since_last_optimization >= min_trades

        return time_trigger or trade_trigger

    def optimize_parameters(
        self,
        recent_performance: Dict[str, Any],
        market_data: pd.DataFrame,
        trade_history: List[Dict],
        lookback_days: int = 7
    ) -> Optional[OptimizationResult]:
        """
        Optimize all trading parameters using Bayesian optimization

        Args:
            recent_performance: Recent performance metrics
            market_data: Historical market data for backtesting
            trade_history: Recent trade history
            lookback_days: How far back to look for optimization

        Returns:
            OptimizationResult or None if optimization failed
        """
        if not BAYESIAN_OPTIMIZATION_AVAILABLE:
            self.logger.warning("Bayesian optimization not available. Using heuristic fallback.")
            return self._heuristic_optimization(recent_performance, trade_history)

        try:
            self.logger.info("Starting Bayesian parameter optimization...")

            # Filter recent trades
            cutoff_date = datetime.now() - timedelta(days=lookback_days)
            recent_trades = [
                t for t in trade_history
                if t.get('timestamp', datetime.min) >= cutoff_date
            ]

            if len(recent_trades) < 10:
                self.logger.warning(f"Only {len(recent_trades)} trades available. Need at least 10 for optimization.")
                return None

            # Define objective function
            def objective(params_array):
                params_dict = dict(zip(self.parameter_bounds.keys(), params_array))
                score = self._evaluate_parameters(params_dict, market_data, recent_trades)
                return -score  # Minimize negative (maximize score)

            # Create search space for skopt
            search_space = [
                Real(bounds[0], bounds[1], name=param_name)
                for param_name, bounds in self.parameter_bounds.items()
            ]

            # Run Bayesian optimization
            n_calls = getattr(self.settings, 'OPTIMIZATION_N_CALLS', 20)
            result = gp_minimize(
                objective,
                search_space,
                n_calls=n_calls,
                random_state=42,
                verbose=False
            )

            # Extract optimized parameters
            optimized_params = dict(zip(self.parameter_bounds.keys(), result.x))
            optimized_score = -result.fun  # Convert back to positive

            # Calculate improvement
            baseline_score = self._evaluate_parameters(
                self._get_current_params(),
                market_data,
                recent_trades
            )
            improvement_pct = ((optimized_score - baseline_score) / abs(baseline_score)) * 100 if baseline_score != 0 else 0

            # Create result
            opt_result = OptimizationResult(
                optimized_params=optimized_params,
                score=optimized_score,
                timestamp=datetime.now(),
                iteration_count=n_calls,
                improvement_pct=improvement_pct
            )

            # Update tracking
            self.optimization_history.append(opt_result)
            self.last_optimization_time = datetime.now()
            self.trades_since_last_optimization = 0

            if optimized_score > self.current_best_score:
                self.current_best_params = optimized_params
                self.current_best_score = optimized_score

            self.logger.info(
                f"Optimization complete. Score: {optimized_score:.4f}, "
                f"Improvement: {improvement_pct:.2f}%"
            )

            return opt_result

        except Exception as e:
            self.error_logger.error(f"Parameter optimization failed: {e}", exc_info=True)
            return None

    def _evaluate_parameters(
        self,
        params: Dict[str, Any],
        market_data: pd.DataFrame,
        trade_history: List[Dict]
    ) -> float:
        """
        Evaluate a parameter set based on performance metrics

        Returns a composite score (higher is better)
        """
        try:
            # Calculate metrics from trade history
            if not trade_history:
                return 0.0

            pnls = [t.get('pnl', 0) for t in trade_history if 'pnl' in t]
            if not pnls:
                return 0.0

            # Sharpe ratio approximation
            returns = np.array(pnls)
            sharpe = np.mean(returns) / (np.std(returns) + 1e-8) * np.sqrt(252)

            # Win rate
            wins = sum(1 for pnl in pnls if pnl > 0)
            win_rate = wins / len(pnls) if pnls else 0

            # Max drawdown (simplified)
            cumulative = np.cumsum(pnls)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = (cumulative - running_max)
            max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0

            # Composite score (weighted combination)
            score = (
                sharpe * 0.4 +          # 40% weight on risk-adjusted returns
                win_rate * 0.3 +         # 30% weight on win rate
                -abs(max_drawdown) * 0.3 # 30% penalty for drawdown
            )

            return score

        except Exception as e:
            self.error_logger.error(f"Parameter evaluation failed: {e}")
            return 0.0

    def _get_current_params(self) -> Dict[str, Any]:
        """Get current parameter values from settings"""
        return {
            'risk_per_trade': getattr(self.settings, 'RISK_PER_TRADE', 0.01),
            'stop_loss_atr_multiplier': getattr(self.settings, 'STOP_LOSS_ATR_MULTIPLIER', 2.0),
            'take_profit_rr_ratio': getattr(self.settings, 'TAKE_PROFIT_RR_RATIO', 2.0),
            'rsi_period': getattr(self.settings, 'RSI_PERIOD', 14),
            'ma_short_period': getattr(self.settings, 'MOVING_AVERAGE_PERIODS', {}).get('short_term', 9),
            'ma_long_period': getattr(self.settings, 'MOVING_AVERAGE_PERIODS', {}).get('long_term', 21),
            'atr_period': getattr(self.settings, 'ATR_PERIOD', 14),
        }

    def _heuristic_optimization(
        self,
        recent_performance: Dict[str, Any],
        trade_history: List[Dict]
    ) -> Optional[OptimizationResult]:
        """Fallback heuristic optimization when Bayesian opt not available"""
        self.logger.info("Using heuristic parameter optimization...")

        try:
            current_params = self._get_current_params()
            optimized_params = current_params.copy()

            # Simple heuristics based on performance
            win_rate = recent_performance.get('win_rate', 0.5)
            sharpe = recent_performance.get('sharpe_ratio', 0)

            # Adjust risk based on performance
            if win_rate > 0.6 and sharpe > 1.0:
                # Good performance, can increase risk slightly
                optimized_params['risk_per_trade'] = min(
                    current_params['risk_per_trade'] * 1.1,
                    self.parameter_bounds['risk_per_trade'][1]
                )
            elif win_rate < 0.4 or sharpe < 0:
                # Poor performance, reduce risk
                optimized_params['risk_per_trade'] = max(
                    current_params['risk_per_trade'] * 0.9,
                    self.parameter_bounds['risk_per_trade'][0]
                )

            score = self._evaluate_parameters(optimized_params, pd.DataFrame(), trade_history)

            result = OptimizationResult(
                optimized_params=optimized_params,
                score=score,
                timestamp=datetime.now(),
                iteration_count=1,
                improvement_pct=0.0
            )

            self.last_optimization_time = datetime.now()
            self.trades_since_last_optimization = 0

            return result

        except Exception as e:
            self.error_logger.error(f"Heuristic optimization failed: {e}")
            return None

    def select_strategies(
        self,
        market_regime: str,
        strategy_performance: Dict[str, Dict[str, float]]
    ) -> List[str]:
        """
        Select which strategies to enable based on market regime and performance

        Args:
            market_regime: Current market regime (trending, ranging, volatile, squeeze)
            strategy_performance: Performance metrics for each strategy

        Returns:
            List of strategy names to enable
        """
        enabled_strategies = []

        # Regime-based heuristics
        regime_strategy_map = {
            'trending': ['trend_following', 'momentum'],
            'ranging': ['mean_reversion'],
            'volatile': ['machine_learning'],
            'squeeze': ['mean_reversion', 'momentum'],
        }

        # Start with regime-appropriate strategies
        base_strategies = regime_strategy_map.get(market_regime, ['trend_following', 'mean_reversion'])

        # Filter based on recent performance
        for strategy_name in base_strategies:
            if strategy_name in strategy_performance:
                perf = strategy_performance[strategy_name]
                win_rate = perf.get('win_rate', 0)
                sharpe = perf.get('sharpe', 0)

                # Enable if performance is acceptable
                if win_rate >= 0.45 or sharpe >= 0.5:
                    enabled_strategies.append(strategy_name)

        # Always enable ML if available and performing well
        if 'machine_learning' in strategy_performance:
            ml_perf = strategy_performance['machine_learning']
            if ml_perf.get('win_rate', 0) >= 0.5:
                if 'machine_learning' not in enabled_strategies:
                    enabled_strategies.append('machine_learning')

        # Ensure at least one strategy is enabled
        if not enabled_strategies:
            enabled_strategies = ['trend_following']  # Safe default

        self.last_strategy_selection_time = datetime.now()
        self.logger.info(f"Selected strategies for {market_regime} regime: {enabled_strategies}")

        return enabled_strategies

    def adjust_position_sizing(
        self,
        recent_trades: List[Dict],
        current_volatility: float,
        current_drawdown: float
    ) -> float:
        """
        Adjust position sizing using Kelly Criterion with safety factor

        Args:
            recent_trades: Recent trade history
            current_volatility: Current market volatility (ATR/price)
            current_drawdown: Current drawdown percentage

        Returns:
            New risk_per_trade value
        """
        try:
            if len(recent_trades) < 10:
                return self.settings.RISK_PER_TRADE

            # Calculate win rate and average win/loss
            pnls = [t.get('pnl', 0) for t in recent_trades if 'pnl' in t]
            wins = [p for p in pnls if p > 0]
            losses = [abs(p) for p in pnls if p < 0]

            win_rate = len(wins) / len(pnls) if pnls else 0.5
            avg_win = np.mean(wins) if wins else 1.0
            avg_loss = np.mean(losses) if losses else 1.0

            # Kelly Criterion: f = (p*b - q) / b
            # where p = win rate, q = loss rate, b = avg_win/avg_loss
            b = avg_win / avg_loss if avg_loss > 0 else 2.0
            q = 1 - win_rate
            kelly_fraction = (win_rate * b - q) / b if b > 0 else 0

            # Apply safety factor (use 25% of Kelly)
            kelly_fraction = max(0, kelly_fraction) * 0.25

            # Get bounds
            min_risk = self.parameter_bounds['risk_per_trade'][0]
            max_risk = self.parameter_bounds['risk_per_trade'][1]

            # Adjust for volatility (reduce size in high volatility)
            volatility_factor = 1.0 / (1.0 + current_volatility * 10)

            # Adjust for drawdown (reduce size in drawdown)
            drawdown_factor = 1.0 if current_drawdown <= 0.05 else 0.7

            # Calculate new risk
            new_risk = kelly_fraction * volatility_factor * drawdown_factor
            new_risk = np.clip(new_risk, min_risk, max_risk)

            self.last_position_sizing_update = datetime.now()
            self.logger.info(
                f"Position sizing adjusted: {new_risk:.4f} "
                f"(Kelly: {kelly_fraction:.4f}, Vol factor: {volatility_factor:.2f})"
            )

            return new_risk

        except Exception as e:
            self.error_logger.error(f"Position sizing adjustment failed: {e}")
            return self.settings.RISK_PER_TRADE

    def increment_trade_counter(self):
        """Increment the trade counter for optimization triggers"""
        self.trades_since_last_optimization += 1
