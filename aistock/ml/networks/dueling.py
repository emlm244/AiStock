"""Dueling DQN network architecture.

Separates the Q-function into value and advantage streams:
Q(s,a) = V(s) + (A(s,a) - mean(A(s,:)))

Reference: Wang et al. (2016) "Dueling Network Architectures for Deep RL"
"""

import torch
import torch.nn as nn

from .base import BaseNetwork


class DuelingNetwork(BaseNetwork):
    """Dueling DQN architecture with separate value and advantage streams.

    Architecture:
        Input -> Shared Encoder -> [Value Stream]     -> V(s)
                                -> [Advantage Stream] -> A(s,a)

        Q(s,a) = V(s) + (A(s,a) - mean(A(s,:)))

    The value stream estimates the expected return from state s.
    The advantage stream estimates the relative benefit of each action.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_sizes: tuple[int, ...] = (256, 128),
        value_hidden: int = 64,
        advantage_hidden: int = 64,
    ):
        """Initialize the Dueling network.

        Args:
            state_dim: Dimension of state vector
            action_dim: Number of possible actions
            hidden_sizes: Sizes of shared encoder layers
            value_hidden: Size of value stream hidden layer
            advantage_hidden: Size of advantage stream hidden layer
        """
        super().__init__(state_dim, action_dim)

        self.hidden_sizes = hidden_sizes
        self.value_hidden = value_hidden
        self.advantage_hidden = advantage_hidden

        # Build shared encoder
        encoder_layers: list[nn.Module] = []
        prev_size = state_dim

        for hidden_size in hidden_sizes:
            encoder_layers.extend(
                [
                    nn.Linear(prev_size, hidden_size),
                    nn.ReLU(),
                ]
            )
            prev_size = hidden_size

        self.encoder = nn.Sequential(*encoder_layers)
        encoder_output_size = hidden_sizes[-1] if hidden_sizes else state_dim

        # Value stream: V(s) -> scalar
        self.value_stream = nn.Sequential(
            nn.Linear(encoder_output_size, value_hidden),
            nn.ReLU(),
            nn.Linear(value_hidden, 1),
        )

        # Advantage stream: A(s,a) -> action_dim
        self.advantage_stream = nn.Sequential(
            nn.Linear(encoder_output_size, advantage_hidden),
            nn.ReLU(),
            nn.Linear(advantage_hidden, action_dim),
        )

        # Initialize weights
        self._init_weights()

    def _init_weights(self) -> None:
        """Initialize network weights using Xavier initialization."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Forward pass computing Q-values.

        Args:
            state: State tensor of shape (batch, state_dim)

        Returns:
            Q-values tensor of shape (batch, action_dim)
        """
        # Shared encoder
        features = self.encoder(state)

        # Value and advantage streams
        value = self.value_stream(features)  # (batch, 1)
        advantage = self.advantage_stream(features)  # (batch, action_dim)

        # Combine: Q = V + (A - mean(A))
        # Subtracting mean makes the advantage identifiable
        q_values = value + (advantage - advantage.mean(dim=1, keepdim=True))

        return q_values

    def get_value(self, state: torch.Tensor) -> torch.Tensor:
        """Get state value V(s) only.

        Args:
            state: State tensor

        Returns:
            Value tensor of shape (batch, 1)
        """
        with torch.no_grad():
            if state.dim() == 1:
                state = state.unsqueeze(0)
            features = self.encoder(state)
            return self.value_stream(features)

    def get_advantage(self, state: torch.Tensor) -> torch.Tensor:
        """Get action advantages A(s,a) only.

        Args:
            state: State tensor

        Returns:
            Advantage tensor of shape (batch, action_dim)
        """
        with torch.no_grad():
            if state.dim() == 1:
                state = state.unsqueeze(0)
            features = self.encoder(state)
            advantage = self.advantage_stream(features)
            return advantage - advantage.mean(dim=1, keepdim=True)

    def get_config(self) -> dict[str, object]:
        """Get network configuration.

        Returns:
            Dictionary with network configuration
        """
        config = super().get_config()
        config.update(
            {
                'hidden_sizes': self.hidden_sizes,
                'value_hidden': self.value_hidden,
                'advantage_hidden': self.advantage_hidden,
            }
        )
        return config
