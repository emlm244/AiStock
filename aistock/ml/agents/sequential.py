"""Sequential agent using LSTM or Transformer for temporal patterns.

Processes sequences of states to capture temporal dependencies
in market data for improved decision making.

References:
- Hochreiter & Schmidhuber (1997) "Long Short-Term Memory"
- Vaswani et al. (2017) "Attention Is All You Need"
"""

import logging
import random
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from ..config import SequentialConfig, Transition
from ..device import get_device
from ..networks import LSTMNetwork, TransformerNetwork
from .base import BaseAgent

logger = logging.getLogger(__name__)


class SequenceBuffer:
    """Rolling window buffer for state sequences.

    Maintains a fixed-length history of states for sequential models.
    """

    def __init__(self, sequence_length: int, state_dim: int):
        """Initialize the sequence buffer.

        Args:
            sequence_length: Number of historical states to maintain
            state_dim: Dimension of each state vector
        """
        self.sequence_length = sequence_length
        self.state_dim = state_dim
        self._buffer: deque[np.ndarray] = deque(maxlen=sequence_length)

    def add(self, state: np.ndarray) -> None:
        """Add a state to the buffer.

        Args:
            state: State feature vector
        """
        self._buffer.append(state.copy())

    def get_sequence(self) -> np.ndarray:
        """Get the current sequence of states.

        Returns:
            Array of shape (seq_len, state_dim), zero-padded if needed
        """
        if len(self._buffer) == 0:
            return np.zeros((self.sequence_length, self.state_dim), dtype=np.float32)

        # Pad with zeros if not enough history
        sequence = list(self._buffer)
        while len(sequence) < self.sequence_length:
            sequence.insert(0, np.zeros(self.state_dim, dtype=np.float32))

        return np.array(sequence, dtype=np.float32)

    def clear(self) -> None:
        """Clear the buffer."""
        self._buffer.clear()

    def __len__(self) -> int:
        """Return current buffer size."""
        return len(self._buffer)


