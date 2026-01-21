"""ML configuration dataclasses for algorithm upgrades."""

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import numpy as np
import torch


@dataclass
class Transition:
    """Single experience transition for replay buffer.

    Stores a (s, a, r, s', done) tuple with optional metadata.
    """

    state: np.ndarray
    action: str
    reward: float
    next_state: np.ndarray
    done: bool
    td_error: float = 0.0
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        """Ensure arrays are numpy arrays."""
        if not isinstance(self.state, np.ndarray):
            self.state = np.array(self.state, dtype=np.float32)
        if not isinstance(self.next_state, np.ndarray):
            self.next_state = np.array(self.next_state, dtype=np.float32)


@dataclass
class SequenceTransition:
    """Experience transition containing full state sequences."""

    state_sequence: np.ndarray
    action: str
    reward: float
    next_state_sequence: np.ndarray
    done: bool
    td_error: float = 0.0
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        """Ensure arrays are numpy arrays."""
        if not isinstance(self.state_sequence, np.ndarray):
            self.state_sequence = np.array(self.state_sequence, dtype=np.float32)
        if not isinstance(self.next_state_sequence, np.ndarray):
            self.next_state_sequence = np.array(self.next_state_sequence, dtype=np.float32)


@dataclass
class DoubleQLearningConfig:
    """Configuration for Double Q-Learning algorithm.

    Double Q-Learning uses two Q-tables to reduce overestimation bias:
    - Q1 selects the best action (argmax)
    - Q2 evaluates that action's value

    Reference: van Hasselt et al. (2010) "Double Q-learning"
    """

    enable: bool = False
    target_update_freq: int = 100  # Steps between target Q-table sync

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.target_update_freq <= 0:
            raise ValueError(f'target_update_freq must be positive, got {self.target_update_freq}')


@dataclass
class PERConfig:
    """Configuration for Prioritized Experience Replay.

    PER samples transitions with probability proportional to TD error,
    allowing the agent to learn more from surprising transitions.

    Reference: Schaul et al. (2015) "Prioritized Experience Replay"
    """

    enable: bool = False
    buffer_size: int = 100_000
    alpha: float = 0.6  # Priority exponent (0 = uniform, 1 = full prioritization)
    beta_start: float = 0.4  # Initial importance sampling correction
    beta_end: float = 1.0  # Final importance sampling correction
    beta_annealing_steps: int = 100_000  # Steps to anneal beta
    min_priority: float = 1e-6  # Minimum priority to avoid zero probability
    batch_size: int = 32
    train_frequency: int = 4  # Train every N fills

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.buffer_size <= 0:
            raise ValueError(f'buffer_size must be positive, got {self.buffer_size}')
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError(f'alpha must be in [0, 1], got {self.alpha}')
        if not 0.0 <= self.beta_start <= 1.0:
            raise ValueError(f'beta_start must be in [0, 1], got {self.beta_start}')
        if not 0.0 <= self.beta_end <= 1.0:
            raise ValueError(f'beta_end must be in [0, 1], got {self.beta_end}')
        if self.beta_start > self.beta_end:
            raise ValueError(f'beta_start ({self.beta_start}) must be <= beta_end ({self.beta_end})')
        if self.min_priority <= 0:
            raise ValueError(f'min_priority must be positive, got {self.min_priority}')
        if self.batch_size <= 0:
            raise ValueError(f'batch_size must be positive, got {self.batch_size}')
        if self.train_frequency <= 0:
            raise ValueError(f'train_frequency must be positive, got {self.train_frequency}')

    def get_beta(self, step: int) -> float:
        """Calculate current beta value based on annealing schedule.

        Args:
            step: Current training step

        Returns:
            Current beta value for importance sampling correction
        """
        fraction = min(1.0, step / max(1, self.beta_annealing_steps))
        return self.beta_start + fraction * (self.beta_end - self.beta_start)


