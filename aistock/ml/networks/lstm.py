"""LSTM network for sequential pattern recognition.

Uses Long Short-Term Memory to capture temporal dependencies
in sequences of market states.

Reference: Hochreiter & Schmidhuber (1997) "Long Short-Term Memory"
"""

import torch
import torch.nn as nn

from .base import BaseNetwork


class LSTMNetwork(BaseNetwork):
    """LSTM-based network for sequential state processing.

    Architecture:
        Input (batch, seq_len, state_dim) -> LSTM -> FC -> Q-values

    The LSTM maintains hidden state across the sequence, capturing
    temporal patterns in price movements, volume, and indicators.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.1,
    ):
        """Initialize the LSTM network.

        Args:
            state_dim: Dimension of each state in the sequence
            action_dim: Number of possible actions
            hidden_size: LSTM hidden state dimension
            num_layers: Number of stacked LSTM layers
            dropout: Dropout probability between LSTM layers
        """
        super().__init__(state_dim, action_dim)

        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout

        # LSTM layer
        self.lstm = nn.LSTM(
            input_size=state_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        # Output head
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, action_dim),
        )

        # Initialize weights
        self._init_weights()

    def _init_weights(self) -> None:
        """Initialize network weights."""
        # LSTM weights
        for name, param in self.lstm.named_parameters():
            if 'weight_ih' in name:
                nn.init.xavier_uniform_(param)
            elif 'weight_hh' in name:
                nn.init.orthogonal_(param)
            elif 'bias' in name:
                nn.init.zeros_(param)

        # FC weights
        for module in self.fc.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(
        self,
        state: torch.Tensor,
        hidden: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> torch.Tensor:
        """Forward pass through the network.

        Args:
            state: State sequence tensor of shape (batch, seq_len, state_dim)
                   or (batch, state_dim) for single state
            hidden: Optional initial hidden state (h_0, c_0)

        Returns:
            Q-values tensor of shape (batch, action_dim)
        """
        # Handle single state input
        if state.dim() == 2:
            state = state.unsqueeze(1)  # Add sequence dimension

        # LSTM forward
        # _output: (batch, seq_len, hidden_size) - not used, we only need final state
        # h_n: (num_layers, batch, hidden_size)
        _output, (h_n, _c_n) = self.lstm(state, hidden)

        # Use final hidden state for action prediction
        # h_n[-1] is the last layer's hidden state
        final_hidden = h_n[-1]  # (batch, hidden_size)

        # Output head
        q_values = self.fc(final_hidden)

        return q_values

    def forward_with_hidden(
        self,
        state: torch.Tensor,
        hidden: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        """Forward pass returning both Q-values and hidden state.

        Useful for maintaining state across calls during evaluation.

        Args:
            state: State tensor
            hidden: Optional initial hidden state

        Returns:
            Tuple of (Q-values, (h_n, c_n))
        """
        if state.dim() == 2:
            state = state.unsqueeze(1)

        _output, (h_n, c_n) = self.lstm(state, hidden)
        q_values = self.fc(h_n[-1])

        return q_values, (h_n, c_n)

    def init_hidden(self, batch_size: int, device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
        """Initialize hidden state for a new sequence.

        Args:
            batch_size: Batch size
            device: Device for tensors

        Returns:
            Initial (h_0, c_0) tuple
        """
        h_0 = torch.zeros(self.num_layers, batch_size, self.hidden_size, device=device)
        c_0 = torch.zeros(self.num_layers, batch_size, self.hidden_size, device=device)
        return h_0, c_0

    def get_config(self) -> dict[str, object]:
        """Get network configuration.

        Returns:
            Dictionary with network configuration
        """
        config = super().get_config()
        config.update(
            {
                'hidden_size': self.hidden_size,
                'num_layers': self.num_layers,
                'dropout': self.dropout,
            }
        )
        return config
