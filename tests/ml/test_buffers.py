"""Tests for experience replay buffers."""

import math

import numpy as np
import pytest

from aistock.ml.buffers.prioritized import PrioritizedReplayBuffer
from aistock.ml.buffers.sum_tree import SumTree
from aistock.ml.buffers.uniform import UniformReplayBuffer
from aistock.ml.config import PERConfig, Transition


class TestSumTree:
    """Tests for SumTree data structure."""

    def test_initialization(self):
        """Test sum tree initializes correctly."""
        tree = SumTree(capacity=10)
        assert len(tree) == 0
        assert tree.total == 0.0
        assert tree.capacity == 10

    def test_add_single_item(self):
        """Test adding a single item."""
        tree = SumTree(capacity=10)
        tree.add(priority=1.5, data='test')

        assert len(tree) == 1
        assert tree.total == 1.5

    def test_add_multiple_items(self):
        """Test adding multiple items."""
        tree = SumTree(capacity=10)
        tree.add(1.0, 'a')
        tree.add(2.0, 'b')
        tree.add(3.0, 'c')

        assert len(tree) == 3
        assert tree.total == 6.0

    def test_capacity_overflow(self):
        """Test that capacity is respected with LRU eviction."""
        tree = SumTree(capacity=3)

        for i in range(5):
            tree.add(1.0, f'item_{i}')

        assert len(tree) == 3
        assert tree.total == 3.0

    def test_get_by_cumsum(self):
        """Test sampling by cumulative sum."""
        tree = SumTree(capacity=10)
        tree.add(1.0, 'a')
        tree.add(2.0, 'b')
        tree.add(3.0, 'c')

        # Sample at cumsum = 0.5 should get 'a' (priority 1.0)
        _idx, _priority, data = tree.get(0.5)
        assert data == 'a'

        # Sample at cumsum = 1.5 should get 'b' (priorities: 1+2=3 boundary)
        _idx, _priority, data = tree.get(1.5)
        assert data == 'b'

    def test_update_priority(self):
        """Test updating priorities."""
        tree = SumTree(capacity=10)
        tree.add(1.0, 'a')
        tree.add(2.0, 'b')

        # Get index of first item
        idx, _, _ = tree.get(0.5)

        # Update priority
        tree.update(idx, 5.0)

        assert tree.total == 7.0  # 5 + 2

    def test_min_max_priority(self):
        """Test min/max priority tracking."""
        tree = SumTree(capacity=10)
        tree.add(1.0, 'a')
        tree.add(5.0, 'b')
        tree.add(2.0, 'c')

        assert tree.max_priority == 5.0
        assert tree.min_priority == 1.0

    def test_invalid_capacity(self):
        """Test that invalid capacity raises error."""
        with pytest.raises(ValueError):
            SumTree(capacity=0)

        with pytest.raises(ValueError):
            SumTree(capacity=-1)

    def test_negative_priority_rejected(self):
        """Test that negative priorities are rejected."""
        tree = SumTree(capacity=10)

        with pytest.raises(ValueError):
            tree.add(-1.0, 'test')


class TestUniformReplayBuffer:
    """Tests for uniform replay buffer."""

    def test_initialization(self):
        """Test buffer initializes correctly."""
        buffer = UniformReplayBuffer(capacity=100)
        assert len(buffer) == 0
        assert buffer.capacity == 100

    def test_add_and_sample(self):
        """Test adding and sampling transitions."""
        buffer = UniformReplayBuffer(capacity=100)

        # Add transitions
        for i in range(50):
            transition = Transition(
                state=np.array([i, i + 1], dtype=np.float32),
                action='BUY',
                reward=float(i),
                next_state=np.array([i + 1, i + 2], dtype=np.float32),
                done=False,
            )
            buffer.add(transition)

        assert len(buffer) == 50

        # Sample
        transitions, weights, indices = buffer.sample(batch_size=10)

        assert len(transitions) == 10
        assert len(weights) == 10
        assert all(w == 1.0 for w in weights)  # Uniform weights
        assert len(indices) == 10

    def test_is_ready(self):
        """Test is_ready check."""
        buffer = UniformReplayBuffer(capacity=100)

        assert not buffer.is_ready(10)

        for _ in range(10):
            buffer.add(
                Transition(
                    state=np.zeros(2),
                    action='HOLD',
                    reward=0.0,
                    next_state=np.zeros(2),
                    done=False,
                )
            )

        assert buffer.is_ready(10)
        assert not buffer.is_ready(11)

    def test_capacity_overflow(self):
        """Test that old items are evicted."""
        buffer = UniformReplayBuffer(capacity=10)

        for i in range(20):
            buffer.add(
                Transition(
                    state=np.array([i]),
                    action='HOLD',
                    reward=float(i),
                    next_state=np.array([i + 1]),
                    done=False,
                )
            )

        assert len(buffer) == 10

        # Sample and verify we have recent items
        transitions, _, _ = buffer.sample(10)
        rewards = [t.reward for t in transitions]

        # All rewards should be >= 10 (old ones evicted)
        assert all(r >= 10 for r in rewards)


