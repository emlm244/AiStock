# indicators/moving_averages.py
import pandas as pd


def calculate_sma(data, period):
    """Calculates Simple Moving Average (SMA)."""
    if 'close' not in data.columns:
        raise ValueError("DataFrame must contain 'close' column.")
    if len(data) < period:
        # Return NaNs if not enough data
        return pd.Series(index=data.index, dtype=float)
    sma = data['close'].rolling(window=period, min_periods=period).mean()
    return sma


def calculate_ema(data, period):
    """Calculates Exponential Moving Average (EMA)."""
    if 'close' not in data.columns:
        raise ValueError("DataFrame must contain 'close' column.")
    if len(data) < period:
        # Return NaNs if not enough data
        return pd.Series(index=data.index, dtype=float)
    # adjust=False uses the recursive formula from the start
    ema = data['close'].ewm(span=period, adjust=False, min_periods=period).mean()
    return ema
