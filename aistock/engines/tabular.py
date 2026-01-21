"""Tabular decision engine using Double Q-Learning with PER.

This engine uses tabular Q-learning (no neural networks) and is
suitable for discrete state spaces. Supports Double Q-Learning
and Prioritized Experience Replay.
"""

import logging
from decimal import Decimal
from typing import Any, Callable

import numpy as np

from ..data import Bar
from ..ml.agents import DoubleQAgent
from ..ml.config import DoubleQLearningConfig, PERConfig, SequenceTransition, Transition
from ..portfolio import Portfolio
from .base import BaseDecisionEngine

logger = logging.getLogger(__name__)

TransitionType = Transition | SequenceTransition


class TabularEngine(BaseDecisionEngine):
    """Tabular Q-Learning decision engine.

    Uses Double Q-Learning with optional Prioritized Experience Replay.
    Suitable for moderate state spaces with discrete features.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        double_q_config: DoubleQLearningConfig | None = None,
        per_config: PERConfig | None = None,
        learning_rate: float = 0.001,
        discount_factor: float = 0.95,
        exploration_rate: float = 0.1,
        min_confidence_threshold: float = 0.6,
        max_capital: float = 10000.0,
        max_q_table_size: int = 200_000,
        gui_log_callback: Callable[[str], None] | None = None,
    ):
        """Initialize the tabular engine.

        Args:
            portfolio: Portfolio for position tracking
            double_q_config: Double Q-Learning configuration
            per_config: PER configuration
            learning_rate: Q-Learning rate
            discount_factor: Discount factor (gamma)
            exploration_rate: Initial exploration rate
            min_confidence_threshold: Minimum confidence to trade
            max_capital: Maximum capital per trade
            max_q_table_size: Maximum Q-table entries
            gui_log_callback: Optional GUI logging callback
        """
        if double_q_config is not None and not isinstance(double_q_config, DoubleQLearningConfig):
            raise ValueError('double_q_config must be a DoubleQLearningConfig instance')
        if per_config is not None and not isinstance(per_config, PERConfig):
            raise ValueError('per_config must be a PERConfig instance')
        if double_q_config is not None:
            double_q_config.validate()
        if per_config is not None:
            per_config.validate()
        if learning_rate <= 0:
            raise ValueError('learning_rate must be positive')
        if not 0 <= discount_factor <= 1:
            raise ValueError('discount_factor must be in [0, 1]')
        if not 0 <= exploration_rate <= 1:
            raise ValueError('exploration_rate must be in [0, 1]')
        if max_q_table_size < 1:
            raise ValueError('max_q_table_size must be >= 1')

        super().__init__(
            portfolio=portfolio,
            per_config=per_config,
            min_confidence_threshold=min_confidence_threshold,
            max_capital=max_capital,
            gui_log_callback=gui_log_callback,
        )

        validated_double_q = double_q_config or DoubleQLearningConfig()
        validated_double_q.validate()
        self.double_q_config = validated_double_q

        # State dimension (will be determined from first state)
        self._state_dim: int | None = None

        # Create Double Q-Learning agent
        self._agent: DoubleQAgent | None = None
        self._learning_rate = learning_rate
        self._discount_factor = discount_factor
        self._exploration_rate = exploration_rate
        self._max_q_table_size = max_q_table_size

    def _ensure_agent(self, state_dim: int) -> DoubleQAgent:
        """Ensure agent is initialized with correct state dimension.

        Args:
            state_dim: State feature dimension

        Returns:
            Initialized agent
        """
        if self._agent is None or self._state_dim != state_dim:
            self._state_dim = state_dim
            self._agent = DoubleQAgent(
                state_dim=state_dim,
                config=self.double_q_config,
                learning_rate=self._learning_rate,
                discount_factor=self._discount_factor,
                exploration_rate=self._exploration_rate,
                max_q_table_size=self._max_q_table_size,
            )
        return self._agent

    def evaluate_opportunity(
        self,
        symbol: str,
        bars: list[Bar],
        last_prices: dict[str, Decimal],
    ) -> dict[str, Any]:
        """Evaluate a trading opportunity.

        Args:
            symbol: Trading symbol
            bars: Historical bars
            last_prices: Current prices

        Returns:
            Decision dictionary
        """
        if len(bars) < 20:
            return {
                'should_trade': False,
                'action': {},
                'confidence': 0.0,
                'state': {},
                'reason': 'Insufficient bars',
            }

        # Extract state features
        state = self._extract_state(symbol, bars, last_prices)
        state_array = self._state_to_array(state)

        # Ensure agent is initialized
        agent = self._ensure_agent(len(state_array))

        # Get action from agent
        action_name = agent.select_action(state_array, training=True)

        # Get Q-values for confidence estimation
        q_values = agent.get_q_values(state_array)
        max_q = max(q_values.values())
        min_q = min(q_values.values())

        # Confidence based on Q-value spread
        q_spread = max_q - min_q
        confidence = min(1.0, max(0.0, 0.5 + q_spread))

        # Map action to signal
        signal_map = {
            'BUY': 1,
            'SELL': -1,
            'HOLD': 0,
            'INCREASE_SIZE': 1,
            'DECREASE_SIZE': -1,
        }
        signal = signal_map.get(action_name, 0)

        # Determine if we should trade
        should_trade = action_name not in ('HOLD',) and confidence >= self.min_confidence_threshold

        # Store for learning
        self.last_state = state
        self.last_action = action_name

        return {
            'should_trade': should_trade,
            'action': {
                'signal': signal,
                'signal_name': action_name,
                'size_fraction': min(1.0, confidence),
            },
            'confidence': confidence,
            'state': state,
            'reason': f'{action_name} (Q={q_values[action_name]:.3f}, conf={confidence:.2f})',
        }

    def _extract_state(
        self,
        symbol: str,
        bars: list[Bar],
        last_prices: dict[str, Decimal],
    ) -> dict[str, Any]:
        """Extract state features from market data.

        Args:
            symbol: Trading symbol
            bars: Historical bars
            last_prices: Current prices

        Returns:
            State feature dictionary
        """
        # Get recent bars
        recent = bars[-20:]

        # Price features
        prices = [float(b.close) for b in recent]
        price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0

        # Volume features
        volumes = [float(b.volume) for b in recent if b.volume > 0]
        avg_volume = np.mean(volumes) if volumes else 1
        vol_ratio = float(recent[-1].volume) / avg_volume if avg_volume > 0 else 1

        # Trend (simple moving average comparison)
        sma_5 = np.mean(prices[-5:])
        sma_20 = np.mean(prices)
        trend = 'up' if sma_5 > sma_20 else 'down' if sma_5 < sma_20 else 'neutral'

        # Volatility
        returns = np.diff(prices) / prices[:-1]
        volatility = np.std(returns) if len(returns) > 1 else 0
        vol_level = 'high' if volatility > 0.02 else 'low' if volatility < 0.005 else 'normal'

        # Position
        position = float(self.portfolio.position(symbol).quantity)
        equity = float(self.portfolio.get_equity(last_prices) or 10000)
        current_price = float(last_prices.get(symbol, Decimal('1')))
        position_pct = (position * current_price) / equity if equity > 0 else 0

        # Discretize for tabular Q-learning
        return {
            'price_change_bin': self._discretize(float(price_change), -0.05, 0.05, 10),
            'volume_bin': self._discretize(float(np.float64(vol_ratio)), 0.5, 2.0, 5),
            'position_bin': self._discretize(float(position_pct), -0.5, 0.5, 5),
            'trend': trend,
            'volatility': vol_level,
        }

    def _discretize(self, value: float, min_val: float, max_val: float, bins: int) -> int:
        """Discretize a continuous value into bins.

        Args:
            value: Value to discretize
            min_val: Minimum value
            max_val: Maximum value
            bins: Number of bins

        Returns:
            Bin index
        """
        if value <= min_val:
            return 0
        if value >= max_val:
            return bins - 1

        range_size = max_val - min_val
        bin_size = range_size / bins
        bin_idx = int((value - min_val) / bin_size)

        return min(bin_idx, bins - 1)

    def _get_agent_action(self, state: dict[str, Any], training: bool = True) -> str:
        """Get action from the Double Q agent.

        Args:
            state: State dictionary
            training: Whether to use exploration

        Returns:
            Action name
        """
        state_array = self._state_to_array(state)
        agent = self._ensure_agent(len(state_array))
        return agent.select_action(state_array, training)

    def _update_agent(self, transitions: list[TransitionType], weights: list[float]) -> dict[str, float]:
        """Update the Double Q agent.

        Args:
            transitions: Batch of transitions
            weights: Importance sampling weights

        Returns:
            Training metrics
        """
        if self._agent is None:
            return {'loss': 0.0}

        return self._agent.update(transitions, weights)

    def _get_td_errors(self, transitions: list[TransitionType]) -> list[float]:
        """Get TD errors for PER priority updates.

        Args:
            transitions: Batch of transitions

        Returns:
            List of TD errors
        """
        if self._agent is None:
            return [1.0] * len(transitions)

        return self._agent.get_td_errors(transitions)

    def _save_agent_state(self, filepath: str) -> None:
        """Save agent state.

        Args:
            filepath: Path to save
        """
        if self._agent is not None:
            self._agent.save_state(filepath)

    def _load_agent_state(self, filepath: str) -> bool:
        """Load agent state.

        Args:
            filepath: Path to load from

        Returns:
            True if successful
        """
        # Need to know state dimension to initialize agent
        # Will be initialized on first evaluate_opportunity
        if self._agent is not None:
            return self._agent.load_state(filepath)

        # Try to load and infer state dimension
        import ast
        import json
        from pathlib import Path

        path = Path(filepath)
        if not path.exists():
            return False

        try:
            with open(path) as f:
                data = json.load(f)

            # Infer state dimension from Q-table keys
            q1 = data.get('q1', data.get('q_values', {}))
            if q1:
                first_key = next(iter(q1.keys()))
                # Parse state array from key
                state_list = ast.literal_eval(first_key)
                if not isinstance(state_list, (list, tuple)) or not state_list:
                    raise ValueError('Invalid state key format')
                if not all(isinstance(value, (int, float)) for value in state_list):
                    raise TypeError('State key must contain numeric values')
                state_dim = len(state_list)

                agent = self._ensure_agent(state_dim)
                return agent.load_state(filepath)

            return False

        except Exception as e:
            logger.error(f'Failed to load agent state: {e}')
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get engine statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            'engine': 'TabularEngine',
            'algorithm': 'double_q_learning',
            'session_trades': self.session_trades,
        }

        if self._agent is not None:
            stats.update(self._agent.get_stats())

        return stats
