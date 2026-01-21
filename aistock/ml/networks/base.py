"""Base class for neural network architectures."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn


class BaseNetwork(nn.Module, ABC):
    """Abstract base class for all neural network architectures.

    All network implementations must inherit from this class and
    implement the required abstract methods.
    """

    def __init__(self, state_dim: int, action_dim: int):
        """Initialize the network.

        Args:
            state_dim: Dimension of state/observation vector
            action_dim: Number of possible actions (output dimension)
        """
        super().__init__()
        self.state_dim = state_dim
        self.action_dim = action_dim

    @abstractmethod
    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Forward pass through the network.

        Args:
            state: State tensor of shape (batch, state_dim) or (batch, seq, state_dim)

        Returns:
            Q-values tensor of shape (batch, action_dim)
        """
        ...

    def get_action(self, state: torch.Tensor) -> int:
        """Get the greedy action for a single state.

        Args:
            state: State tensor of shape (state_dim,) or (1, state_dim)

        Returns:
            Index of the action with highest Q-value
        """
        with torch.no_grad():
            if state.dim() == 1:
                state = state.unsqueeze(0)
            q_values = self.forward(state)
            return int(q_values.argmax(dim=1).item())

    def get_q_values(self, state: torch.Tensor) -> dict[str, float]:
        """Get Q-values for all actions for a single state.

        Args:
            state: State tensor

        Returns:
            Dictionary mapping action index to Q-value
        """
        with torch.no_grad():
            if state.dim() == 1:
                state = state.unsqueeze(0)
            q_values = self.forward(state).squeeze(0)
            return {str(i): float(q) for i, q in enumerate(q_values.tolist())}

    def save(self, path: Path | str) -> None:
        """Save network weights and metadata.

        Args:
            path: Path to save the model
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        checkpoint = {
            'state_dict': self.state_dict(),
            'state_dim': self.state_dim,
            'action_dim': self.action_dim,
            'class_name': self.__class__.__name__,
        }
        torch.save(checkpoint, path)

    def load(self, path: Path | str, strict: bool = True) -> None:
        """Load network weights from a checkpoint.

        Args:
            path: Path to the saved model
            strict: Whether to require exact parameter match
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f'Checkpoint not found: {path}')

        checkpoint = torch.load(path, weights_only=False)

        # Validate dimensions
        if checkpoint.get('state_dim') != self.state_dim:
            raise ValueError(
                f'State dim mismatch: checkpoint has {checkpoint.get("state_dim")}, model expects {self.state_dim}'
            )
        if checkpoint.get('action_dim') != self.action_dim:
            raise ValueError(
                f'Action dim mismatch: checkpoint has {checkpoint.get("action_dim")}, model expects {self.action_dim}'
            )

        self.load_state_dict(checkpoint['state_dict'], strict=strict)

    def count_parameters(self) -> int:
        """Count total trainable parameters.

        Returns:
            Number of trainable parameters
        """
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def get_config(self) -> dict[str, Any]:
        """Get network configuration.

        Returns:
            Dictionary with network configuration
        """
        return {
            'class_name': self.__class__.__name__,
            'state_dim': self.state_dim,
            'action_dim': self.action_dim,
            'trainable_parameters': self.count_parameters(),
        }