@dataclass
class DuelingDQNConfig:
    """Configuration for Dueling DQN architecture.

    Dueling DQN separates the Q-function into:
    - Value stream V(s): Expected value of being in state s
    - Advantage stream A(s,a): Advantage of each action over the mean

    Q(s,a) = V(s) + (A(s,a) - mean(A(s,:)))

    Reference: Wang et al. (2016) "Dueling Network Architectures"
    """

    enable: bool = False
    hidden_sizes: tuple[int, ...] = (256, 128)  # Shared encoder layers
    value_hidden: int = 64  # Value stream hidden size
    advantage_hidden: int = 64  # Advantage stream hidden size
    learning_rate: float = 1e-4
    gradient_clip: float = 1.0  # Max gradient norm
    target_update_freq: int = 1000  # Steps between target network sync

    # Learning rate scheduling
    lr_scheduler: Literal['none', 'step', 'exponential', 'plateau', 'cosine'] = 'none'
    lr_step_size: int = 1000  # Steps between LR decay (for step scheduler)
    lr_gamma: float = 0.95  # LR decay factor
    lr_patience: int = 100  # Plateau patience (for plateau scheduler)
    lr_min: float = 1e-6  # Minimum learning rate
    lr_warmup_steps: int = 0  # Warmup steps (linear increase from 0 to lr)

    # Early stopping
    early_stopping_enable: bool = False
    early_stopping_patience: int = 50  # Updates without improvement before stopping
    early_stopping_min_delta: float = 1e-4  # Minimum improvement threshold
    early_stopping_check_freq: int = 10  # Check every N updates

    def validate(self) -> None:
        """Validate configuration parameters."""
        if not self.hidden_sizes:
            raise ValueError('hidden_sizes cannot be empty')
        if any(h <= 0 for h in self.hidden_sizes):
            raise ValueError(f'All hidden_sizes must be positive: {self.hidden_sizes}')
        if self.value_hidden <= 0:
            raise ValueError(f'value_hidden must be positive, got {self.value_hidden}')
        if self.advantage_hidden <= 0:
            raise ValueError(f'advantage_hidden must be positive, got {self.advantage_hidden}')
        if self.learning_rate <= 0:
            raise ValueError(f'learning_rate must be positive, got {self.learning_rate}')
        if self.gradient_clip <= 0:
            raise ValueError(f'gradient_clip must be positive, got {self.gradient_clip}')
        valid_schedulers = ('none', 'step', 'exponential', 'plateau', 'cosine')
        if self.lr_scheduler not in valid_schedulers:
            raise ValueError(f'lr_scheduler must be one of {valid_schedulers}, got {self.lr_scheduler}')
        if self.lr_step_size <= 0:
            raise ValueError(f'lr_step_size must be positive, got {self.lr_step_size}')
        if not 0.0 < self.lr_gamma <= 1.0:
            raise ValueError(f'lr_gamma must be in (0, 1], got {self.lr_gamma}')
        if self.lr_min < 0:
            raise ValueError(f'lr_min must be non-negative, got {self.lr_min}')
        if self.lr_warmup_steps < 0:
            raise ValueError(f'lr_warmup_steps must be non-negative, got {self.lr_warmup_steps}')
        if self.early_stopping_patience <= 0:
            raise ValueError(f'early_stopping_patience must be positive, got {self.early_stopping_patience}')
        if self.early_stopping_min_delta < 0:
            raise ValueError(f'early_stopping_min_delta must be non-negative, got {self.early_stopping_min_delta}')
        if self.early_stopping_check_freq <= 0:
            raise ValueError(f'early_stopping_check_freq must be positive, got {self.early_stopping_check_freq}')


@dataclass
class EarlyStoppingConfig:
    """Configuration for early stopping during training.

    Early stopping prevents overtraining by monitoring validation loss
    and stopping when improvement stalls.

    Reference: Prechelt (1998) "Early Stopping - But When?"
    """

    enable: bool = False
    patience: int = 50  # Updates without improvement before stopping
    min_delta: float = 1e-4  # Minimum improvement to count as progress
    validation_fraction: float = 0.1  # Fraction of buffer to use for validation
    check_frequency: int = 10  # Check validation every N updates
    restore_best: bool = True  # Restore best weights when stopping

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.patience <= 0:
            raise ValueError(f'patience must be positive, got {self.patience}')
        if self.min_delta < 0:
            raise ValueError(f'min_delta must be non-negative, got {self.min_delta}')
        if not 0.0 < self.validation_fraction < 1.0:
            raise ValueError(f'validation_fraction must be in (0, 1), got {self.validation_fraction}')
        if self.check_frequency <= 0:
            raise ValueError(f'check_frequency must be positive, got {self.check_frequency}')


