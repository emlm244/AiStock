"""Neural decision engine using Dueling DQN.

This engine uses PyTorch neural networks with the Dueling DQN
architecture for Q-value estimation.
"""

import logging
from decimal import Decimal
from typing import Any, Callable

import numpy as np

from ..data import Bar
from ..ml.agents import DQNAgent
from ..ml.config import DuelingDQNConfig, PERConfig, Transition
from ..portfolio import Portfolio
from .base import BaseDecisionEngine

logger = logging.getLogger(__name__)


class NeuralEngine(BaseDecisionEngine):
    """Neural network decision engine using Dueling DQN.

    Uses deep neural networks for Q-value function approximation,
    with separate value and advantage streams.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        dqn_config: DuelingDQNConfig | None = None,
        per_config: PERConfig | None = None,
        state_dim: int = 20,
        learning_rate: float = 1e-4,
        discount_factor: float = 0.95,
        exploration_rate: float = 0.1,
        min_confidence_threshold: float = 0.6,
        max_capital: float = 10000.0,
        device: str = 'auto',
        gui_log_callback: Callable[[str], None] | None = None,
    ):
        """Initialize the neural engine.

        Args:
            portfolio: Portfolio for position tracking
            dqn_config: Dueling DQN configuration
            per_config: PER configuration
            state_dim: State feature dimension
            learning_rate: Learning rate
            discount_factor: Discount factor
            exploration_rate: Initial exploration rate
            min_confidence_threshold: Minimum confidence to trade
            max_capital: Maximum capital per trade
            device: Device preference ('auto', 'cpu', 'cuda')
            gui_log_callback: Optional GUI logging callback
        """
        super().__init__(
            portfolio=portfolio,
            per_config=per_config,
            min_confidence_threshold=min_confidence_threshold,
            max_capital=max_capital,
            gui_log_callback=gui_log_callback,
        )

        self.dqn_config = dqn_config or DuelingDQNConfig()
        self.state_dim = state_dim

        # Create DQN agent
        self._agent = DQNAgent(
            state_dim=state_dim,
            config=self.dqn_config,
            learning_rate=learning_rate,
            discount_factor=discount_factor,
            exploration_rate=exploration_rate,
            device=device,
        )

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

        # Extract continuous state features (no discretization)
        state = self._extract_state(symbol, bars, last_prices)
        state_array = np.array(list(state.values()), dtype=np.float32)

        # Pad or truncate to expected dimension
        if len(state_array) < self.state_dim:
            state_array = np.pad(state_array, (0, self.state_dim - len(state_array)))
        elif len(state_array) > self.state_dim:
            state_array = state_array[: self.state_dim]

        # Get action from agent
        action_name = self._agent.select_action(state_array, training=True)

        # Get Q-values for confidence
        q_values = self._agent.get_q_values(state_array)
        max_q = max(q_values.values())
        min_q = min(q_values.values())

        # Confidence from Q-value spread (softmax-like)
        q_spread = max_q - min_q
        confidence = min(1.0, max(0.0, 0.5 + q_spread * 0.5))

        # Map action to signal
        signal_map = {
            'BUY': 1,
            'SELL': -1,
            'HOLD': 0,
            'INCREASE_SIZE': 1,
            'DECREASE_SIZE': -1,
        }
        signal = signal_map.get(action_name, 0)

        should_trade = action_name not in ('HOLD',) and confidence >= self.min_confidence_threshold

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
    ) -> dict[str, float]:
        """Extract continuous state features.

        Args:
            symbol: Trading symbol
            bars: Historical bars
            last_prices: Current prices

        Returns:
            State feature dictionary (all floats)
        """
        recent = bars[-50:] if len(bars) >= 50 else bars

        # Price features
        prices = [float(b.close) for b in recent]

        # Returns at various lookbacks
        features: dict[str, float] = {}

        for lookback in [1, 5, 10, 20]:
            if len(prices) > lookback:
                ret = (prices[-1] - prices[-lookback - 1]) / prices[-lookback - 1]
                features[f'return_{lookback}'] = np.clip(ret, -0.1, 0.1)
            else:
                features[f'return_{lookback}'] = 0.0

        # Volume features
        volumes = [float(b.volume) for b in recent if b.volume > 0]
        if volumes:
            avg_vol = np.mean(volumes)
            features['vol_ratio'] = float(np.clip(volumes[-1] / avg_vol if avg_vol > 0 else 1, 0, 3))
        else:
            features['vol_ratio'] = 1.0

        # Volatility (rolling std of returns)
        if len(prices) > 5:
            returns = np.diff(prices[-20:]) / prices[-20:-1]
            features['volatility'] = float(np.float64(np.clip(np.std(returns), 0, 0.1)))
        else:
            features['volatility'] = 0.01

        # Trend indicators
        if len(prices) >= 20:
            sma_5 = np.mean(prices[-5:])
            sma_20 = np.mean(prices[-20:])
            features['trend'] = float(np.clip((sma_5 - sma_20) / sma_20, -0.05, 0.05))
        else:
            features['trend'] = 0.0

        # RSI approximation
        if len(prices) > 14:
            deltas = np.diff(prices[-15:])
            gains = np.mean([d for d in deltas if d > 0]) if any(d > 0 for d in deltas) else 0
            losses = np.mean([-d for d in deltas if d < 0]) if any(d < 0 for d in deltas) else 0
            if losses > 0:
                rs = gains / losses
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 100 if gains > 0 else 50
            features['rsi'] = (rsi - 50) / 50  # Normalize to [-1, 1]
        else:
            features['rsi'] = 0.0

        # Position features
        position = float(self.portfolio.position(symbol))
        equity = float(self.portfolio.get_equity(last_prices) or 10000)
        current_price = float(last_prices.get(symbol, Decimal('1')))
        features['position_pct'] = np.clip((position * current_price) / equity, -1, 1)

        return features

    def _state_to_array(self, state: dict[str, Any]) -> np.ndarray:
        """Convert state dict to array.

        Args:
            state: State dictionary

        Returns:
            Numpy array
        """
        values = [float(v) for v in state.values() if isinstance(v, (int, float))]
        arr = np.array(values, dtype=np.float32)

        # Pad to state_dim
        if len(arr) < self.state_dim:
            arr = np.pad(arr, (0, self.state_dim - len(arr)))
        elif len(arr) > self.state_dim:
            arr = arr[: self.state_dim]

        return arr

    def _get_agent_action(self, state: dict[str, Any], training: bool = True) -> str:
        """Get action from DQN agent.

        Args:
            state: State dictionary
            training: Whether to explore

        Returns:
            Action name
        """
        state_array = self._state_to_array(state)
        return self._agent.select_action(state_array, training)

    def _update_agent(self, transitions: list[Transition], weights: list[float]) -> dict[str, float]:
        """Update the DQN agent.

        Args:
            transitions: Batch of transitions
            weights: Importance sampling weights

        Returns:
            Training metrics
        """
        return self._agent.update(transitions, weights)

    def _get_td_errors(self, transitions: list[Transition]) -> list[float]:
        """Get TD errors for PER.

        Args:
            transitions: Batch of transitions

        Returns:
            List of TD errors
        """
        return self._agent.get_td_errors(transitions)

    def _save_agent_state(self, filepath: str) -> None:
        """Save agent state.

        Args:
            filepath: Path to save
        """
        self._agent.save_state(filepath)

    def _load_agent_state(self, filepath: str) -> bool:
        """Load agent state.

        Args:
            filepath: Path to load from

        Returns:
            True if successful
        """
        return self._agent.load_state(filepath)

    def get_stats(self) -> dict[str, Any]:
        """Get engine statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            'engine': 'NeuralEngine',
            'algorithm': 'dueling_dqn',
            'session_trades': self.session_trades,
        }
        stats.update(self._agent.get_stats())
        return stats
