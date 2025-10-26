from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from ..config import DataQualityConfig, DataSource
from ..data import load_csv_directory
from .dataset import Sample, _build_samples_for_symbol, train_test_split
from .model import LogisticRegressionModel, save_model, train_logistic_regression


@dataclass
class TrainingResult:
    model_path: str
    train_accuracy: float
    test_accuracy: float
    samples: int


@dataclass
class WalkForwardFold:
    """Single fold in walk-forward validation."""
    train_end_idx: int
    test_end_idx: int
    train_accuracy: float
    test_accuracy: float
    train_size: int
    test_size: int


@dataclass
class WalkForwardResult:
    """Results of walk-forward validation.

    P1 Enhancement: Comprehensive out-of-sample validation with embargo periods.
    """
    folds: list[WalkForwardFold]
    mean_test_accuracy: float
    std_test_accuracy: float
    min_test_accuracy: float
    max_test_accuracy: float
    total_folds: int

    def is_stable(self, min_accuracy: float = 0.52) -> bool:
        """Check if model is stable across folds."""
        return self.min_test_accuracy >= min_accuracy


def train_model(
    data_dir: str,
    symbols: Sequence[str],
    lookback: int = 30,
    horizon: int = 1,
    learning_rate: float = 0.01,
    epochs: int = 200,
    model_path: str = "models/ml_model.json",
    quality: DataQualityConfig | None = None,
    bar_interval: timedelta | None = None,
) -> TrainingResult:
    from datetime import timedelta as _td
    if not symbols:
        raise ValueError("At least one symbol must be supplied for training.")

    source = DataSource(
        path=data_dir,
        symbols=list(symbols),
        warmup_bars=lookback,
        bar_interval=bar_interval or _td(minutes=1),
    )
    data = load_csv_directory(source, quality)
    samples: list[Sample] = []
    for _symbol, bars in data.items():
        samples.extend(_build_samples_for_symbol(bars, lookback, horizon))

    if len(samples) < 10:
        raise ValueError("Insufficient samples generated. Increase data window or lookback.")

    train_samples, test_samples = train_test_split(samples, test_ratio=0.2)
    train_pairs = [(sample.features, sample.label) for sample in train_samples]
    test_pairs = [(sample.features, sample.label) for sample in test_samples]

    model = train_logistic_regression(train_pairs, learning_rate=learning_rate, epochs=epochs)

    train_accuracy = _accuracy(model, train_pairs)
    test_accuracy = _accuracy(model, test_pairs)

    output_path = Path(model_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_model(model, model_path)

    return TrainingResult(
        model_path=str(output_path),
        train_accuracy=train_accuracy,
        test_accuracy=test_accuracy,
        samples=len(samples),
    )


def _accuracy(model: LogisticRegressionModel, samples: Sequence[tuple[dict, int]]) -> float:
    if not samples:
        return 0.0
    correct = 0
    for features, label in samples:
        prediction = model.predict(features)
        if prediction == label:
            correct += 1
    return correct / len(samples)


def walk_forward_validation(
    data_dir: str,
    symbols: Sequence[str],
    lookback: int = 30,
    horizon: int = 1,
    train_window: int = 500,
    test_window: int = 100,
    embargo_bars: int = 10,
    learning_rate: float = 0.01,
    epochs: int = 200,
) -> WalkForwardResult:
    """
    Walk-forward validation with expanding window.

    P1 Enhancement: Production-grade ML validation.

    Args:
        data_dir: Path to historical data
        symbols: List of symbols to train on
        lookback: Feature window size
        horizon: Prediction horizon (bars ahead)
        train_window: Minimum training samples before first test
        test_window: Number of samples per test fold
        embargo_bars: Gap between train/test to prevent leakage (default 10)
        learning_rate: Model learning rate
        epochs: Training epochs per fold

    Returns:
        WalkForwardResult with per-fold metrics and summary statistics

    Example:
        >>> result = walk_forward_validation(
        ...     "data/2024",
        ...     ["AAPL", "MSFT"],
        ...     train_window=500,
        ...     test_window=100,
        ...     embargo_bars=10,
        ... )
        >>> print(f"Mean test accuracy: {result.mean_test_accuracy:.2%}")
        >>> assert result.is_stable(min_accuracy=0.52)
    """
    # Load all data
    source = DataSource(path=data_dir, symbols=list(symbols), warmup_bars=lookback)
    data = load_csv_directory(source)
    all_samples: list[Sample] = []
    for _symbol, bars in data.items():
        all_samples.extend(_build_samples_for_symbol(bars, lookback, horizon))

    if len(all_samples) < train_window + test_window:
        raise ValueError(
            f"Insufficient samples ({len(all_samples)}) for walk-forward. "
            f"Need at least {train_window + test_window}."
        )

    folds: list[WalkForwardFold] = []
    current_idx = train_window

    while current_idx + test_window + embargo_bars <= len(all_samples):
        # Expanding window: train on [0:current_idx], test on [current_idx+embargo:current_idx+embargo+test_window]
        train_set = all_samples[:current_idx]
        test_start = current_idx + embargo_bars
        test_end = test_start + test_window
        test_set = all_samples[test_start:test_end]

        # Train model on this fold
        train_pairs = [(s.features, s.label) for s in train_set]
        test_pairs = [(s.features, s.label) for s in test_set]

        model = train_logistic_regression(train_pairs, learning_rate=learning_rate, epochs=epochs)

        train_acc = _accuracy(model, train_pairs)
        test_acc = _accuracy(model, test_pairs)

        folds.append(
            WalkForwardFold(
                train_end_idx=current_idx,
                test_end_idx=test_end,
                train_accuracy=train_acc,
                test_accuracy=test_acc,
                train_size=len(train_set),
                test_size=len(test_set),
            )
        )

        # Move forward by test_window
        current_idx += test_window

    # Compute summary statistics
    test_accuracies = [fold.test_accuracy for fold in folds]
    mean_test = sum(test_accuracies) / len(test_accuracies) if test_accuracies else 0.0
    variance = sum((acc - mean_test) ** 2 for acc in test_accuracies) / len(test_accuracies) if test_accuracies else 0.0
    std_test = variance ** 0.5

    return WalkForwardResult(
        folds=folds,
        mean_test_accuracy=mean_test,
        std_test_accuracy=std_test,
        min_test_accuracy=min(test_accuracies) if test_accuracies else 0.0,
        max_test_accuracy=max(test_accuracies) if test_accuracies else 0.0,
        total_folds=len(folds),
    )
