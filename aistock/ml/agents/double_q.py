"""Double Q-Learning agent (tabular implementation).

Uses two Q-tables to reduce overestimation bias:
- Q1 selects the best action (argmax)
- Q2 evaluates that action's value
- Tables are updated alternately

Reference: van Hasselt et al. (2010) "Double Q-learning"
"""

import json
import logging
import random
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from ..config import DoubleQLearningConfig, SequenceTransition, Transition
from .base import BaseAgent

logger = logging.getLogger(__name__)

TransitionType = Transition | SequenceTransition


def _hash_state(state: np.ndarray) -> str:
    """Hash state array to string key for Q-table lookup.

    Args:
        state: State feature vector

    Returns:
        String key for dictionary lookup
    """
    # Round to reduce floating point noise
    rounded = np.round(state, decimals=4)
    return str(rounded.tolist())


class DoubleQAgent(BaseAgent):
    """Double Q-Learning agent with tabular Q-values.

    Maintains two Q-tables and alternates updates between them.
    Action selection uses Q1, value estimation uses Q2 (or vice versa).
    """

    def __init__(
        self,
        state_dim: int,
        config: DoubleQLearningConfig | None = None,
        learning_rate: float = 0.001,
        discount_factor: float = 0.95,
        exploration_rate: float = 0.1,
        exploration_decay: float = 0.995,
        min_exploration_rate: float = 0.05,
        max_q_table_size: int = 200_000,
    ):
        """Initialize the Double Q-Learning agent.

        Args:
            state_dim: Dimension of state feature vector
            config: Optional DoubleQLearningConfig
            learning_rate: Learning rate (alpha)
            discount_factor: Discount factor (gamma)
            exploration_rate: Initial exploration rate (epsilon)
            exploration_decay: Exploration decay per episode
            min_exploration_rate: Minimum exploration rate
            max_q_table_size: Maximum Q-table entries before LRU eviction
        """
        super().__init__(
            state_dim=state_dim,
            learning_rate=learning_rate,
            discount_factor=discount_factor,
            exploration_rate=exploration_rate,
            exploration_decay=exploration_decay,
            min_exploration_rate=min_exploration_rate,
        )

        self.config = config or DoubleQLearningConfig()
        self.max_q_table_size = max_q_table_size

        # Two Q-tables with LRU eviction
        self._q1: OrderedDict[str, dict[str, float]] = OrderedDict()
        self._q2: OrderedDict[str, dict[str, float]] = OrderedDict()

        # Thread safety for IBKR callbacks
        self._lock = threading.Lock()

        # Track which table to update next
        self._update_q1_next = True

        # Sync counter for target updates (if using soft updates)
        self._sync_counter = 0

    def _ensure_state(self, q_table: OrderedDict[str, dict[str, float]], state_key: str) -> None:
        """Ensure state exists in Q-table, with LRU eviction.

        Args:
            q_table: Q-table to update
            state_key: State hash key
        """
        if state_key not in q_table:
            # Evict oldest if at capacity
            if len(q_table) >= self.max_q_table_size:
                q_table.popitem(last=False)
            # Initialize Q-values to 0
            q_table[state_key] = dict.fromkeys(self.ACTIONS, 0.0)
        else:
            # Move to end (mark as recently used)
            q_table.move_to_end(state_key)

    def select_action(self, state: np.ndarray, training: bool = True) -> str:
        """Select action using epsilon-greedy over Q1 + Q2.

        Args:
            state: State feature vector
            training: Whether to use exploration

        Returns:
            Selected action name
        """
        state_key = _hash_state(state)

        with self._lock:
            self._ensure_state(self._q1, state_key)
            self._ensure_state(self._q2, state_key)

            # Epsilon-greedy exploration
            if training and random.random() < self.exploration_rate:
                return random.choice(self.ACTIONS)

            # Greedy action: use average of Q1 and Q2
            combined_q = {
                action: (self._q1[state_key][action] + self._q2[state_key][action]) / 2 for action in self.ACTIONS
            }
            return max(combined_q.items(), key=lambda x: x[1])[0]

    def update(self, transitions: list[TransitionType], weights: list[float]) -> dict[str, float]:
        """Update Q-tables from a batch of transitions.

        Args:
            transitions: Batch of (s, a, r, s', done) transitions
            weights: Importance sampling weights (for PER compatibility)

        Returns:
            Dictionary with training metrics
        """
        if not transitions:
            return {'loss': 0.0, 'td_error_mean': 0.0}

        total_loss = 0.0
        td_errors = []

        with self._lock:
            for transition, weight in zip(transitions, weights):
                state_key = _hash_state(transition.state)
                next_state_key = _hash_state(transition.next_state)
                action = transition.action

                # Ensure states exist in both tables
                self._ensure_state(self._q1, state_key)
                self._ensure_state(self._q2, state_key)
                self._ensure_state(self._q1, next_state_key)
                self._ensure_state(self._q2, next_state_key)

                # Double Q-Learning update
                if self._update_q1_next:
                    # Use Q1 to select action, Q2 to evaluate
                    if transition.done:
                        target = transition.reward
                    else:
                        best_action = max(self._q1[next_state_key].items(), key=lambda x: x[1])[0]
                        target = transition.reward + self.discount_factor * self._q2[next_state_key][best_action]

                    # TD error for Q1
                    current_q = self._q1[state_key][action]
                    td_error = target - current_q

                    # Update Q1
                    self._q1[state_key][action] += self.learning_rate * weight * td_error
                else:
                    # Use Q2 to select action, Q1 to evaluate
                    if transition.done:
                        target = transition.reward
                    else:
                        best_action = max(self._q2[next_state_key].items(), key=lambda x: x[1])[0]
                        target = transition.reward + self.discount_factor * self._q1[next_state_key][best_action]

                    # TD error for Q2
                    current_q = self._q2[state_key][action]
                    td_error = target - current_q

                    # Update Q2
                    self._q2[state_key][action] += self.learning_rate * weight * td_error

                # Alternate which table to update
                self._update_q1_next = not self._update_q1_next

                td_errors.append(abs(td_error))
                total_loss += td_error**2

                # Track updates
                self.total_updates += 1

        return {
            'loss': total_loss / len(transitions),
            'td_error_mean': float(np.mean(td_errors)),
            'td_error_max': float(np.max(td_errors)),
            'q1_size': len(self._q1),
            'q2_size': len(self._q2),
        }

    def get_td_errors(self, transitions: list[TransitionType]) -> list[float]:
        """Calculate TD errors for priority updates.

        Args:
            transitions: Batch of transitions

        Returns:
            List of absolute TD errors
        """
        td_errors = []

        with self._lock:
            for transition in transitions:
                state_key = _hash_state(transition.state)
                next_state_key = _hash_state(transition.next_state)

                self._ensure_state(self._q1, state_key)
                self._ensure_state(self._q2, state_key)
                self._ensure_state(self._q1, next_state_key)
                self._ensure_state(self._q2, next_state_key)

                # Use Q1+Q2 average for TD error calculation
                current_q = (self._q1[state_key][transition.action] + self._q2[state_key][transition.action]) / 2

                if transition.done:
                    target = transition.reward
                else:
                    # Use Q1 for action selection, Q2 for value (standard Double DQN)
                    best_action = max(self._q1[next_state_key].items(), key=lambda x: x[1])[0]
                    next_q = (self._q1[next_state_key][best_action] + self._q2[next_state_key][best_action]) / 2
                    target = transition.reward + self.discount_factor * next_q

                td_errors.append(abs(target - current_q))

        return td_errors

    def get_q_values(self, state: np.ndarray) -> dict[str, float]:
        """Get Q-values for a state (average of Q1 and Q2).

        Args:
            state: State feature vector

        Returns:
            Dictionary of action -> Q-value
        """
        state_key = _hash_state(state)

        with self._lock:
            self._ensure_state(self._q1, state_key)
            self._ensure_state(self._q2, state_key)

            return {action: (self._q1[state_key][action] + self._q2[state_key][action]) / 2 for action in self.ACTIONS}

    def save_state(self, path: str | Path) -> None:
        """Save agent state to file.

        Args:
            path: Path to save the state
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            state = {
                'version': '2.0',
                'algorithm': 'double_q_learning',
                'q1': dict(self._q1),
                'q2': dict(self._q2),
                'exploration_rate': self.exploration_rate,
                'total_updates': self.total_updates,
                'total_episodes': self.total_episodes,
                'update_q1_next': self._update_q1_next,
            }

        # Atomic write
        temp_path = path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(state, f)
        temp_path.replace(path)

        logger.info(f'Saved Double Q-Learning state to {path} (Q1: {len(self._q1)}, Q2: {len(self._q2)} states)')

    def load_state(self, path: str | Path) -> bool:
        """Load agent state from file.

        Args:
            path: Path to load the state from

        Returns:
            True if loaded successfully
        """
        path = Path(path)
        if not path.exists():
            logger.warning(f'State file not found: {path}')
            return False

        try:
            with open(path, encoding='utf-8') as f:
                state = json.load(f)

            with self._lock:
                # Handle version migration
                version = state.get('version', '1.0')

                if version == '1.0':
                    # Migrate from single Q-table format
                    q_values = state.get('q_values', {})
                    self._q1 = OrderedDict(q_values)
                    self._q2 = OrderedDict(q_values)  # Duplicate for Double Q
                    logger.info('Migrated from v1.0 single Q-table format')
                else:
                    self._q1 = OrderedDict(state.get('q1', {}))
                    self._q2 = OrderedDict(state.get('q2', {}))

                self.exploration_rate = state.get('exploration_rate', self.exploration_rate)
                self.total_updates = state.get('total_updates', 0)
                self.total_episodes = state.get('total_episodes', 0)
                self._update_q1_next = state.get('update_q1_next', True)

            logger.info(f'Loaded Double Q-Learning state from {path} (Q1: {len(self._q1)}, Q2: {len(self._q2)} states)')
            return True

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f'Failed to load state from {path}: {e}')
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get agent statistics.

        Returns:
            Dictionary with agent stats
        """
        stats = super().get_stats()
        stats.update(
            {
                'algorithm': 'double_q_learning',
                'q1_size': len(self._q1),
                'q2_size': len(self._q2),
                'max_q_table_size': self.max_q_table_size,
            }
        )
        return stats