class TestPrioritizedReplayBuffer:
    """Tests for PER buffer."""

    @pytest.fixture
    def per_config(self):
        """Create test PER config."""
        return PERConfig(
            enable=True,
            buffer_size=100,
            alpha=0.6,
            beta_start=0.4,
            beta_end=1.0,
            beta_annealing_steps=1000,
            min_priority=1e-6,
            batch_size=8,
        )

    def test_initialization(self, per_config):
        """Test buffer initializes correctly."""
        buffer = PrioritizedReplayBuffer(per_config)
        assert len(buffer) == 0

    def test_add_and_sample(self, per_config):
        """Test adding and sampling with priorities."""
        buffer = PrioritizedReplayBuffer(per_config)

        # Add transitions
        for i in range(50):
            transition = Transition(
                state=np.array([i, i + 1], dtype=np.float32),
                action='BUY',
                reward=float(i),
                next_state=np.array([i + 1, i + 2], dtype=np.float32),
                done=False,
            )
            buffer.add(transition)

        assert len(buffer) == 50

        # Sample
        transitions, weights, indices = buffer.sample(batch_size=8)

        assert len(transitions) == 8
        assert len(weights) == 8
        assert len(indices) == 8

        # Weights should be normalized
        assert max(weights) <= 1.0

    def test_priority_updates(self, per_config):
        """Test updating priorities based on TD errors."""
        buffer = PrioritizedReplayBuffer(per_config)

        # Add transitions
        for i in range(20):
            buffer.add(
                Transition(
                    state=np.array([i]),
                    action='HOLD',
                    reward=float(i),
                    next_state=np.array([i + 1]),
                    done=False,
                )
            )

        # Sample and update priorities
        _, _, indices = buffer.sample(batch_size=5)
        td_errors = [1.0, 2.0, 3.0, 4.0, 5.0]

        buffer.update_priorities(indices, td_errors)

        # Verify max priority was updated
        stats = buffer.get_stats()
        assert stats['max_priority'] >= 5.0

    def test_beta_annealing(self, per_config):
        """Test beta annealing schedule."""
        # At step 0
        assert per_config.get_beta(0) == 0.4

        # At step 1000 (end of annealing)
        assert per_config.get_beta(1000) == 1.0

        # Halfway
        assert math.isclose(per_config.get_beta(500), 0.7, rel_tol=0, abs_tol=1e-6)

    def test_is_ready(self, per_config):
        """Test is_ready check."""
        buffer = PrioritizedReplayBuffer(per_config)

        assert not buffer.is_ready()  # Default uses batch_size=8

        for _ in range(10):
            buffer.add(
                Transition(
                    state=np.zeros(2),
                    action='HOLD',
                    reward=0.0,
                    next_state=np.zeros(2),
                    done=False,
                )
            )

        assert buffer.is_ready()

    def test_get_stats(self, per_config):
        """Test buffer statistics."""
        buffer = PrioritizedReplayBuffer(per_config)

        for _ in range(10):
            buffer.add(
                Transition(
                    state=np.zeros(2),
                    action='HOLD',
                    reward=0.0,
                    next_state=np.zeros(2),
                    done=False,
                )
            )

        stats = buffer.get_stats()

        assert stats['size'] == 10
        assert stats['capacity'] == 100
        assert stats['max_priority'] >= 1.0
