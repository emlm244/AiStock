"""
Machine Learning infrastructure for AIStock FSD trading agent.

This module provides advanced RL algorithms:
- Double Q-Learning (reduces overestimation bias)
- Prioritized Experience Replay (learns from important transitions)
- Dueling DQN (separates value and advantage)
- LSTM/Transformer (sequential pattern memory)
"""

from .config import (
    DoubleQLearningConfig,
    DuelingDQNConfig,
    PERConfig,
    SequentialConfig,
    Transition,
)
from .device import DeviceType, get_device

__all__ = [
    'DoubleQLearningConfig',
    'DuelingDQNConfig',
    'PERConfig',
    'SequentialConfig',
    'Transition',
    'get_device',
    'DeviceType',
]
