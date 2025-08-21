# indicators/trend.py
import pandas as pd
import numpy as np
from .volatility import calculate_atr # Import ATR for ADX calculation

def calculate_adx(data, period=14):
    """
    Calculates the Average Directional Index (ADX), +DI, and -DI.
    Uses Wilder's smoothing for DM and TR.

    Args:
        data (pd.DataFrame): DataFrame with 'high', 'low', 'close' columns.
        period (int): The period for ADX calculation.

    Returns:
        tuple: A tuple containing three pandas Series (adx, plus_di, minus_di).
               Returns (None, None, None) if input data is insufficient.
    """
    if not all(col in data.columns for col in ['high', 'low', 'close']):
        raise ValueError("DataFrame must contain 'high', 'low', and 'close' columns.")
    # ADX calculation needs more history than just the period due to smoothing steps
    required_periods = period * 2 # Heuristic: Need roughly 2x period for reasonable smoothing start
    if len(data) < required_periods:
        # print(f"Debug ADX: Not enough data {len(data)}/{required_periods}")
        nan_series = pd.Series(index=data.index, dtype=float)
        return nan_series, nan_series, nan_series # Return NaNs

    df = data.copy()

    # Calculate True Range (TR)
    df['high_minus_low'] = df['high'] - df['low']
    df['high_minus_prev_close'] = abs(df['high'] - df['close'].shift(1))
    df['low_minus_prev_close'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['high_minus_low', 'high_minus_prev_close', 'low_minus_prev_close']].max(axis=1)

    # Calculate Directional Movement (+DM, -DM)
    df['high_diff'] = df['high'].diff()
    df['low_diff'] = df['low'].diff() # Note: diff calculates X[t] - X[t-1]

    df['plus_dm'] = np.where((df['high_diff'] > -df['low_diff']) & (df['high_diff'] > 0), df['high_diff'], 0.0)
    df['minus_dm'] = np.where((-df['low_diff'] > df['high_diff']) & (-df['low_diff'] > 0), -df['low_diff'], 0.0)

    # Calculate Smoothed +DM, -DM, and TR using Wilder's smoothing (alpha = 1/period)
    alpha = 1.0 / period
    df['smoothed_plus_dm'] = df['plus_dm'].ewm(alpha=alpha, adjust=False).mean()
    df['smoothed_minus_dm'] = df['minus_dm'].ewm(alpha=alpha, adjust=False).mean()
    df['smoothed_tr'] = df['tr'].ewm(alpha=alpha, adjust=False).mean()

    # Calculate +DI and -DI, handle division by zero
    df['plus_di'] = np.where(df['smoothed_tr'] != 0, (df['smoothed_plus_dm'] / df['smoothed_tr']) * 100, 0)
    df['minus_di'] = np.where(df['smoothed_tr'] != 0, (df['smoothed_minus_dm'] / df['smoothed_tr']) * 100, 0)

    # Calculate DX
    di_sum = df['plus_di'] + df['minus_di']
    df['dx'] = np.where(di_sum != 0, (np.abs(df['plus_di'] - df['minus_di']) / di_sum) * 100, 0)

    # Calculate ADX (Smoothed DX)
    df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()

    # Return only the final series
    return df['adx'], df['plus_di'], df['minus_di']