@dataclass
class SequentialConfig:
    """Configuration for LSTM/Transformer sequential models.

    Sequential models capture temporal patterns by processing
    sequences of states instead of single states.

    References:
    - Hochreiter & Schmidhuber (1997) "Long Short-Term Memory"
    - Vaswani et al. (2017) "Attention Is All You Need"
    """

    enable: bool = False
    model_type: Literal['lstm', 'transformer'] = 'lstm'
    sequence_length: int = 50  # Number of historical states to consider
    hidden_size: int = 128
    num_layers: int = 2
    num_heads: int = 4  # Transformer only
    dropout: float = 0.1
    learning_rate: float = 1e-4

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.model_type not in ('lstm', 'transformer'):
            raise ValueError(f"model_type must be 'lstm' or 'transformer', got {self.model_type}")
        if self.sequence_length <= 0:
            raise ValueError(f'sequence_length must be positive, got {self.sequence_length}')
        if self.hidden_size <= 0:
            raise ValueError(f'hidden_size must be positive, got {self.hidden_size}')
        if self.num_layers <= 0:
            raise ValueError(f'num_layers must be positive, got {self.num_layers}')
        if self.num_heads <= 0:
            raise ValueError(f'num_heads must be positive, got {self.num_heads}')
        if self.model_type == 'transformer' and self.hidden_size % self.num_heads != 0:
            raise ValueError(
                f'hidden_size ({self.hidden_size}) must be divisible by num_heads ({self.num_heads}) for transformer'
            )
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError(f'dropout must be in [0, 1), got {self.dropout}')
        if self.learning_rate <= 0:
            raise ValueError(f'learning_rate must be positive, got {self.learning_rate}')


class EarlyStopping:
    """Early stopping tracker for neural network training.

    Monitors validation loss and signals when to stop training
    if no improvement is observed for a specified number of updates.

    Usage:
        early_stopping = EarlyStopping(config)
        for batch in data:
            loss = train(batch)
            if early_stopping.step(loss):
                break  # Stop training
        if early_stopping.should_restore:
            model.load_state_dict(early_stopping.best_weights)
    """

    def __init__(self, config: EarlyStoppingConfig):
        """Initialize early stopping tracker.

        Args:
            config: Early stopping configuration
        """
        self.config = config
        self.best_loss: float = float('inf')
        self.best_weights: dict[str, Any] | None = None
        self.counter: int = 0
        self.stopped: bool = False
        self.stop_step: int = 0

    def step(self, loss: float, weights: dict | None = None) -> bool:
        """Check if training should stop.

        Args:
            loss: Current validation loss
            weights: Current model weights (for restoration)

        Returns:
            True if training should stop
        """
        if not self.config.enable:
            return False

        if self.stopped:
            return True

        # Check for improvement
        if loss < self.best_loss - self.config.min_delta:
            self.best_loss = loss
            self.counter = 0
            if weights is not None and self.config.restore_best:
                # Deep copy weights
                self.best_weights = {
                    k: v.clone() if isinstance(v, torch.Tensor) else copy.deepcopy(v) for k, v in weights.items()
                }
        else:
            self.counter += 1

        # Check patience
        if self.counter >= self.config.patience:
            self.stopped = True
            return True

        return False

    def reset(self) -> None:
        """Reset early stopping state."""
        self.best_loss = float('inf')
        self.best_weights = None
        self.counter = 0
        self.stopped = False
        self.stop_step = 0

    @property
    def should_restore(self) -> bool:
        """Check if best weights should be restored."""
        return self.stopped and self.config.restore_best and self.best_weights is not None

    def get_stats(self) -> dict:
        """Get early stopping statistics.

        Returns:
            Dictionary with stats
        """
        return {
            'enabled': self.config.enable,
            'best_loss': self.best_loss,
            'counter': self.counter,
            'patience': self.config.patience,
            'stopped': self.stopped,
        }