class SequentialAgent(BaseAgent):
    """Sequential RL agent using LSTM or Transformer.

    Maintains a rolling window of states and uses recurrent/attention
    architectures to capture temporal patterns.
    """

    def __init__(
        self,
        state_dim: int,
        config: SequentialConfig | None = None,
        learning_rate: float = 1e-4,
        discount_factor: float = 0.95,
        exploration_rate: float = 0.1,
        exploration_decay: float = 0.995,
        min_exploration_rate: float = 0.05,
        device: str = 'auto',
    ):
        """Initialize the sequential agent.

        Args:
            state_dim: Dimension of state feature vector
            config: Optional SequentialConfig
            learning_rate: Learning rate for optimizer
            discount_factor: Discount factor (gamma)
            exploration_rate: Initial exploration rate (epsilon)
            exploration_decay: Exploration decay per episode
            min_exploration_rate: Minimum exploration rate
            device: Device preference ('auto', 'cpu', 'cuda', 'mps')
        """
        super().__init__(
            state_dim=state_dim,
            learning_rate=learning_rate,
            discount_factor=discount_factor,
            exploration_rate=exploration_rate,
            exploration_decay=exploration_decay,
            min_exploration_rate=min_exploration_rate,
        )

        self.config = config or SequentialConfig()
        self.device = get_device(device)  # type: ignore

        # Sequence buffer for maintaining state history
        self.sequence_buffer = SequenceBuffer(
            self.config.sequence_length,
            state_dim,
        )

        # Build networks
        self._build_networks()

        # Optimizer
        self.optimizer = optim.Adam(
            self.policy_net.parameters(),
            lr=self.config.learning_rate if config else learning_rate,
        )

        # Loss function
        self.loss_fn = nn.SmoothL1Loss(reduction='none')

        # Target network sync counter
        self._sync_counter = 0
        self._target_update_freq = 1000

    def _build_networks(self) -> None:
        """Build policy and target networks based on model type."""
        if self.config.model_type == 'lstm':
            network_class = LSTMNetwork
            network_kwargs = {
                'hidden_size': self.config.hidden_size,
                'num_layers': self.config.num_layers,
                'dropout': self.config.dropout,
            }
        else:  # transformer
            network_class = TransformerNetwork
            network_kwargs = {
                'hidden_size': self.config.hidden_size,
                'num_layers': self.config.num_layers,
                'num_heads': self.config.num_heads,
                'dropout': self.config.dropout,
            }

        # Policy network
        self.policy_net = network_class(
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            **network_kwargs,
        ).to(self.device)

        # Target network
        self.target_net = network_class(
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            **network_kwargs,
        ).to(self.device)

        # Initialize target with policy weights
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

    def select_action(self, state: np.ndarray, training: bool = True) -> str:
        """Select action using epsilon-greedy policy with sequence context.

        Args:
            state: Current state feature vector
            training: Whether to use exploration

        Returns:
            Selected action name
        """
        # Add state to sequence buffer
        self.sequence_buffer.add(state)

        # Epsilon-greedy exploration
        if training and random.random() < self.exploration_rate:
            return random.choice(self.ACTIONS)

        # Get sequence and predict
        with torch.no_grad():
            sequence = self.sequence_buffer.get_sequence()
            seq_tensor = torch.FloatTensor(sequence).unsqueeze(0).to(self.device)
            q_values = self.policy_net(seq_tensor)
            action_idx = q_values.argmax(dim=1).item()
            return self.index_to_action(int(action_idx))

    def update(self, transitions: list[Transition], weights: list[float]) -> dict[str, float]:
        """Update networks from a batch of transitions.

        Note: For sequential models, each transition should contain
        the full sequence of states leading to the current state.

        Args:
            transitions: Batch of (s, a, r, s', done) transitions
            weights: Importance sampling weights

        Returns:
            Dictionary with training metrics
        """
        if not transitions:
            return {'loss': 0.0, 'td_error_mean': 0.0}

        # For sequential models, we need sequences not single states
        # This simplified version treats each state as a single-step sequence
        # A full implementation would maintain sequence history in transitions

        states = (
            torch.FloatTensor(np.array([t.state for t in transitions])).unsqueeze(1).to(self.device)
        )  # Add sequence dim

        actions = torch.LongTensor([self.action_to_index(t.action) for t in transitions]).to(self.device)

        rewards = torch.FloatTensor([t.reward for t in transitions]).to(self.device)

        next_states = torch.FloatTensor(np.array([t.next_state for t in transitions])).unsqueeze(1).to(self.device)

        dones = torch.FloatTensor([float(t.done) for t in transitions]).to(self.device)

        weights_tensor = torch.FloatTensor(weights).to(self.device)

        # Current Q-values
        current_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target Q-values (Double DQN style)
        with torch.no_grad():
            next_actions = self.policy_net(next_states).argmax(dim=1)
            next_q = self.target_net(next_states).gather(1, next_actions.unsqueeze(1)).squeeze(1)
            target_q = rewards + self.discount_factor * next_q * (1 - dones)

        # TD errors
        td_errors = (target_q - current_q).abs().detach().cpu().numpy()

        # Weighted loss
        losses = self.loss_fn(current_q, target_q)
        loss = (losses * weights_tensor).mean()

        # Optimize
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), 1.0)
        self.optimizer.step()

        # Sync target network
        self._sync_counter += 1
        if self._sync_counter >= self._target_update_freq:
            self._sync_target_network()
            self._sync_counter = 0

        self.total_updates += 1

        return {
            'loss': float(loss.item()),
            'td_error_mean': float(np.mean(td_errors)),
            'td_error_max': float(np.max(td_errors)),
            'q_mean': float(current_q.mean().item()),
        }

    def _sync_target_network(self) -> None:
        """Sync target network with policy network."""
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def get_td_errors(self, transitions: list[Transition]) -> list[float]:
        """Calculate TD errors for priority updates.

        Args:
            transitions: Batch of transitions

        Returns:
            List of absolute TD errors
        """
        with torch.no_grad():
            states = torch.FloatTensor(np.array([t.state for t in transitions])).unsqueeze(1).to(self.device)

            actions = torch.LongTensor([self.action_to_index(t.action) for t in transitions]).to(self.device)

            rewards = torch.FloatTensor([t.reward for t in transitions]).to(self.device)

            next_states = torch.FloatTensor(np.array([t.next_state for t in transitions])).unsqueeze(1).to(self.device)

            dones = torch.FloatTensor([float(t.done) for t in transitions]).to(self.device)

            current_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

            next_actions = self.policy_net(next_states).argmax(dim=1)
            next_q = self.target_net(next_states).gather(1, next_actions.unsqueeze(1)).squeeze(1)
            target_q = rewards + self.discount_factor * next_q * (1 - dones)

            td_errors = (target_q - current_q).abs().cpu().numpy()

        return td_errors.tolist()

    def get_q_values(self, state: np.ndarray) -> dict[str, float]:
        """Get Q-values for a state using current sequence context.

        Args:
            state: Current state feature vector

        Returns:
            Dictionary of action -> Q-value
        """
        # Use existing sequence buffer
        with torch.no_grad():
            sequence = self.sequence_buffer.get_sequence()
            # Replace last state with provided state
            sequence[-1] = state
            seq_tensor = torch.FloatTensor(sequence).unsqueeze(0).to(self.device)
            q_values = self.policy_net(seq_tensor).squeeze(0).cpu().numpy()

        return {action: float(q_values[i]) for i, action in enumerate(self.ACTIONS)}

    def reset_sequence(self) -> None:
        """Reset the sequence buffer (e.g., at episode start)."""
        self.sequence_buffer.clear()

    def save_state(self, path: str | Path) -> None:
        """Save agent state to file.

        Args:
            path: Path to save the state
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        state = {
            'version': '4.0',
            'algorithm': f'sequential_{self.config.model_type}',
            'policy_net': self.policy_net.state_dict(),
            'target_net': self.target_net.state_dict(),
            'optimizer': self.optimizer.state_dict(),
            'exploration_rate': self.exploration_rate,
            'total_updates': self.total_updates,
            'total_episodes': self.total_episodes,
            'sync_counter': self._sync_counter,
            'config': {
                'model_type': self.config.model_type,
                'sequence_length': self.config.sequence_length,
                'hidden_size': self.config.hidden_size,
                'num_layers': self.config.num_layers,
                'num_heads': self.config.num_heads,
                'dropout': self.config.dropout,
            },
        }

        torch.save(state, path)
        logger.info(
            f'Saved {self.config.model_type.upper()} state to {path} ({self.policy_net.count_parameters()} parameters)'
        )

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
            state = torch.load(path, map_location=self.device, weights_only=False)

            self.policy_net.load_state_dict(state['policy_net'])
            self.target_net.load_state_dict(state['target_net'])
            self.optimizer.load_state_dict(state['optimizer'])
            self.exploration_rate = state.get('exploration_rate', self.exploration_rate)
            self.total_updates = state.get('total_updates', 0)
            self.total_episodes = state.get('total_episodes', 0)
            self._sync_counter = state.get('sync_counter', 0)

            logger.info(
                f'Loaded {self.config.model_type.upper()} state from {path} '
                f'({self.policy_net.count_parameters()} parameters)'
            )
            return True

        except Exception as e:
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
                'algorithm': f'sequential_{self.config.model_type}',
                'model_type': self.config.model_type,
                'sequence_length': self.config.sequence_length,
                'device': str(self.device),
                'parameters': self.policy_net.count_parameters(),
                'sequence_buffer_len': len(self.sequence_buffer),
            }
        )
        return stats
