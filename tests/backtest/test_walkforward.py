"""Tests for walk-forward validation framework."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aistock.backtest.config import PeriodResult, WalkForwardConfig
from aistock.backtest.walkforward import (
    WalkForwardFold,
    WalkForwardResult,
    WalkForwardValidator,
)


class TestWalkForwardConfig:
    """Tests for WalkForwardConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = WalkForwardConfig()
        assert config.initial_train_days == 252
        assert config.test_window_days == 21
        assert config.mode == 'expanding'

    def test_invalid_train_days(self) -> None:
        """Test validation of train days."""
        config = WalkForwardConfig(initial_train_days=10)
        with pytest.raises(ValueError, match='initial_train_days must be at least 30'):
            config.validate()

    def test_invalid_test_days(self) -> None:
        """Test validation of test days."""
        config = WalkForwardConfig(test_window_days=2)
        with pytest.raises(ValueError, match='test_window_days must be at least 5'):
            config.validate()


class TestWalkForwardValidator:
    """Tests for WalkForwardValidator."""

    def test_generate_folds_expanding(self) -> None:
        """Test fold generation in expanding mode."""
        config = WalkForwardConfig(
            initial_train_days=100,
            test_window_days=20,
            step_days=20,
            mode='expanding',
            enable_final_holdout=False,
        )
        validator = WalkForwardValidator(config)

        folds = validator.generate_folds(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
        )

        assert len(folds) >= 2
        # First fold train period
        assert folds[0].train_start == date(2024, 1, 1)
        # Second fold should have longer training period (expanding)
        assert folds[1].train_days > folds[0].train_days

    def test_generate_folds_rolling(self) -> None:
        """Test fold generation in rolling mode."""
        config = WalkForwardConfig(
            initial_train_days=100,
            test_window_days=20,
            step_days=20,
            mode='rolling',
            rolling_window_days=100,
            enable_final_holdout=False,
        )
        validator = WalkForwardValidator(config)

        folds = validator.generate_folds(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
        )

        assert len(folds) >= 2
        # All folds should have same training period length (rolling)
        assert folds[0].train_days == folds[1].train_days

    def test_generate_folds_with_holdout(self) -> None:
        """Test fold generation reserves final holdout."""
        config = WalkForwardConfig(
            initial_train_days=60,
            test_window_days=20,
            step_days=20,
            mode='expanding',
            final_holdout_days=30,
            enable_final_holdout=True,
        )
        validator = WalkForwardValidator(config)

        folds = validator.generate_folds(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
        )

        # Last fold's test_end should be before holdout period
        last_fold = folds[-1]
        holdout_start = date(2024, 5, 31)  # 30 days before end
        assert last_fold.test_end < holdout_start

    def test_run_validation(self) -> None:
        """Test running validation with mock strategy."""
        config = WalkForwardConfig(
            initial_train_days=60,
            test_window_days=20,
            step_days=20,
            mode='expanding',
            enable_final_holdout=False,
        )
        validator = WalkForwardValidator(config)

        folds = validator.generate_folds(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 4, 30),
        )

        # Mock strategy runner
        call_count = [0]

        def mock_runner(start: date, end: date, is_training: bool) -> PeriodResult:
            call_count[0] += 1
            return PeriodResult(
                start_date=start,
                end_date=end,
                total_return=Decimal('1000'),
                total_return_pct=0.1 if is_training else 0.05,
                sharpe_ratio=1.5 if is_training else 1.0,
                total_trades=50,
                win_rate=0.55,
            )

        result = validator.run_validation(folds, mock_runner)

        # Should have run strategy for both train and test of each fold
        assert call_count[0] == len(folds) * 2
        assert result.completed_folds == len(folds)

    def test_overfitting_detection(self) -> None:
        """Test overfitting ratio calculation."""
        config = WalkForwardConfig()
        validator = WalkForwardValidator(config)

        # Create result with IS >> OOS (overfitting)
        result = WalkForwardResult(
            config=config,
            is_sharpes=[2.0],
            oos_sharpes=[0.5],
        )
        validator._calculate_aggregate_metrics(result)

        assert result.overfitting_ratio == 4.0
        assert result.is_overfitting(threshold=1.5) is True

    def test_no_overfitting(self) -> None:
        """Test overfitting detection when IS ~ OOS."""
        config = WalkForwardConfig()
        validator = WalkForwardValidator(config)

        result = WalkForwardResult(
            config=config,
            is_sharpes=[1.2],
            oos_sharpes=[1.1],
        )
        validator._calculate_aggregate_metrics(result)

        assert result.overfitting_ratio < 1.5
        assert result.is_overfitting(threshold=1.5) is False


class TestWalkForwardFold:
    """Tests for WalkForwardFold."""

    def test_fold_properties(self) -> None:
        """Test fold property calculations."""
        fold = WalkForwardFold(
            fold_number=1,
            train_start=date(2024, 1, 1),
            train_end=date(2024, 4, 1),
            test_start=date(2024, 4, 2),
            test_end=date(2024, 4, 30),
        )

        assert fold.train_days == 91  # ~3 months
        assert fold.test_days == 28
        assert fold.is_complete is False

    def test_fold_completion(self) -> None:
        """Test fold completion tracking."""
        fold = WalkForwardFold(
            fold_number=1,
            train_start=date(2024, 1, 1),
            train_end=date(2024, 4, 1),
            test_start=date(2024, 4, 2),
            test_end=date(2024, 4, 30),
        )

        assert fold.is_complete is False

        fold.train_result = PeriodResult(start_date=fold.train_start, end_date=fold.train_end)
        assert fold.is_complete is False

        fold.test_result = PeriodResult(start_date=fold.test_start, end_date=fold.test_end)
        assert fold.is_complete is True
