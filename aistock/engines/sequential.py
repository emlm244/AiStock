"""Sequential decision engine using LSTM or Transformer.

This engine uses recurrent or attention-based neural networks
to capture temporal patterns in market data.
"""

import logging
import math
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

import numpy as np

from ..data import Bar
from ..ml.agents import SequentialAgent
from ..ml.config import PERConfig, SequenceTransition, SequentialConfig, Transition
from ..portfolio import Portfolio
from .base import BaseDecisionEngine

logger = logging.getLogger(__name__)

TransitionType = Transition | SequenceTransition


class SequentialEngine(BaseDecisionEngine):
    """Sequential decision engine using LSTM or Transformer.

    Processes sequences of market states to capture temporal patterns
    for improved trading decisions.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        seq_config: SequentialConfig | None = None,
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
        """Initialize the sequential engine.

        Args:
            portfolio: Portfolio for position tracking
            seq_config: Sequential model configuration
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

        self.seq_config = seq_config or SequentialConfig()
        self.state_dim = state_dim

        # Create sequential agent
        self._agent = SequentialAgent(
            state_dim=state_dim,
            config=self.seq_config,
            learning_rate=learning_rate,
            discount_factor=discount_factor,
            exploration_rate=exploration_rate,
            device=device,
        )
        self._last_state_sequence: np.ndarray | None = None

    def register_trade_intent(
        self,
        symbol: str,
        timestamp: datetime,
        decision: dict[str, Any],
        target_notional: float,
        target_quantity: float,
    ) -> None:
        """Log trade intent and snapshot sequence context."""
        super().register_trade_intent(symbol, timestamp, decision, target_notional, target_quantity)
        self._last_state_sequence = self._agent.sequence_buffer.get_sequence()

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

        # Get action from sequential agent (maintains internal sequence buffer)
        action_name = self._agent.select_action(state_array, training=True)

        # Get Q-values for confidence
        q_values = self._agent.get_q_values(state_array)
        max_q = max(q_values.values())
        min_q = min(q_values.values())

        # Confidence uses a bounded mapping; assumes normalized Q-spreads near 1.0.
        q_spread = max_q - min_q
        expected_max_spread = 1.0
        normalized_spread = q_spread / expected_max_spread if expected_max_spread > 0 else q_spread
        confidence = 1.0 / (1.0 + math.exp(-2.0 * normalized_spread))

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
            'reason': f'{action_name} (Q={q_values[action_name]:.3f}, conf={confidence:.2f}, seq={self._agent.config.model_type})',
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
            State feature dictionary
        """
        # Use most recent bar for current state
        # Sequential model handles temporal context internally
        recent = bars[-50:] if len(bars) >= 50 else bars
        prices = [float(b.close) for b in recent]

        features: dict[str, float] = {}

        # Price features
        if len(prices) >= 2:
            features['price_change'] = np.clip((prices[-1] - prices[-2]) / prices[-2], -0.05, 0.05)
        else:
            features['price_change'] = 0.0

        # Multi-scale returns
        for lookback in [1, 5, 10, 20]:
            if len(prices) > lookback:
                ret = (prices[-1] - prices[-lookback - 1]) / prices[-lookback - 1]
                features[f'return_{lookback}'] = np.clip(ret, -0.1, 0.1)
            else:
                features[f'return_{lookback}'] = 0.0

        # Volume
        volumes = [float(b.volume) for b in recent if b.volume > 0]
        if volumes:
            avg_vol = np.mean(volumes)
            features['vol_ratio'] = float(np.clip(volumes[-1] / avg_vol if avg_vol > 0 else 1, 0, 3))
        else:
            features['vol_ratio'] = 1.0

        # Volatility
        if len(prices) >= 2:
            window = min(20, len(prices))
            window_prices = prices[-window:]
            returns = np.diff(window_prices) / window_prices[:-1]
            features['volatility'] = np.clip(np.std(returns), 0, 0.1).item() if len(returns) else 0.01
        else:
            features['volatility'] = 0.01

        # Trend
        if len(prices) >= 20:
            sma_5 = np.mean(prices[-5:])
            sma_20 = np.mean(prices[-20:])
            features['trend'] = np.clip((sma_5 - sma_20) / sma_20, -0.05, 0.05).item()
        else:
            features['trend'] = 0.0

        # RSI approximation
        if len(prices) > 14:
            deltas = np.diff(prices[-15:])
            gains_list = [d for d in deltas if d > 0]
            losses_list = [-d for d in deltas if d < 0]
            gains = float(np.mean(gains_list)) if gains_list else 0.0
            losses = float(np.mean(losses_list)) if losses_list else 0.0
            if losses > 0:
                rs = gains / losses
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 100.0 if gains > 0 else 50.0
            features['rsi'] = float((rsi - 50) / 50)
        else:
            features['rsi'] = 0.0

        # Position
        position = float(self.portfolio.position(symbol).quantity)
        equity = float(self.portfolio.get_equity(last_prices) or 10000)
        current_price = float(last_prices.get(symbol, Decimal('1')))
        features['position_pct'] = float(np.clip((position * current_price) / equity, -1, 1))

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

    def _build_transition(
        self,
        reward: float,
        next_state: dict[str, Any],
        done: bool,
    ) -> SequenceTransition:
        """Build a sequence-aware transition for replay."""
        state_sequence = self._last_state_sequence or self._agent.sequence_buffer.get_sequence()
        next_state_array = self._state_to_array(next_state)
        if len(state_sequence) > 0:
            next_state_sequence = np.vstack([state_sequence[1:], next_state_array])
        else:
            next_state_sequence = np.expand_dims(next_state_array, axis=0)

        return SequenceTransition(
            state_sequence=state_sequence,
            action=self.last_action or 'HOLD',
            reward=reward,
            next_state_sequence=next_state_sequence,
            done=done,
        )

    def _get_agent_action(self, state: dict[str, Any], training: bool = True) -> str:
        """Get action from sequential agent.

        Args:
            state: State dictionary
            training: Whether to explore

        Returns:
            Action name
        """
        state_array = self._state_to_array(state)
        return self._agent.select_action(state_array, training)

    def _update_agent(self, transitions: list[TransitionType], weights: list[float]) -> dict[str, float]:
        """Update the sequential agent.

        Args:
            transitions: Batch of transitions
            weights: Importance sampling weights

        Returns:
            Training metrics
        """
        return self._agent.update(transitions, weights)

    def _get_td_errors(self, transitions: list[TransitionType]) -> list[float]:
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

    def reset_sequence(self) -> None:
        """Reset the sequence buffer (call at episode/session start)."""
        self._agent.reset_sequence()
        self._last_state_sequence = None

    def start_session(self) -> dict[str, Any]:
        """Start a new trading session.

        Returns:
            Session start info
        """
        # Reset sequence buffer at session start
        self.reset_sequence()
        return super().start_session()

    def get_stats(self) -> dict[str, Any]:
        """Get engine statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            'engine': 'SequentialEngine',
            'algorithm': f'sequential_{self.seq_config.model_type}',
            'model_type': self.seq_config.model_type,
            'sequence_length': self.seq_config.sequence_length,
            'session_trades': self.session_trades,
        }
        stats.update(self._agent.get_stats())
        return stats
