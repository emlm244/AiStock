"""Base protocol for experience replay buffers."""

from typing import Protocol

from ..config import SequenceTransition, Transition

TransitionType = Transition | SequenceTransition


class ReplayBufferProtocol(Protocol):
    """Protocol defining the replay buffer interface.

    All replay buffer implementations must conform to this interface
    to ensure interchangeability.
    """

    def add(self, transition: TransitionType) -> None:
        """Add a transition to the buffer.

        Args:
            transition: Experience transition (s, a, r, s', done)
        """
        ...

    def sample(self, batch_size: int) -> tuple[list[TransitionType], list[float], list[int]]:
        """Sample a batch of transitions.

        Args:
            batch_size: Number of transitions to sample

        Returns:
            Tuple of (transitions, importance_weights, indices)
            - transitions: List of sampled transitions
            - importance_weights: Weights for importance sampling correction
            - indices: Buffer indices for priority updates
        """
        ...

    def update_priorities(self, indices: list[int], priorities: list[float]) -> None:
        """Update priorities for sampled transitions.

        Args:
            indices: Buffer indices to update
            priorities: New priority values (typically |TD error| + epsilon)
        """
        ...

    def __len__(self) -> int:
        """Return the current number of transitions in the buffer."""
        ...

    def is_ready(self, min_size: int | None = None) -> bool:
        """Check if buffer has enough transitions for training.

        Args:
            min_size: Minimum required transitions (defaults to implementation-defined minimum when None)

        Returns:
            True if len(buffer) >= min_size
        """
        ...
