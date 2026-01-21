"""
Walk-forward validation framework.

Walk-forward validation helps detect overfitting by:
1. Training on historical data (in-sample)
2. Testing on subsequent data (out-of-sample)
3. Moving the window forward and repeating
4. Comparing in-sample vs out-of-sample performance

This provides a more realistic estimate of strategy performance
than simple train/test splits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .config import PeriodResult, WalkForwardConfig

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardFold:
    """
    Single fold in walk-forward validation.

    Each fold consists of:
    - Training period: Used to train/optimize the strategy
    - Test period: Used to evaluate out-of-sample performance
    """

    fold_number: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    # Results populated after running the fold
    train_result: PeriodResult | None = None
    test_result: PeriodResult | None = None
    optimized_params: dict[str, Any] | None = None
    status: str = 'pending'
    error_message: str | None = None
    error_timestamp: datetime | None = None

    @property
    def train_days(self) -> int:
        """Number of days in training period."""
        return (self.train_end - self.train_start).days

    @property
    def test_days(self) -> int:
        """Number of days in test period."""
        return (self.test_end - self.test_start).days

    @property
    def is_complete(self) -> bool:
        """Whether this fold has been executed."""
        return self.train_result is not None and self.test_result is not None


@dataclass
class WalkForwardResult:
    """Result of a complete walk-forward validation."""

    config: WalkForwardConfig
    folds: list[WalkForwardFold] = field(default_factory=list)
    final_holdout_result: PeriodResult | None = None

    # Aggregate metrics
    in_sample_sharpe: float = 0.0
    out_of_sample_sharpe: float = 0.0
    overfitting_ratio: float = 0.0  # IS Sharpe / OOS Sharpe

    # Per-fold metrics
    is_sharpes: list[float] = field(default_factory=list)
    oos_sharpes: list[float] = field(default_factory=list)
    is_returns: list[float] = field(default_factory=list)
    oos_returns: list[float] = field(default_factory=list)

    # Consistency metrics
    oos_positive_folds: int = 0  # Folds with positive OOS return
    oos_profitable_rate: float = 0.0  # % of folds profitable OOS

    @property
    def total_folds(self) -> int:
        """Total number of folds."""
        return len(self.folds)

    @property
    def completed_folds(self) -> int:
        """Number of completed folds."""
        return sum(1 for f in self.folds if f.is_complete)

    def is_overfitting(self, threshold: float = 1.5) -> bool:
        """
        Check if strategy appears to be overfitting.

        A high overfitting ratio (IS performance >> OOS performance)
        suggests the strategy is curve-fitted to historical data.

        Args:
            threshold: Overfitting ratio threshold (default 1.5).

        Returns:
            True if overfitting is detected.
        """
        return self.overfitting_ratio > threshold


class WalkForwardValidator:
    """
    Walk-forward validation framework.

    Implements both expanding and rolling window validation modes:

    Expanding Mode:
    ```
    |--Train 1 (252d)--|Test 1 (21d)|
    |----Train 2 (273d)----|Test 2 (21d)|
    |------Train 3 (294d)------|Test 3 (21d)|
    ```

    Rolling Mode:
    ```
    |--Train 1 (504d)--|Test 1 (21d)|
       |--Train 2 (504d)--|Test 2 (21d)|
          |--Train 3 (504d)--|Test 3 (21d)|
    ```
    """

    def __init__(self, config: WalkForwardConfig) -> None:
        """
        Initialize the validator.

        Args:
            config: Walk-forward configuration.
        """
        self.config = config

    def generate_folds(
        self,
        start_date: date,
        end_date: date,
    ) -> list[WalkForwardFold]:
        """
        Generate walk-forward folds for a date range.

        Args:
            start_date: Start of available data.
            end_date: End of available data.

        Returns:
            List of WalkForwardFold objects.
        """
        folds: list[WalkForwardFold] = []

        # Reserve final holdout if enabled
        if self.config.enable_final_holdout:
            holdout_start = end_date - timedelta(days=self.config.final_holdout_days)
            available_end = holdout_start - timedelta(days=1)
        else:
            available_end = end_date

        # Calculate first fold
        train_start = start_date
        train_end = train_start + timedelta(days=self.config.initial_train_days)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=self.config.test_window_days)

        fold_number = 1

        while test_end <= available_end:
            fold = WalkForwardFold(
                fold_number=fold_number,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
            folds.append(fold)

            # Move to next fold
            fold_number += 1

            if self.config.mode == 'expanding':
                # Expanding: keep train_start, extend train_end
                train_end = train_end + timedelta(days=self.config.step_days)
            else:
                # Rolling: move both train_start and train_end
                train_start = train_start + timedelta(days=self.config.step_days)
                train_end = train_start + timedelta(days=self.config.rolling_window_days)

            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=self.config.test_window_days)

        if len(folds) < self.config.min_folds:
            logger.warning(
                f'Only {len(folds)} folds generated, minimum is {self.config.min_folds}. '
                'Consider increasing the date range or reducing window sizes.'
            )

        return folds

    def run_validation(
        self,
        folds: list[WalkForwardFold],
        strategy_runner: Callable[[date, date, bool], PeriodResult],
        final_holdout_dates: tuple[date, date] | None = None,
    ) -> WalkForwardResult:
        """
        Run walk-forward validation across all folds.

        Args:
            folds: List of folds to validate.
            strategy_runner: Callable that runs a backtest for a date range.
                            Arguments: (start_date, end_date, is_training)
                            Returns: PeriodResult
            final_holdout_dates: Optional (start, end) for final OOS test.

        Returns:
            WalkForwardResult with all metrics.
        """
        result = WalkForwardResult(config=self.config, folds=folds)

        logger.info(f'Running walk-forward validation with {len(folds)} folds')

        for fold in folds:
            logger.info(
                f'Fold {fold.fold_number}/{len(folds)}: '
                f'Train {fold.train_start} to {fold.train_end} ({fold.train_days}d), '
                f'Test {fold.test_start} to {fold.test_end} ({fold.test_days}d)'
            )

            # Run training period
            try:
                fold.train_result = strategy_runner(
                    fold.train_start,
                    fold.train_end,
                    True,  # is_training
                )
                fold.train_result.is_train = True

                result.is_sharpes.append(fold.train_result.sharpe_ratio)
                result.is_returns.append(fold.train_result.total_return_pct)

                logger.info(
                    f'  Train: Return={fold.train_result.total_return_pct:.2%}, '
                    f'Sharpe={fold.train_result.sharpe_ratio:.2f}, '
                    f'Trades={fold.train_result.total_trades}'
                )

            except Exception as e:
                fold.status = 'failed'
                fold.error_message = str(e)
                fold.error_timestamp = datetime.now(timezone.utc)
                logger.error('  Train period failed for fold %s: %s', fold.fold_number, e, exc_info=True)
                continue

            # Run test period
            try:
                fold.test_result = strategy_runner(
                    fold.test_start,
                    fold.test_end,
                    False,  # is_training (OOS)
                )
                fold.test_result.is_test = True

                result.oos_sharpes.append(fold.test_result.sharpe_ratio)
                result.oos_returns.append(fold.test_result.total_return_pct)

                if fold.test_result.total_return_pct > 0:
                    result.oos_positive_folds += 1

                logger.info(
                    f'  Test: Return={fold.test_result.total_return_pct:.2%}, '
                    f'Sharpe={fold.test_result.sharpe_ratio:.2f}, '
                    f'Trades={fold.test_result.total_trades}'
                )

            except Exception as e:
                fold.status = 'failed'
                fold.error_message = str(e)
                fold.error_timestamp = datetime.now(timezone.utc)
                logger.error('  Test period failed for fold %s: %s', fold.fold_number, e, exc_info=True)
            else:
                fold.status = 'completed'

        # Run final holdout if provided
        if final_holdout_dates:
            holdout_start, holdout_end = final_holdout_dates
            logger.info(f'Running final holdout: {holdout_start} to {holdout_end}')

            try:
                result.final_holdout_result = strategy_runner(
                    holdout_start,
                    holdout_end,
                    False,  # OOS
                )
                logger.info(
                    f'Final holdout: Return={result.final_holdout_result.total_return_pct:.2%}, '
                    f'Sharpe={result.final_holdout_result.sharpe_ratio:.2f}'
                )
            except Exception as e:
                logger.error(f'Final holdout failed: {e}')

        # Calculate aggregate metrics
        self._calculate_aggregate_metrics(result)

        return result

    def _calculate_aggregate_metrics(self, result: WalkForwardResult) -> None:
        """Calculate aggregate metrics from fold results."""
        if result.is_sharpes:
            result.in_sample_sharpe = sum(result.is_sharpes) / len(result.is_sharpes)

        if result.oos_sharpes:
            result.out_of_sample_sharpe = sum(result.oos_sharpes) / len(result.oos_sharpes)

        # Overfitting ratio
        if result.out_of_sample_sharpe != 0:
            result.overfitting_ratio = result.in_sample_sharpe / result.out_of_sample_sharpe
        elif result.in_sample_sharpe > 0:
            result.overfitting_ratio = float('inf')  # OOS = 0 but IS > 0 = extreme overfitting
        else:
            result.overfitting_ratio = 1.0  # Both near zero

        # OOS profitable rate
        if result.oos_returns:
            result.oos_profitable_rate = result.oos_positive_folds / len(result.oos_returns)

    def calculate_overfitting_ratio(self, result: WalkForwardResult) -> float:
        """
        Calculate the overfitting ratio.

        Overfitting Ratio = In-Sample Sharpe / Out-of-Sample Sharpe

        Interpretation:
        - Ratio ~1.0: Strategy performs similarly IS and OOS (good)
        - Ratio >1.5: Strategy degrades OOS (possible overfitting)
        - Ratio >2.0: Strategy significantly worse OOS (likely overfitting)

        Args:
            result: Walk-forward result.

        Returns:
            Overfitting ratio.
        """
        return result.overfitting_ratio

    def generate_summary(self, result: WalkForwardResult) -> dict[str, Any]:
        """
        Generate a summary dictionary of walk-forward results.

        Args:
            result: Walk-forward result.

        Returns:
            Dictionary with summary metrics.
        """
        summary: dict[str, Any] = {
            'validation_mode': self.config.mode,
            'total_folds': result.total_folds,
            'completed_folds': result.completed_folds,
            'in_sample_sharpe': round(result.in_sample_sharpe, 3),
            'out_of_sample_sharpe': round(result.out_of_sample_sharpe, 3),
            'overfitting_ratio': round(result.overfitting_ratio, 3),
            'oos_profitable_rate': round(result.oos_profitable_rate, 3),
            'is_likely_overfitting': result.is_overfitting(),
        }

        # Add fold-by-fold summary
        fold_summaries: list[dict[str, float | int]] = []
        for fold in result.folds:
            fold_summary: dict[str, float | int] = {
                'fold': fold.fold_number,
                'train_days': fold.train_days,
                'test_days': fold.test_days,
            }
            if fold.train_result:
                fold_summary['train_sharpe'] = round(fold.train_result.sharpe_ratio, 3)
                fold_summary['train_return'] = round(fold.train_result.total_return_pct, 4)
            if fold.test_result:
                fold_summary['test_sharpe'] = round(fold.test_result.sharpe_ratio, 3)
                fold_summary['test_return'] = round(fold.test_result.total_return_pct, 4)
            fold_summaries.append(fold_summary)

        summary['folds'] = fold_summaries

        # Final holdout
        if result.final_holdout_result:
            summary['final_holdout'] = {
                'sharpe': round(result.final_holdout_result.sharpe_ratio, 3),
                'return': round(result.final_holdout_result.total_return_pct, 4),
                'trades': result.final_holdout_result.total_trades,
            }

        return summary

    def get_recommended_action(self, result: WalkForwardResult) -> str:
        """
        Get recommended action based on walk-forward results.

        Args:
            result: Walk-forward result.

        Returns:
            String with recommendation.
        """
        if result.overfitting_ratio > 2.0:
            return (
                'HIGH OVERFITTING DETECTED. Strategy performs much worse out-of-sample. '
                'Consider: (1) Reducing strategy complexity, (2) Using more robust features, '
                '(3) Increasing regularization, (4) Using longer training periods.'
            )

        if result.overfitting_ratio > 1.5:
            return (
                'MODERATE OVERFITTING DETECTED. Strategy shows some performance degradation OOS. '
                'Review feature selection and consider simplifying the model.'
            )

        if result.oos_profitable_rate < 0.5:
            return (
                'LOW OOS PROFITABILITY. Less than 50% of folds were profitable out-of-sample. '
                'Strategy may not be robust across different market conditions.'
            )

        if result.out_of_sample_sharpe < 0.5:
            return (
                'LOW OOS SHARPE RATIO. Strategy risk-adjusted returns are weak. '
                'Consider improving risk management or signal quality.'
            )

        if result.overfitting_ratio < 1.0 and result.out_of_sample_sharpe > result.in_sample_sharpe:
            return (
                'EXCELLENT. Strategy performs BETTER out-of-sample than in-sample. '
                'This is unusual and suggests robust performance. Verify data integrity.'
            )

        return (
            'ACCEPTABLE. Strategy shows reasonable consistency between IS and OOS performance. '
            'Proceed with paper trading to validate in live market conditions.'
        )
