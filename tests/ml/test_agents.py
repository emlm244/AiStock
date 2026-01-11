"""Tests for RL agents."""

import numpy as np
import pytest
import tempfile
from pathlib import Path

from aistock.ml.agents.double_q import DoubleQAgent
from aistock.ml.config import Transition


class TestDoubleQAgent:
    """Tests for Double Q-Learning agent."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return DoubleQAgent(
            state_dim=4,
            learning_rate=0.1,
            discount_factor=0.95,
            exploration_rate=0.5,
            max_q_table_size=1000,
        )

    def test_initialization(self, agent):
        """Test agent initializes correctly."""
        assert agent.state_dim == 4
        assert agent.action_dim == 5  # BUY, SELL, HOLD, INCREASE, DECREASE
        assert agent.learning_rate == 0.1
        assert agent.exploration_rate == 0.5

    def test_select_action(self, agent):
        """Test action selection."""
        state = np.array([0.1, 0.2, 0.3, 0.4])

        # Test many selections to verify exploration
        actions = [agent.select_action(state, training=True) for _ in range(100)]

        # Should have some variety due to exploration
        unique_actions = set(actions)
        assert len(unique_actions) > 1

        # All actions should be valid
        valid_actions = {'BUY', 'SELL', 'HOLD', 'INCREASE_SIZE', 'DECREASE_SIZE'}
        assert all(a in valid_actions for a in actions)

    def test_select_action_greedy(self, agent):
        """Test greedy action selection (no exploration)."""
        state = np.array([0.1, 0.2, 0.3, 0.4])

        # Training=False should be deterministic
        actions = [agent.select_action(state, training=False) for _ in range(10)]

        # All actions should be the same (greedy)
        assert len(set(actions)) == 1

    def test_update(self, agent):
        """Test Q-value updates."""
        state = np.array([0.1, 0.2, 0.3, 0.4])
        next_state = np.array([0.2, 0.3, 0.4, 0.5])

        transitions = [
            Transition(
                state=state,
                action='BUY',
                reward=1.0,
                next_state=next_state,
                done=False,
            )
        ]
        weights = [1.0]

        # Get initial Q-values
        q_before = agent.get_q_values(state).copy()

        # Update
        metrics = agent.update(transitions, weights)

        # Get updated Q-values
        q_after = agent.get_q_values(state)

        # Q-value for 'BUY' should have changed
        assert q_after['BUY'] != q_before['BUY']

        # Metrics should be returned
        assert 'loss' in metrics
        assert 'td_error_mean' in metrics

    def test_dual_q_tables(self, agent):
        """Test that both Q-tables are maintained."""
        state = np.array([0.1, 0.2, 0.3, 0.4])

        # Initialize state in Q-tables
        agent.select_action(state, training=True)

        # Both tables should have entries
        assert len(agent._q1) > 0
        assert len(agent._q2) > 0

    def test_get_td_errors(self, agent):
        """Test TD error calculation."""
        transitions = [
            Transition(
                state=np.array([0.1, 0.2, 0.3, 0.4]),
                action='BUY',
                reward=1.0,
                next_state=np.array([0.2, 0.3, 0.4, 0.5]),
                done=False,
            ),
            Transition(
                state=np.array([0.2, 0.3, 0.4, 0.5]),
                action='SELL',
                reward=-0.5,
                next_state=np.array([0.3, 0.4, 0.5, 0.6]),
                done=True,
            ),
        ]

        td_errors = agent.get_td_errors(transitions)

        assert len(td_errors) == 2
        assert all(e >= 0 for e in td_errors)  # Absolute errors

    def test_exploration_decay(self, agent):
        """Test exploration rate decay."""
        initial_rate = agent.exploration_rate

        agent.decay_exploration()

        assert agent.exploration_rate < initial_rate

    def test_save_load_state(self, agent):
        """Test saving and loading agent state."""
        # Train agent a bit
        for _ in range(10):
            state = np.random.randn(4)
            agent.select_action(state, training=True)

        # Save state
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'agent_state.json'
            agent.save_state(path)

            # Create new agent and load
            new_agent = DoubleQAgent(
                state_dim=4,
                learning_rate=0.1,
                max_q_table_size=1000,
            )
            success = new_agent.load_state(path)

            assert success
            assert len(new_agent._q1) == len(agent._q1)
            assert len(new_agent._q2) == len(agent._q2)

    def test_q_table_capacity(self):
        """Test Q-table LRU eviction."""
        agent = DoubleQAgent(
            state_dim=4,
            max_q_table_size=10,
        )

        # Add many unique states
        for i in range(50):
            state = np.array([i, i + 1, i + 2, i + 3], dtype=np.float32)
            agent.select_action(state, training=True)

        # Should be at capacity
        assert len(agent._q1) <= 10
        assert len(agent._q2) <= 10

    def test_get_stats(self, agent):
        """Test agent statistics."""
        stats = agent.get_stats()

        assert stats['algorithm'] == 'double_q_learning'
        assert stats['state_dim'] == 4
        assert stats['action_dim'] == 5


class TestTransition:
    """Tests for Transition dataclass."""

    def test_transition_creation(self):
        """Test creating a transition."""
        t = Transition(
            state=np.array([1.0, 2.0]),
            action='BUY',
            reward=0.5,
            next_state=np.array([2.0, 3.0]),
            done=False,
        )

        assert t.action == 'BUY'
        assert t.reward == 0.5
        assert not t.done
        assert t.td_error == 0.0  # Default

    def test_transition_with_td_error(self):
        """Test transition with TD error."""
        t = Transition(
            state=np.array([1.0, 2.0]),
            action='SELL',
            reward=-0.5,
            next_state=np.array([2.0, 3.0]),
            done=True,
            td_error=0.25,
        )

        assert t.td_error == 0.25
        assert t.done

    def test_transition_converts_to_numpy(self):
        """Test that state arrays are converted to numpy."""
        t = Transition(
            state=[1.0, 2.0],  # List input
            action='HOLD',
            reward=0.0,
            next_state=[2.0, 3.0],  # List input
            done=False,
        )

        assert isinstance(t.state, np.ndarray)
        assert isinstance(t.next_state, np.ndarray)
        assert t.state.dtype == np.float32
