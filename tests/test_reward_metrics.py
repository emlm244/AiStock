"""
Unit tests for enhanced reward shaping.

Tests the RewardMetricsTracker class and enhanced reward calculation.
"""

import math
import threading
from decimal import Decimal

import pytest

from aistock.fsd import (
    FSDConfig,
    FSDEngine,
    RewardMetricsState,
    RewardMetricsTracker,
)
from aistock.portfolio import Portfolio


class TestRewardMetricsTracker:
    """Tests for RewardMetricsTracker class."""

    def test_initial_state(self):
        """Tracker starts with correct initial values."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        assert tracker.get_current_drawdown() == 0.0
        assert tracker.get_streak_bonus() == 0.0
        assert tracker.get_rolling_sharpe() == 0.0
        assert tracker.get_rolling_sortino() == 0.0

    def test_record_winning_trade(self):
        """Recording a winning trade updates streak correctly."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)
        tracker.record_trade(pnl=100.0, new_equity=10100.0)

        assert tracker.get_streak_bonus() > 0.0

    def test_record_losing_trade(self):
        """Recording a losing trade gives negative streak."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)
        tracker.record_trade(pnl=-100.0, new_equity=9900.0)

        assert tracker.get_streak_bonus() < 0.0

    def test_consecutive_wins_build_streak(self):
        """Multiple consecutive wins increase streak bonus."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        tracker.record_trade(pnl=100.0, new_equity=10100.0)
        bonus_1 = tracker.get_streak_bonus()

        tracker.record_trade(pnl=100.0, new_equity=10200.0)
        bonus_2 = tracker.get_streak_bonus()

        tracker.record_trade(pnl=100.0, new_equity=10300.0)
        bonus_3 = tracker.get_streak_bonus()

        assert bonus_2 > bonus_1
        assert bonus_3 > bonus_2

    def test_losing_trade_resets_win_streak(self):
        """Losing trade after wins resets win streak."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        # Build up wins
        tracker.record_trade(pnl=100.0, new_equity=10100.0)
        tracker.record_trade(pnl=50.0, new_equity=10150.0)
        assert tracker.get_streak_bonus() > 0.0

        # Loss resets to negative
        tracker.record_trade(pnl=-200.0, new_equity=9950.0)
        assert tracker.get_streak_bonus() < 0.0

    def test_drawdown_calculation(self):
        """Drawdown correctly tracks peak and current equity."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        # New peak
        tracker.record_trade(pnl=500.0, new_equity=10500.0)
        assert tracker.get_current_drawdown() == 0.0  # At peak

        # Drawdown
        tracker.record_trade(pnl=-1000.0, new_equity=9500.0)
        expected_dd = (10500 - 9500) / 10500
        assert abs(tracker.get_current_drawdown() - expected_dd) < 0.0001

    def test_drawdown_recovers(self):
        """Drawdown decreases as equity recovers."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        # Create drawdown
        tracker.record_trade(pnl=-500.0, new_equity=9500.0)
        dd_1 = tracker.get_current_drawdown()
        assert dd_1 > 0

        # Partial recovery
        tracker.record_trade(pnl=250.0, new_equity=9750.0)
        dd_2 = tracker.get_current_drawdown()
        assert dd_2 < dd_1

    def test_rolling_sharpe_requires_data(self):
        """Sharpe returns 0.0 with insufficient data."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        # Only 1 trade - not enough for variance
        tracker.record_trade(pnl=100.0, new_equity=10100.0)
        assert tracker.get_rolling_sharpe() == 0.0

    def test_rolling_sharpe_with_data(self):
        """Sharpe returns valid value with sufficient data."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        equity = 10000.0
        for i in range(10):
            pnl = 100.0 if i % 2 == 0 else -50.0
            equity += pnl
            tracker.record_trade(pnl=pnl, new_equity=equity)

        # Net positive returns should give positive Sharpe
        sharpe = tracker.get_rolling_sharpe()
        assert sharpe > 0.0

    def test_rolling_sharpe_negative_returns(self):
        """Sharpe is negative for consistently losing trades."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        equity = 10000.0
        for _ in range(10):
            pnl = -50.0
            equity += pnl
            tracker.record_trade(pnl=pnl, new_equity=equity)

        sharpe = tracker.get_rolling_sharpe()
        assert sharpe < 0.0

    def test_sortino_no_downside(self):
        """Sortino returns inf when no downside trades."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        equity = 10000.0
        for _ in range(5):
            equity += 100.0
            tracker.record_trade(pnl=100.0, new_equity=equity)

        assert tracker.get_rolling_sortino() == float('inf')

    def test_sortino_with_downside(self):
        """Sortino returns finite value with downside trades."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        equity = 10000.0
        # Mix of wins and losses (more losses)
        for i in range(10):
            pnl = 50.0 if i % 3 == 0 else -30.0
            equity += pnl
            tracker.record_trade(pnl=pnl, new_equity=equity)

        sortino = tracker.get_rolling_sortino()
        assert sortino != float('inf')
        assert not math.isnan(sortino)

    def test_state_persistence_roundtrip(self):
        """State can be saved and restored."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        # Build up some state
        tracker.record_trade(pnl=100.0, new_equity=10100.0)
        tracker.record_trade(pnl=100.0, new_equity=10200.0)
        tracker.record_trade(pnl=-50.0, new_equity=10150.0)

        original_dd = tracker.get_current_drawdown()
        original_streak = tracker.get_streak_bonus()

        # Save state
        state = tracker.get_state()

        # Create new tracker and restore
        new_tracker = RewardMetricsTracker(window_size=50, initial_equity=5000.0)
        new_tracker.restore_state(state)

        assert abs(new_tracker.get_current_drawdown() - original_dd) < 0.0001
        assert abs(new_tracker.get_streak_bonus() - original_streak) < 0.0001

    def test_streak_bonus_saturation(self):
        """Streak bonus saturates via tanh."""
        tracker = RewardMetricsTracker(window_size=50, initial_equity=10000.0)

        # Many consecutive wins
        equity = 10000.0
        for _ in range(20):
            equity += 100.0
            tracker.record_trade(pnl=100.0, new_equity=equity)

        bonus = tracker.get_streak_bonus()
        # tanh saturates at ~1.0
        assert 0.9 < bonus <= 1.0

    def test_thread_safety(self):
        """Concurrent access does not corrupt state."""
        tracker = RewardMetricsTracker(window_size=100, initial_equity=10000.0)
        errors: list[Exception] = []

        def record_trades():
            try:
                for i in range(50):
                    tracker.record_trade(pnl=10.0, new_equity=10000.0 + i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_trades) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestEnhancedRewardCalculation:
    """Tests for enhanced _calculate_reward method."""

    def test_legacy_mode_unchanged(self):
        """With enhanced rewards disabled, behavior matches legacy."""
        config = FSDConfig(enable_enhanced_rewards=False)
        portfolio = Portfolio(cash=Decimal('10000'))
        engine = FSDEngine(config, portfolio)

        reward = engine._calculate_reward(pnl=100.0, price=50.0, quantity=10.0)

        # Manual legacy calc
        position_value = 50.0 * 10.0
        expected = 100.0 - (0.1 * position_value) - (0.001 * position_value)

        assert abs(reward - expected) < 0.0001

    def test_enhanced_mode_enabled(self):
        """With enhanced rewards enabled, uses new calculation."""
        config = FSDConfig(
            enable_enhanced_rewards=True,
            base_pnl_weight=0.1,
            sharpe_weight=0.35,
            sortino_weight=0.25,
            drawdown_penalty_weight=0.25,
            streak_bonus_weight=0.05,
        )
        portfolio = Portfolio(cash=Decimal('10000'))
        engine = FSDEngine(config, portfolio)

        # Record some trades to populate metrics
        for _ in range(10):
            engine._reward_tracker.record_trade(pnl=50.0, new_equity=10050.0)

        reward = engine._calculate_reward(pnl=100.0, price=50.0, quantity=10.0)

        # Reward should be in reasonable range (normalized)
        assert -2.0 < reward < 2.0

    def test_enhanced_reward_with_drawdown_penalty(self):
        """Drawdown penalty reduces reward."""
        config = FSDConfig(
            enable_enhanced_rewards=True,
            base_pnl_weight=0.1,
            sharpe_weight=0.35,
            sortino_weight=0.25,
            drawdown_penalty_weight=0.25,
            streak_bonus_weight=0.05,
        )
        portfolio = Portfolio(cash=Decimal('10000'))
        engine = FSDEngine(config, portfolio)

        # Simulate trades to build up metrics
        equity = 10000.0
        for _ in range(5):
            equity += 100.0
            engine._reward_tracker.record_trade(pnl=100.0, new_equity=equity)

        reward_at_peak = engine._calculate_reward(pnl=100.0, price=50.0, quantity=10.0)

        # Now create a drawdown
        engine._reward_tracker.record_trade(pnl=-500.0, new_equity=equity - 500.0)

        reward_in_drawdown = engine._calculate_reward(pnl=100.0, price=50.0, quantity=10.0)

        # Reward should be lower during drawdown
        assert reward_in_drawdown < reward_at_peak

    def test_enhanced_reward_streak_bonus(self):
        """Win streak bonus increases reward."""
        config = FSDConfig(
            enable_enhanced_rewards=True,
            base_pnl_weight=0.1,
            sharpe_weight=0.35,
            sortino_weight=0.25,
            drawdown_penalty_weight=0.25,
            streak_bonus_weight=0.05,
        )
        portfolio = Portfolio(cash=Decimal('10000'))
        engine = FSDEngine(config, portfolio)

        # Record a loss to start
        engine._reward_tracker.record_trade(pnl=-50.0, new_equity=9950.0)

        reward_after_loss = engine._calculate_reward(pnl=100.0, price=50.0, quantity=10.0)

        # Build win streak
        equity = 9950.0
        for _ in range(5):
            equity += 100.0
            engine._reward_tracker.record_trade(pnl=100.0, new_equity=equity)

        reward_after_wins = engine._calculate_reward(pnl=100.0, price=50.0, quantity=10.0)

        # Reward should be higher after win streak
        assert reward_after_wins > reward_after_loss


class TestFSDConfigValidation:
    """Tests for FSDConfig reward weights validation."""

    def test_valid_weights_pass_validation(self):
        """Valid weights (summing to 1.0) pass validation."""
        config = FSDConfig(
            enable_enhanced_rewards=True,
            base_pnl_weight=0.1,
            sharpe_weight=0.35,
            sortino_weight=0.25,
            drawdown_penalty_weight=0.25,
            streak_bonus_weight=0.05,
        )
        config.validate()  # Should not raise

    def test_invalid_weights_sum_fails(self):
        """Weights not summing to 1.0 fail validation."""
        config = FSDConfig(
            enable_enhanced_rewards=True,
            base_pnl_weight=0.5,  # Now sums to 1.4
            sharpe_weight=0.35,
            sortino_weight=0.25,
            drawdown_penalty_weight=0.25,
            streak_bonus_weight=0.05,
        )
        with pytest.raises(ValueError, match='Reward weights must sum to 1.0'):
            config.validate()

    def test_negative_weight_fails(self):
        """Negative weights fail validation."""
        config = FSDConfig(
            enable_enhanced_rewards=True,
            base_pnl_weight=-0.1,  # Negative
            sharpe_weight=0.45,
            sortino_weight=0.25,
            drawdown_penalty_weight=0.25,
            streak_bonus_weight=0.15,
        )
        with pytest.raises(ValueError, match='non-negative'):
            config.validate()

    def test_small_window_size_fails(self):
        """Window size < 10 fails validation."""
        config = FSDConfig(
            enable_enhanced_rewards=True,
            reward_window_size=5,  # Too small
        )
        with pytest.raises(ValueError, match='reward_window_size must be >= 10'):
            config.validate()

    def test_validation_skipped_when_disabled(self):
        """Enhanced reward validation skipped when disabled."""
        config = FSDConfig(
            enable_enhanced_rewards=False,
            reward_window_size=1,  # Would fail if enabled
            base_pnl_weight=0.0,  # Would fail sum check if enabled
        )
        config.validate()  # Should not raise


class TestFSDEngineStatePersistence:
    """Tests for reward metrics state persistence in FSDEngine."""

    def test_save_load_preserves_reward_metrics(self, tmp_path):
        """Save and load preserves reward tracker state."""
        config = FSDConfig(enable_enhanced_rewards=True)
        portfolio = Portfolio(cash=Decimal('10000'))
        engine = FSDEngine(config, portfolio)

        # Build up reward metrics state
        equity = 10000.0
        for i in range(5):
            pnl = 100.0 if i % 2 == 0 else -50.0
            equity += pnl
            engine._reward_tracker.record_trade(pnl=pnl, new_equity=equity)

        original_dd = engine._reward_tracker.get_current_drawdown()
        original_sharpe = engine._reward_tracker.get_rolling_sharpe()

        # Save state
        filepath = str(tmp_path / 'fsd_state.json')
        engine.save_state(filepath)

        # Create new engine and load
        new_engine = FSDEngine(config, Portfolio(cash=Decimal('10000')))
        assert new_engine.load_state(filepath)

        # Verify metrics restored
        assert abs(new_engine._reward_tracker.get_current_drawdown() - original_dd) < 0.0001
        # Sharpe may differ slightly due to floating point, but should be close
        restored_sharpe = new_engine._reward_tracker.get_rolling_sharpe()
        assert abs(restored_sharpe - original_sharpe) < 0.1

    def test_load_old_state_without_reward_metrics(self, tmp_path):
        """Loading old state without reward_metrics works (backward compat)."""
        import json

        # Create old-style state file (without reward_metrics)
        old_state = {
            'q_values': {},
            'total_trades': 10,
            'winning_trades': 5,
            'total_pnl': 500.0,
            'exploration_rate': 0.1,
            'symbol_performance': {},
            'last_decay_timestamp': None,
        }

        filepath = str(tmp_path / 'old_state.json')
        with open(filepath, 'w') as f:
            json.dump(old_state, f)

        config = FSDConfig(enable_enhanced_rewards=True)
        engine = FSDEngine(config, Portfolio(cash=Decimal('10000')))

        # Should load without error
        assert engine.load_state(filepath)

        # Reward tracker should be fresh/default
        assert engine._reward_tracker.get_current_drawdown() == 0.0
