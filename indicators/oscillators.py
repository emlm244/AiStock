# indicators/oscillators.py
import numpy as np
import pandas as pd


def calculate_rsi(data, period=14):
    """
    Calculates the Relative Strength Index (RSI).

    Uses Wilder's smoothing (equivalent to EMA with alpha = 1/period).
    """
    if 'close' not in data.columns:
        raise ValueError("DataFrame must contain 'close' column.")
    if len(data) < period + 1:  # Need at least period+1 for diff and initial smoothing
        return pd.Series(index=data.index, dtype=float)

    delta = data['close'].diff()

    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    # Use Wilder's smoothing (alpha = 1 / period) for average gain/loss
    # Adjust=False starts the recursive calculation immediately
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    # Calculate RS
    rs = avg_gain / avg_loss
    # Handle division by zero where avg_loss is 0
    rs = rs.replace([np.inf], np.nan).fillna(100)  # If avg_loss is 0, RSI is 100

    rsi = 100.0 - (100.0 / (1.0 + rs))

    # Handle cases where avg_loss was zero initially, causing NaNs in rs -> rsi
    rsi.fillna(100, inplace=True)  # If avg_gain is > 0 and avg_loss is 0

    return rsi


def calculate_macd(data, fast_period=12, slow_period=26, signal_period=9):
    """
    Calculates Moving Average Convergence Divergence (MACD).
    """
    if 'close' not in data.columns:
        raise ValueError("DataFrame must contain 'close' column.")
    if len(data) < slow_period:  # Need enough data for the slowest EMA
        nan_series = pd.Series(index=data.index, dtype=float)
        return nan_series, nan_series, nan_series

    # Calculate Fast and Slow EMAs
    ema_fast = data['close'].ewm(span=fast_period, adjust=False, min_periods=fast_period).mean()
    ema_slow = data['close'].ewm(span=slow_period, adjust=False, min_periods=slow_period).mean()

    # Calculate MACD Line
    macd_line = ema_fast - ema_slow

    # Calculate Signal Line (EMA of MACD Line)
    signal_line = macd_line.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()

    # Calculate MACD Histogram
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram
