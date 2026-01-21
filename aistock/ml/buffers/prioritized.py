"""Prioritized Experience Replay (PER) buffer.

Implements prioritized sampling using a sum tree for O(log n) operations.

Reference: Schaul et al. (2015) "Prioritized Experience Replay"
"""

import numpy as np

from ..config import PERConfig, SequenceTransition, Transition
from .sum_tree import SumTree


TransitionType = Transition | SequenceTransition


class PrioritizedReplayBuffer:
    """Experience replay buffer with prioritized sampling.

    Transitions are sampled with probability proportional to their
    priority (typically |TD error| + epsilon), raised to power alpha.

    Importance sampling weights correct for the non-uniform sampling bias.
    """

    def __init__(self, config: PERConfig):
        """Initialize the buffer.

        Args:
            config: PER configuration with buffer_size, alpha, etc.
        """
        config.validate()
        self.config = config

        self._tree = SumTree(config.buffer_size)
        self._max_priority = 1.0  # Start with max priority for new transitions
        self._step = 0  # For beta annealing

    def __len__(self) -> int:
        """Return current number of transitions."""
        return len(self._tree)

    def add(self, transition: TransitionType) -> None:
        """Add a transition with max priority.

        New transitions get maximum priority to ensure they are
        sampled at least once.

        Args:
            transition: Experience transition (s, a, r, s', done)
        """
        # Use max priority for new transitions
        priority = self._max_priority**self.config.alpha
        self._tree.add(priority, transition)

    def sample(self, batch_size: int) -> tuple[list[TransitionType], list[float], list[int]]:
        """Sample a batch of transitions with prioritized sampling.

        Args:
            batch_size: Number of transitions to sample

        Returns:
            Tuple of (transitions, importance_weights, tree_indices)
        """
        if len(self._tree) < batch_size:
            raise ValueError(f'Not enough transitions: have {len(self._tree)}, need {batch_size}')

        transitions: list[TransitionType] = []
        tree_indices: list[int] = []
        priorities: list[float] = []

        # Divide priority range into segments for stratified sampling
        total_priority = self._tree.total
        segment_size = total_priority / batch_size

        for i in range(batch_size):
            # Sample uniformly within segment
            low = segment_size * i
            high = segment_size * (i + 1)
            cumsum = np.random.uniform(low, high)

            tree_idx, priority, data = self._tree.get(cumsum)

            transitions.append(data)  # type: ignore
            tree_indices.append(tree_idx)
            priorities.append(priority)

        # Calculate importance sampling weights
        beta = self.config.get_beta(self._step)
        self._step += 1

        # P(i) = p_i / sum(p_j)
        probabilities = np.array(priorities) / total_priority

        # w_i = (N * P(i))^(-beta) / max(w)
        n = len(self._tree)
        weights = (n * probabilities) ** (-beta)

        # Normalize by max weight for stability
        weights = weights / np.max(weights)

        return transitions, weights.tolist(), tree_indices

    def update_priorities(self, indices: list[int], td_errors: list[float]) -> None:
        """Update priorities based on TD errors.

        Args:
            indices: Tree indices from sampling
            td_errors: Absolute TD errors for each transition
        """
        for idx, td_error in zip(indices, td_errors):
            # Priority = |TD error| + epsilon, raised to alpha
            priority = (abs(td_error) + self.config.min_priority) ** self.config.alpha
            self._tree.update(idx, priority)

            # Track max priority for new transitions
            self._max_priority = max(self._max_priority, abs(td_error))

    def is_ready(self, min_size: int | None = None) -> bool:
        """Check if buffer has enough transitions for training.

        Args:
            min_size: Minimum required transitions (defaults to batch_size)

        Returns:
            True if len(buffer) >= min_size
        """
        threshold = min_size if min_size is not None else self.config.batch_size
        return len(self._tree) >= threshold

    def get_stats(self) -> dict[str, float]:
        """Get buffer statistics.

        Returns:
            Dictionary with buffer stats
        """
        return {
            'size': len(self._tree),
            'capacity': self.config.buffer_size,
            'total_priority': self._tree.total,
            'max_priority': self._max_priority,
            'min_priority': self._tree.min_priority,
            'beta': self.config.get_beta(self._step),
            'step': self._step,
        }
