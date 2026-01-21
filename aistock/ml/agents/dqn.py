"""DQN/Dueling DQN agent with neural network function approximation.

Uses PyTorch neural networks for Q-value estimation, supporting
both standard DQN and Dueling DQN architectures.

References:
- Mnih et al. (2015) "Human-level control through deep RL"
- Wang et al. (2016) "Dueling Network Architectures"
"""

import logging
import random
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim import lr_scheduler

from ..config import DuelingDQNConfig, EarlyStopping, EarlyStoppingConfig, SequenceTransition, Transition
from ..device import get_device
from ..networks import DuelingNetwork
from .base import BaseAgent

logger = logging.getLogger(__name__)

TransitionType = Transition | SequenceTransition


class DQNAgent(BaseAgent):
    """DQN agent with neural network function approximation.

    Supports Dueling DQN architecture for better value estimation.
    Uses a target network for stable training.
    """

    def __init__(
        self,
        state_dim: int,
        config: DuelingDQNConfig | None = None,
        learning_rate: float = 1e-4,
        discount_factor: float = 0.95,
        exploration_rate: float = 0.1,
        exploration_decay: float = 0.995,
        min_exploration_rate: float = 0.05,
        device: str = 'auto',
    ):
        """Initialize the DQN agent.

        Args:
            state_dim: Dimension of state feature vector
            config: Optional DuelingDQNConfig
            learning_rate: Learning rate for optimizer
            discount_factor: Discount factor (gamma)
            exploration_rate: Initial exploration rate (epsilon)
            exploration_decay: Exploration decay per episode
            min_exploration_rate: Minimum exploration rate
            device: Device preference ('auto', 'cpu', 'cuda', 'mps')
        """
        validated_config = config or DuelingDQNConfig()
        validated_config.validate()
        if learning_rate <= 0:
            raise ValueError('learning_rate must be positive')
        if not 0 <= discount_factor <= 1:
            raise ValueError('discount_factor must be in [0, 1]')
        if not 0 <= exploration_rate <= 1:
            raise ValueError('exploration_rate must be in [0, 1]')
        if not 0 <= exploration_decay <= 1:
            raise ValueError('exploration_decay must be in [0, 1]')
        if not 0 <= min_exploration_rate <= 1:
            raise ValueError('min_exploration_rate must be in [0, 1]')

        super().__init__(
            state_dim=state_dim,
            learning_rate=learning_rate,
            discount_factor=discount_factor,
            exploration_rate=exploration_rate,
            exploration_decay=exploration_decay,
            min_exploration_rate=min_exploration_rate,
        )

        self.config = validated_config
        self.device = get_device(device)  # type: ignore

        # Build networks
        self._build_networks()

        # Optimizer
        effective_lr = self.config.learning_rate if config is not None else learning_rate
        self.optimizer = optim.Adam(
            self.policy_net.parameters(),
            lr=effective_lr,
        )

        # Learning rate scheduler
        self.scheduler = self._build_scheduler()
        self._warmup_steps = self.config.lr_warmup_steps
        self._base_lr = effective_lr

        # Early stopping
        early_stop_config = EarlyStoppingConfig(
            enable=self.config.early_stopping_enable,
            patience=self.config.early_stopping_patience,
            min_delta=self.config.early_stopping_min_delta,
            check_frequency=self.config.early_stopping_check_freq,
            restore_best=True,
        )
        self.early_stopping = EarlyStopping(early_stop_config)
        self._training_stopped = False

        # Loss function
        self.loss_fn = nn.SmoothL1Loss(reduction='none')  # Huber loss

        # Target network sync counter
        self._sync_counter = 0

    def _build_networks(self) -> None:
        """Build policy and target networks."""
        # Policy network (trained)
        self.policy_net = DuelingNetwork(
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            hidden_sizes=self.config.hidden_sizes,
            value_hidden=self.config.value_hidden,
            advantage_hidden=self.config.advantage_hidden,
        ).to(self.device)

        # Target network (periodically synced)
        self.target_net = DuelingNetwork(
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            hidden_sizes=self.config.hidden_sizes,
            value_hidden=self.config.value_hidden,
            advantage_hidden=self.config.advantage_hidden,
        ).to(self.device)

        # Initialize target with policy weights
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()  # Target is never trained directly

    def _build_scheduler(self) -> lr_scheduler.LRScheduler | None:
        """Build learning rate scheduler based on config.

        Returns:
            LR scheduler instance or None if disabled
        """
        scheduler_type = self.config.lr_scheduler
        if scheduler_type == 'none':
            return None

        if scheduler_type == 'step':
            return lr_scheduler.StepLR(
                self.optimizer,
                step_size=self.config.lr_step_size,
                gamma=self.config.lr_gamma,
            )
        elif scheduler_type == 'exponential':
            return lr_scheduler.ExponentialLR(
                self.optimizer,
                gamma=self.config.lr_gamma,
            )
        elif scheduler_type == 'plateau':
            return lr_scheduler.ReduceLROnPlateau(
                self.optimizer,
                mode='min',
                factor=self.config.lr_gamma,
                patience=self.config.lr_patience,
                min_lr=self.config.lr_min,
            )
        elif scheduler_type == 'cosine':
            return lr_scheduler.CosineAnnealingLR(
                self.optimizer,
                T_max=self.config.lr_step_size,
                eta_min=self.config.lr_min,
            )
        else:
            logger.warning(f'Unknown scheduler type: {scheduler_type}, using none')
            return None

    def _apply_warmup(self) -> None:
        """Apply linear warmup to learning rate if in warmup phase."""
        if self._warmup_steps <= 0 or self.total_updates >= self._warmup_steps:
            return

        # Linear warmup: lr = base_lr * (step / warmup_steps)
        warmup_factor = self.total_updates / self._warmup_steps
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = self._base_lr * warmup_factor

    def get_current_lr(self) -> float:
        """Get current learning rate.

        Returns:
            Current learning rate
        """
        return self.optimizer.param_groups[0]['lr']

    def is_training_stopped(self) -> bool:
        """Check if training has been stopped by early stopping.

        Returns:
            True if training has been stopped
        """
        return self._training_stopped

    def select_action(self, state: np.ndarray, training: bool = True) -> str:
        """Select action using epsilon-greedy policy.

        Args:
            state: State feature vector
            training: Whether to use exploration

        Returns:
            Selected action name
        """
        # Epsilon-greedy exploration
        if training and random.random() < self.exploration_rate:
            return random.choice(self.ACTIONS)

        # Greedy action from policy network
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.policy_net(state_tensor)
            action_idx = q_values.argmax(dim=1).item()
            return self.index_to_action(int(action_idx))

    def update(self, transitions: list[TransitionType], weights: list[float]) -> dict[str, float]:
        """Update networks from a batch of transitions.

        Args:
            transitions: Batch of (s, a, r, s', done) transitions
            weights: Importance sampling weights (for PER)

        Returns:
            Dictionary with training metrics
        """
        if not transitions:
            return {'loss': 0.0, 'td_error_mean': 0.0}

        # Prepare batch tensors
        states = torch.FloatTensor(np.array([t.state for t in transitions])).to(self.device)

        actions = torch.LongTensor([self.action_to_index(t.action) for t in transitions]).to(self.device)

        rewards = torch.FloatTensor([t.reward for t in transitions]).to(self.device)

        next_states = torch.FloatTensor(np.array([t.next_state for t in transitions])).to(self.device)

        dones = torch.FloatTensor([float(t.done) for t in transitions]).to(self.device)

        if not weights:
            weights_list = [1.0] * len(transitions)
        elif len(weights) != len(transitions):
            raise ValueError(f'weights length {len(weights)} does not match transitions {len(transitions)}')
        else:
            weights_list = list(weights)

        weights_tensor = torch.FloatTensor(weights_list).to(self.device)

        # Current Q-values
        current_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target Q-values (Double DQN: use policy_net for action selection)
        with torch.no_grad():
            # Select best action using policy network
            next_actions = self.policy_net(next_states).argmax(dim=1)
            # Evaluate using target network
            next_q = self.target_net(next_states).gather(1, next_actions.unsqueeze(1)).squeeze(1)
            target_q = rewards + self.discount_factor * next_q * (1 - dones)

        # Compute TD errors for PER priority updates
        td_errors = (target_q - current_q).abs().detach().cpu().numpy()

        # Weighted loss (importance sampling)
        losses = self.loss_fn(current_q, target_q)
        loss = (losses * weights_tensor).mean()

        # Optimize
        self.optimizer.zero_grad()
        loss.backward()

        # Gradient clipping
        if self.config.gradient_clip > 0:
            nn.utils.clip_grad_norm_(
                self.policy_net.parameters(),
                self.config.gradient_clip,
            )

        self.optimizer.step()

        # Sync target network periodically
        self._sync_counter += 1
        if self._sync_counter >= self.config.target_update_freq:
            self._sync_target_network()
            self._sync_counter = 0

        self.total_updates += 1

        # Apply warmup or step scheduler
        if self.total_updates <= self._warmup_steps:
            self._apply_warmup()
        elif self.scheduler is not None:
            if isinstance(self.scheduler, lr_scheduler.ReduceLROnPlateau):
                # Plateau scheduler uses loss
                self.scheduler.step(loss.item())
            else:
                self.scheduler.step()

        # Check early stopping (every check_frequency updates)
        early_stopped = False
        if self.config.early_stopping_enable and self.total_updates % self.config.early_stopping_check_freq == 0:
            early_stopped = self.early_stopping.step(
                loss.item(),
                weights=self.policy_net.state_dict(),
            )
            if early_stopped:
                self._training_stopped = True
                logger.info(f'Early stopping triggered at update {self.total_updates}')
                # Restore best weights if available
                if self.early_stopping.should_restore and self.early_stopping.best_weights:
                    self.policy_net.load_state_dict(self.early_stopping.best_weights)
                    logger.info(f'Restored best weights (loss: {self.early_stopping.best_loss:.6f})')

        return {
            'loss': float(loss.item()),
            'td_error_mean': float(np.mean(td_errors)),
            'td_error_max': float(np.max(td_errors)),
            'q_mean': float(current_q.mean().item()),
            'q_max': float(current_q.max().item()),
            'learning_rate': self.get_current_lr(),
            'early_stopped': early_stopped,
            'early_stopping_counter': self.early_stopping.counter,
        }

    def _sync_target_network(self) -> None:
        """Sync target network with policy network weights."""
        self.target_net.load_state_dict(self.policy_net.state_dict())
        logger.debug('Synced target network')

    def get_td_errors(self, transitions: list[TransitionType]) -> list[float]:
        """Calculate TD errors for priority updates.

        Args:
            transitions: Batch of transitions

        Returns:
            List of absolute TD errors
        """
        with torch.no_grad():
            states = torch.FloatTensor(np.array([t.state for t in transitions])).to(self.device)

            actions = torch.LongTensor([self.action_to_index(t.action) for t in transitions]).to(self.device)

            rewards = torch.FloatTensor([t.reward for t in transitions]).to(self.device)

            next_states = torch.FloatTensor(np.array([t.next_state for t in transitions])).to(self.device)

            dones = torch.FloatTensor([float(t.done) for t in transitions]).to(self.device)

            current_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

            next_actions = self.policy_net(next_states).argmax(dim=1)
            next_q = self.target_net(next_states).gather(1, next_actions.unsqueeze(1)).squeeze(1)
            target_q = rewards + self.discount_factor * next_q * (1 - dones)

            td_errors = (target_q - current_q).abs().cpu().numpy()

        return td_errors.tolist()

    def get_q_values(self, state: np.ndarray) -> dict[str, float]:
        """Get Q-values for a state.

        Args:
            state: State feature vector

        Returns:
            Dictionary of action -> Q-value
        """
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.policy_net(state_tensor).squeeze(0).cpu().numpy()

        return {action: float(q_values[i]) for i, action in enumerate(self.ACTIONS)}

    def save_state(self, path: str | Path) -> None:
        """Save agent state to file.

        Args:
            path: Path to save the state
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        state = {
            'version': '3.1',
            'algorithm': 'dueling_dqn',
            'policy_net': self.policy_net.state_dict(),
            'target_net': self.target_net.state_dict(),
            'optimizer': self.optimizer.state_dict(),
            'scheduler': self.scheduler.state_dict() if self.scheduler else None,
            'exploration_rate': self.exploration_rate,
            'total_updates': self.total_updates,
            'total_episodes': self.total_episodes,
            'sync_counter': self._sync_counter,
            'config': {
                'hidden_sizes': self.config.hidden_sizes,
                'value_hidden': self.config.value_hidden,
                'advantage_hidden': self.config.advantage_hidden,
                'learning_rate': self.config.learning_rate,
                'gradient_clip': self.config.gradient_clip,
                'target_update_freq': self.config.target_update_freq,
                'lr_scheduler': self.config.lr_scheduler,
            },
        }

        torch.save(state, path)
        logger.info(f'Saved DQN state to {path} ({self.policy_net.count_parameters()} parameters)')

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
            version_str = torch.__version__.split('+', 1)[0]
            version_parts = version_str.split('.')
            major = int(version_parts[0]) if version_parts else 0
            minor = int(version_parts[1]) if len(version_parts) > 1 else 0
            if (major, minor) < (2, 6):
                raise RuntimeError('Loading DQN checkpoints requires torch>=2.6.0')

            state = torch.load(path, map_location=self.device, weights_only=False)

            self.policy_net.load_state_dict(state['policy_net'])
            self.target_net.load_state_dict(state['target_net'])
            self.optimizer.load_state_dict(state['optimizer'])
            if self.scheduler and state.get('scheduler'):
                self.scheduler.load_state_dict(state['scheduler'])
            self.exploration_rate = state.get('exploration_rate', self.exploration_rate)
            self.total_updates = state.get('total_updates', 0)
            self.total_episodes = state.get('total_episodes', 0)
            self._sync_counter = state.get('sync_counter', 0)

            logger.info(f'Loaded DQN state from {path} ({self.policy_net.count_parameters()} parameters)')
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
                'algorithm': 'dueling_dqn',
                'device': str(self.device),
                'parameters': self.policy_net.count_parameters(),
                'hidden_sizes': self.config.hidden_sizes,
                'learning_rate': self.get_current_lr(),
                'lr_scheduler': self.config.lr_scheduler,
                'early_stopping': self.early_stopping.get_stats(),
                'training_stopped': self._training_stopped,
            }
        )
        return stats
