from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..config import DataSource
from ..data import Bar, load_csv_directory
from .features import extract_features


@dataclass
class Sample:
    features: dict[str, float]
    label: int  # 1 for up, 0 for down/flat


def build_dataset_from_directory(
    data_dir: str,
    symbols: Sequence[str],
    lookback: int = 30,
    horizon: int = 1,
) -> list[Sample]:
    source = DataSource(path=data_dir, symbols=list(symbols))
    data = load_csv_directory(source)
    samples: list[Sample] = []
    for _symbol, bars in data.items():
        samples.extend(_build_samples_for_symbol(bars, lookback, horizon))
    return samples


def _build_samples_for_symbol(bars: list[Bar], lookback: int, horizon: int) -> list[Sample]:
    """
    Build training samples with P1 leakage audit.

    For each sample:
    - Features use bars [idx-lookback:idx]
    - Label uses bar at idx+horizon-1
    - Leakage check: feature timestamp < label timestamp
    """
    samples: list[Sample] = []
    for idx in range(lookback, len(bars) - horizon):
        window = bars[idx - lookback : idx]
        prediction_time = bars[idx].timestamp  # Time we're predicting FROM

        # P1 Enhancement: Pass prediction_time for leakage audit
        feature_map = extract_features(window, lookback=lookback, as_of_timestamp=prediction_time)
        if not feature_map:
            continue

        # Label comes from FUTURE bar (idx + horizon - 1)
        label_bar = bars[idx + horizon - 1]
        future_close = float(label_bar.close)
        current_close = float(window[-1].close)

        # P1 Enhancement: Explicit leakage assertion
        assert label_bar.timestamp > window[-1].timestamp, (
            f"Leakage: label bar ({label_bar.timestamp}) must be after "
            f"feature window end ({window[-1].timestamp})"
        )

        label = 1 if future_close > current_close else 0
        samples.append(Sample(features=feature_map, label=label))
    return samples


def train_test_split(samples: Sequence[Sample], test_ratio: float = 0.2) -> tuple[list[Sample], list[Sample]]:
    cutoff = max(1, int(len(samples) * (1 - test_ratio)))
    return list(samples[:cutoff]), list(samples[cutoff:])
