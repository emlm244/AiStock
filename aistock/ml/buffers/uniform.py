"""Uniform experience replay buffer (baseline implementation)."""

import random
from collections import deque

from ..config import Transition


class UniformReplayBuffer:
    """Simple replay buffer with uniform random sampling.

    This is the baseline implementation without prioritization.
    All transitions have equal probability of being sampled.
    """

    def __init__(self, capacity: int):
        """Initialize the buffer.

        Args:
            capacity: Maximum number of transitions to store
        """
        if capacity <= 0:
            raise ValueError(f'capacity must be positive, got {capacity}')

        self.capacity = capacity
        self._buffer: deque[Transition] = deque(maxlen=capacity)

    def __len__(self) -> int:
        """Return current number of transitions."""
        return len(self._buffer)

    def add(self, transition: Transition) -> None:
        """Add a transition to the buffer.

        Args:
            transition: Experience transition (s, a, r, s', done)
        """
        self._buffer.append(transition)

    def sample(self, batch_size: int) -> tuple[list[Transition], list[float], list[int]]:
        """Sample a batch of transitions uniformly.

        Args:
            batch_size: Number of transitions to sample

        Returns:
            Tuple of (transitions, weights, indices)
            - transitions: List of sampled transitions
            - weights: All 1.0 (no importance sampling needed)
            - indices: Buffer indices (for API compatibility)
        """
        if len(self._buffer) < batch_size:
            raise ValueError(f'Not enough transitions: have {len(self._buffer)}, need {batch_size}')

        indices = random.sample(range(len(self._buffer)), batch_size)
        transitions = [self._buffer[i] for i in indices]
        weights = [1.0] * batch_size  # Uniform weights

        return transitions, weights, indices

    def update_priorities(self, _indices: list[int], _priorities: list[float]) -> None:
        """No-op for uniform buffer (API compatibility).

        Args:
            _indices: Ignored
            _priorities: Ignored
        """
        pass  # Uniform sampling ignores priorities

    def is_ready(self, min_size: int) -> bool:
        """Check if buffer has enough transitions.

        Args:
            min_size: Minimum required transitions

        Returns:
            True if len(buffer) >= min_size
        """
        return len(self._buffer) >= min_size
