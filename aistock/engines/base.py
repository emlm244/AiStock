"""Base decision engine with shared functionality.

Provides common implementation for DecisionEngineProtocol methods
that are shared across all engine types.
"""

import logging
import threading
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, TypedDict

from ..data import Bar
from ..ml.buffers import PrioritizedReplayBuffer, UniformReplayBuffer
from ..ml.config import PERConfig, SequenceTransition, Transition
from ..portfolio import Portfolio

logger = logging.getLogger(__name__)

TransitionType = Transition | SequenceTransition


class TradeRecord(TypedDict):
    """Record of a trade for history tracking."""

    timestamp: datetime
    symbol: str
    quantity: float
    price: float
    pnl: float
    position_before: float
    position_after: float


class BaseDecisionEngine(ABC):
    """Abstract base class for decision engines.

    Implements common functionality for DecisionEngineProtocol while
    delegating algorithm-specific behavior to subclasses.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        per_config: PERConfig | None = None,
        min_confidence_threshold: float = 0.6,
        max_capital: float = 10000.0,
        gui_log_callback: Callable[[str], None] | None = None,
    ):
        """Initialize the base engine.

        Args:
            portfolio: Portfolio for position and equity tracking
            per_config: Optional PER configuration for experience replay
            min_confidence_threshold: Minimum confidence to trade
            max_capital: Maximum capital per trade
            gui_log_callback: Optional callback for GUI logging
        """
        self.portfolio = portfolio
        self.min_confidence_threshold = min_confidence_threshold
        self.max_capital = max_capital
        self.gui_log_callback = gui_log_callback

        # Experience replay buffer
        self.per_config = per_config
        if per_config and per_config.enable:
            self._replay_buffer: PrioritizedReplayBuffer | UniformReplayBuffer = PrioritizedReplayBuffer(per_config)
        else:
            self._replay_buffer = UniformReplayBuffer(capacity=100_000)

        # Trade history
        self.trade_history: deque[TradeRecord] = deque(maxlen=10_000)

        # Session tracking
        self.session_start_time: datetime | None = None
        self.session_trades = 0

        # Last state/action for learning
        self.last_state: dict[str, Any] | None = None
        self.last_action: str | None = None

        # Thread safety
        self._lock = threading.Lock()

        # Fill counter for batch training
        self._fill_count = 0

    @abstractmethod
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
            last_prices: Current prices for all symbols

        Returns:
            Decision dict with should_trade, action, confidence, state, reason
        """
        ...

    @abstractmethod
    def _get_agent_action(self, state: dict[str, Any], training: bool = True) -> str:
        """Get action from the underlying RL agent.

        Args:
            state: Current state dictionary
            training: Whether to use exploration

        Returns:
            Action name
        """
        ...

    @abstractmethod
    def _update_agent(self, transitions: list[TransitionType], weights: list[float]) -> dict[str, float]:
        """Update the RL agent with a batch of transitions.

        Args:
            transitions: Batch of transitions
            weights: Importance sampling weights

        Returns:
            Training metrics
        """
        ...

    @abstractmethod
    def _save_agent_state(self, filepath: str) -> None:
        """Save agent-specific state.

        Args:
            filepath: Path to save state
        """
        ...

    @abstractmethod
    def _load_agent_state(self, filepath: str) -> bool:
        """Load agent-specific state.

        Args:
            filepath: Path to load state from

        Returns:
            True if loaded successfully
        """
        ...

    def register_trade_intent(
        self,
        symbol: str,
        timestamp: datetime,
        decision: dict[str, Any],
        target_notional: float,
        target_quantity: float,
    ) -> None:
        """Log trade intent for learning.

        Args:
            symbol: Trading symbol
            timestamp: Intent timestamp
            decision: Decision dictionary from evaluate_opportunity
            target_notional: Target notional value
            target_quantity: Target quantity
        """
        with self._lock:
            self.last_state = decision.get('state')
            self.last_action = decision.get('action', {}).get('signal_name', 'HOLD')

        logger.debug(f'Registered intent: {symbol} {self.last_action} qty={target_quantity} notional={target_notional}')

    def handle_fill(
        self,
        symbol: str,
        timestamp: datetime,
        fill_price: float,
        realised_pnl: float,
        signed_quantity: float,
        previous_position: float,
        new_position: float,
    ) -> None:
        """Handle fill and update learning.

        Args:
            symbol: Trading symbol
            timestamp: Fill timestamp
            fill_price: Fill price
            realised_pnl: Realized P&L
            signed_quantity: Signed fill quantity
            previous_position: Position before fill
            new_position: Position after fill
        """
        with self._lock:
            # Record trade
            self.trade_history.append(
                TradeRecord(
                    timestamp=timestamp,
                    symbol=symbol,
                    quantity=float(signed_quantity),
                    price=fill_price,
                    pnl=realised_pnl,
                    position_before=previous_position,
                    position_after=new_position,
                )
            )
            self.session_trades += 1

            # Create transition for replay buffer
            if self.last_state is not None and self.last_action is not None:
                # Calculate reward (can be customized in subclass)
                reward = self._calculate_reward(realised_pnl, fill_price, abs(signed_quantity))

                # Create next state (approximation)
                next_state = self._create_next_state(new_position, fill_price)

                # Episode done if position closed
                done = abs(new_position) < 0.01

                # Create transition
                transition = self._build_transition(reward, next_state, done)

                # Add to replay buffer
                self._replay_buffer.add(transition)

                # Batch training
                self._fill_count += 1
                train_freq = self.per_config.train_frequency if self.per_config else 4
                if self._fill_count >= train_freq:
                    self._maybe_train_batch()
                    self._fill_count = 0

        logger.debug(f'Handled fill: {symbol} qty={signed_quantity} price={fill_price} pnl={realised_pnl}')

    def _calculate_reward(self, pnl: float, price: float, quantity: float) -> float:
        """Calculate reward for a fill.

        Can be overridden in subclasses for custom reward shaping.

        Args:
            pnl: Realized P&L
            price: Fill price
            quantity: Absolute quantity

        Returns:
            Reward value
        """
        # Simple P&L-based reward, normalized
        position_value = price * quantity
        if position_value > 0:
            return pnl / position_value
        return 0.0

    def _create_next_state(self, new_position: float, fill_price: float) -> dict[str, Any]:
        """Create approximate next state after fill.

        Args:
            new_position: New position after fill
            fill_price: Fill price

        Returns:
            Next state dictionary
        """
        # Copy last state and update position
        if self.last_state is None:
            return {'position_pct': 0.0}

        next_state = dict(self.last_state)

        # Update position percentage
        equity = float(self.portfolio.get_equity({}) or 10000)
        if equity > 0:
            position_notional = new_position * fill_price
            next_state['position_pct'] = position_notional / equity
        else:
            next_state['position_pct'] = 0.0

        return next_state

    def _build_transition(
        self,
        reward: float,
        next_state: dict[str, Any],
        done: bool,
    ) -> TransitionType:
        """Build a replay buffer transition.

        Subclasses can override to include richer state (e.g., sequences).
        """
        return Transition(
            state=self._state_to_array(self.last_state or {}),
            action=self.last_action or 'HOLD',
            reward=reward,
            next_state=self._state_to_array(next_state),
            done=done,
        )

    def _state_to_array(self, state: dict[str, Any]) -> Any:
        """Convert state dictionary to numpy array.

        Can be overridden in subclasses for custom state representation.

        Args:
            state: State dictionary

        Returns:
            Numpy array representation
        """
        import numpy as np

        # Extract numeric values in consistent order
        values = []
        for key in sorted(state.keys()):
            val = state[key]
            if isinstance(val, (int, float)):
                values.append(float(val))
            elif isinstance(val, str):
                # Hash strings to numeric values
                values.append(float(hash(val) % 1000) / 1000)

        return np.array(values, dtype=np.float32)

    def _maybe_train_batch(self) -> None:
        """Train on a batch if replay buffer has enough samples."""
        batch_size = self.per_config.batch_size if self.per_config else 32

        if not self._replay_buffer.is_ready(batch_size):
            return

        try:
            transitions, weights, indices = self._replay_buffer.sample(batch_size)
            metrics = self._update_agent(transitions, weights)

            # Update priorities for PER
            if isinstance(self._replay_buffer, PrioritizedReplayBuffer):
                # Get TD errors from agent
                td_errors = self._get_td_errors(transitions)
                self._replay_buffer.update_priorities(indices, td_errors)

            logger.debug(f'Trained batch: loss={metrics.get("loss", 0):.4f}')

        except Exception as e:
            logger.error(f'Batch training failed: {e}', exc_info=True)

    def _get_td_errors(self, transitions: list[TransitionType]) -> list[float]:
        """Get TD errors from agent for PER priority updates.

        Args:
            transitions: Batch of transitions

        Returns:
            List of absolute TD errors
        """
        # Default implementation returns uniform errors
        # Subclasses should override with actual TD error calculation
        return [1.0] * len(transitions)

    def start_session(self) -> dict[str, Any]:
        """Start a new trading session.

        Returns:
            Session start info
        """
        self.session_start_time = datetime.now(timezone.utc)
        self.session_trades = 0

        return {
            'start_time': self.session_start_time.isoformat(),
            'engine': self.__class__.__name__,
        }

    def end_session(self) -> dict[str, Any]:
        """End trading session and return stats.

        Returns:
            Session statistics
        """
        # Calculate session P&L
        session_pnl = sum(t['pnl'] for t in self.trade_history)

        stats = {
            'start_time': self.session_start_time.isoformat() if self.session_start_time else None,
            'end_time': datetime.now(timezone.utc).isoformat(),
            'total_trades': self.session_trades,
            'session_pnl': session_pnl,
            'engine': self.__class__.__name__,
        }

        return stats

    def save_state(self, filepath: str) -> None:
        """Save learned state.

        Args:
            filepath: Path to save state
        """
        self._save_agent_state(filepath)

    def load_state(self, filepath: str) -> bool:
        """Load learned state.

        Args:
            filepath: Path to load state from

        Returns:
            True if loaded successfully
        """
        return self._load_agent_state(filepath)
