"""Base protocol and class for RL agents."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..config import Transition


class AgentProtocol(Protocol):
    """Protocol defining the RL agent interface.

    All agent implementations must conform to this interface
    for interchangeability with the decision engine.
    """

    def select_action(self, state: np.ndarray, training: bool = True) -> str:
        """Select an action for the given state.

        Args:
            state: Current state feature vector
            training: Whether to use exploration (True) or pure exploitation

        Returns:
            Action name (e.g., 'BUY', 'SELL', 'HOLD')
        """
        ...

    def update(self, transitions: list[Transition], weights: list[float]) -> dict[str, float]:
        """Update the agent from a batch of transitions.

        Args:
            transitions: Batch of (s, a, r, s', done) transitions
            weights: Importance sampling weights for each transition

        Returns:
            Dictionary with training metrics (e.g., loss, td_error)
        """
        ...

    def get_td_errors(self, transitions: list[Transition]) -> list[float]:
        """Calculate TD errors for transitions (for PER priority updates).

        Args:
            transitions: Batch of transitions

        Returns:
            List of absolute TD errors
        """
        ...

    def save_state(self, path: str | Path) -> None:
        """Save agent state to file.

        Args:
            path: Path to save the state
        """
        ...

    def load_state(self, path: str | Path) -> bool:
        """Load agent state from file.

        Args:
            path: Path to load the state from

        Returns:
            True if loaded successfully, False otherwise
        """
        ...


class BaseAgent(ABC):
    """Abstract base class for RL agents.

    Provides common functionality and default implementations
    for the agent interface.
    """

    # Mapping from action indices to action names
    ACTIONS: list[str] = ['BUY', 'SELL', 'HOLD', 'INCREASE_SIZE', 'DECREASE_SIZE']

    def __init__(
        self,
        state_dim: int,
        learning_rate: float = 0.001,
        discount_factor: float = 0.95,
        exploration_rate: float = 0.1,
        exploration_decay: float = 0.995,
        min_exploration_rate: float = 0.05,
    ):
        """Initialize the agent.

        Args:
            state_dim: Dimension of state feature vector
            learning_rate: Learning rate (alpha)
            discount_factor: Discount factor (gamma)
            exploration_rate: Initial exploration rate (epsilon)
            exploration_decay: Exploration decay rate per episode
            min_exploration_rate: Minimum exploration rate
        """
        self.state_dim = state_dim
        self.action_dim = len(self.ACTIONS)
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.exploration_rate = exploration_rate
        self.exploration_decay = exploration_decay
        self.min_exploration_rate = min_exploration_rate

        # Statistics
        self.total_updates = 0
        self.total_episodes = 0

    @abstractmethod
    def select_action(self, state: np.ndarray, training: bool = True) -> str:
        """Select an action for the given state."""
        ...

    @abstractmethod
    def update(self, transitions: list[Transition], weights: list[float]) -> dict[str, float]:
        """Update the agent from a batch of transitions."""
        ...

    @abstractmethod
    def get_td_errors(self, transitions: list[Transition]) -> list[float]:
        """Calculate TD errors for transitions."""
        ...

    @abstractmethod
    def save_state(self, path: str | Path) -> None:
        """Save agent state to file."""
        ...

    @abstractmethod
    def load_state(self, path: str | Path) -> bool:
        """Load agent state from file."""
        ...

    def action_to_index(self, action: str) -> int:
        """Convert action name to index.

        Args:
            action: Action name

        Returns:
            Action index
        """
        return self.ACTIONS.index(action)

    def index_to_action(self, index: int) -> str:
        """Convert action index to name.

        Args:
            index: Action index

        Returns:
            Action name
        """
        return self.ACTIONS[index]

    def decay_exploration(self) -> None:
        """Decay exploration rate after an episode."""
        self.exploration_rate = max(
            self.min_exploration_rate,
            self.exploration_rate * self.exploration_decay,
        )
        self.total_episodes += 1

    def get_stats(self) -> dict[str, Any]:
        """Get agent statistics.

        Returns:
            Dictionary with agent stats
        """
        return {
            'state_dim': self.state_dim,
            'action_dim': self.action_dim,
            'learning_rate': self.learning_rate,
            'discount_factor': self.discount_factor,
            'exploration_rate': self.exploration_rate,
            'total_updates': self.total_updates,
            'total_episodes': self.total_episodes,
        }
