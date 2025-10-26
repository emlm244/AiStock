from __future__ import annotations

from collections.abc import Sequence

from ..data import Bar


def _sma(values: Sequence[float], window: int) -> float | None:
    if len(values) < window or window <= 0:
        return None
    return sum(values[-window:]) / window


def _rsi(values: Sequence[float], window: int) -> float | None:
    if len(values) < window + 1:
        return None
    gains = []
    losses = []
    for prev, curr in zip(values[-window - 1 : -1], values[-window:]):
        delta = curr - prev
        if delta >= 0:
            gains.append(delta)
        else:
            losses.append(abs(delta))
    avg_gain = sum(gains) / window if gains else 0.0
    avg_loss = sum(losses) / window if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _std_dev(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    subset = values[-window:]
    mean = sum(subset) / window
    variance = sum((val - mean) ** 2 for val in subset) / window
    return variance ** 0.5


def extract_features(bars: list[Bar], lookback: int = 30, as_of_timestamp=None) -> dict[str, float] | None:
    """
    Compute a feature vector from the supplied bars.

    P1 Enhancement: Leakage audit with timestamp validation.

    Args:
        bars: Historical bars (must be chronologically ordered)
        lookback: Number of bars to use for indicators
        as_of_timestamp: Optional prediction timestamp for leakage audit.
                        If provided, all bars must be strictly before this time.

    Returns:
        Feature dictionary or None if insufficient history.

    Raises:
        ValueError: If leakage detected (bars after as_of_timestamp)
    """
    if len(bars) < max(lookback, 10):
        return None

    # P1 Enhancement: Leakage audit - ensure no future data
    if as_of_timestamp is not None:
        for i, bar in enumerate(bars):
            if bar.timestamp >= as_of_timestamp:
                raise ValueError(
                    f"LEAKAGE DETECTED: Bar {i} at {bar.timestamp.isoformat()} "
                    f"is >= prediction time {as_of_timestamp.isoformat()}. "
                    f"Features must use only historical data."
                )

    closes = [float(bar.close) for bar in bars]
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    current_close = closes[-1]
    prev_close = closes[-2]
    feature_map: dict[str, float] = {}

    feature_map["return_1"] = (current_close - prev_close) / prev_close
    feature_map["return_5"] = (current_close - closes[-6]) / closes[-6] if len(closes) >= 6 else 0.0

    sma_short = _sma(closes, min(lookback // 2, len(closes)))
    sma_long = _sma(closes, lookback)
    if sma_short is not None and sma_long is not None:
        feature_map["sma_ratio"] = sma_short / sma_long if sma_long != 0 else 0.0
        feature_map["sma_diff"] = sma_short - sma_long
    else:
        feature_map["sma_ratio"] = 1.0
        feature_map["sma_diff"] = 0.0

    rsi = _rsi(closes, min(lookback // 2, 14))
    feature_map["rsi"] = rsi if rsi is not None else 50.0

    volatility = _std_dev(returns, min(len(returns), lookback))
    feature_map["volatility"] = volatility if volatility is not None else 0.0

    true_range = [high - low for high, low in zip(highs[-lookback:], lows[-lookback:])]
    feature_map["atr"] = sum(true_range) / len(true_range) if true_range else 0.0

    feature_map["price"] = current_close

    return feature_map
