"""Transformer network for sequential pattern recognition.

Uses multi-head self-attention to capture long-range dependencies
in sequences of market states.

Reference: Vaswani et al. (2017) "Attention Is All You Need"
"""

import math

import torch
import torch.nn as nn

from .base import BaseNetwork


class PositionalEncoding(nn.Module):
    """Sinusoidal positional encoding for transformers.

    Adds position information to the input embeddings since
    transformers have no inherent notion of sequence order.
    """

    def __init__(self, d_model: int, max_len: int = 500, dropout: float = 0.1):
        """Initialize positional encoding.

        Args:
            d_model: Model dimension (must match input dimension)
            max_len: Maximum sequence length
            dropout: Dropout probability
        """
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        # Create positional encoding matrix
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))

        pe[:, 0::2] = torch.sin(position * div_term)
        if d_model > 1:
            pe[:, 1::2] = torch.cos(position * div_term[: d_model // 2])

        pe = pe.unsqueeze(0)  # Add batch dimension
        self.register_buffer('pe', pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Add positional encoding to input.

        Args:
            x: Input tensor of shape (batch, seq_len, d_model)

        Returns:
            Tensor with positional encoding added
        """
        seq_len = x.size(1)
        x = x + self.pe[:, :seq_len, :]
        return self.dropout(x)


class TransformerNetwork(BaseNetwork):
    """Transformer-based network for sequential state processing.

    Architecture:
        Input -> Linear projection -> Positional Encoding
              -> Transformer Encoder -> Pooling -> FC -> Q-values

    The self-attention mechanism can capture complex temporal patterns
    and long-range dependencies in market data.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        num_heads: int = 4,
        dropout: float = 0.1,
        max_seq_len: int = 500,
    ):
        """Initialize the Transformer network.

        Args:
            state_dim: Dimension of each state in the sequence
            action_dim: Number of possible actions
            hidden_size: Transformer model dimension (d_model)
            num_layers: Number of transformer encoder layers
            num_heads: Number of attention heads
            dropout: Dropout probability
            max_seq_len: Maximum sequence length for positional encoding
        """
        super().__init__(state_dim, action_dim)

        # Validate dimensions
        if hidden_size % num_heads != 0:
            raise ValueError(f'hidden_size ({hidden_size}) must be divisible by num_heads ({num_heads})')

        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.num_heads = num_heads
        self.dropout = dropout

        # Input projection
        self.input_projection = nn.Linear(state_dim, hidden_size)

        # Positional encoding
        self.pos_encoding = PositionalEncoding(hidden_size, max_seq_len, dropout)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_size,
            nhead=num_heads,
            dim_feedforward=hidden_size * 4,
            dropout=dropout,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

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
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Forward pass through the network.

        Args:
            state: State sequence tensor of shape (batch, seq_len, state_dim)
                   or (batch, state_dim) for single state

        Returns:
            Q-values tensor of shape (batch, action_dim)
        """
        # Handle single state input
        if state.dim() == 2:
            state = state.unsqueeze(1)  # Add sequence dimension

        # Project to model dimension
        x = self.input_projection(state)  # (batch, seq_len, hidden_size)

        # Add positional encoding
        x = self.pos_encoding(x)

        # Transformer encoder
        x = self.transformer(x)  # (batch, seq_len, hidden_size)

        # Global average pooling over sequence dimension
        x = x.mean(dim=1)  # (batch, hidden_size)

        # Output head
        q_values = self.fc(x)

        return q_values

    def forward_with_attention(self, state: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass returning Q-values and attention weights.

        Useful for interpretability and debugging.

        Args:
            state: State tensor

        Returns:
            Tuple of (Q-values, attention_weights)
            Note: Attention weights require custom extraction from the transformer
        """
        # Standard forward pass
        q_values = self.forward(state)

        # For attention weights, we'd need to modify the transformer
        # to return them. This is a placeholder for future implementation.
        # Return dummy attention weights for now
        batch_size = state.size(0) if state.dim() == 3 else 1
        seq_len = state.size(1) if state.dim() == 3 else 1
        attention_weights = torch.zeros(
            batch_size,
            self.num_heads,
            seq_len,
            seq_len,
            device=state.device,
            dtype=state.dtype,
        )

        return q_values, attention_weights

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
                'num_heads': self.num_heads,
                'dropout': self.dropout,
            }
        )
        return config
