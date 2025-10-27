# indicators/volatility.py
import numpy as np
import pandas as pd


def calculate_atr(data, period=14):
    """
    Calculates the Average True Range (ATR) using Wilder's smoothing.

    Args:
        data (pd.DataFrame): DataFrame with 'high', 'low', 'close' columns.
        period (int): The period for calculating ATR.

    Returns:
        pd.Series: A Series containing the ATR values. Returns NaNs if insufficient data.
    """
    if not all(col in data.columns for col in ['high', 'low', 'close']):
        raise ValueError("DataFrame must contain 'high', 'low', and 'close' columns for ATR calculation.")
    if len(data) < period + 1:  # Need period+1 for shift and initial smoothing
        return pd.Series(index=data.index, dtype=float)  # Return NaNs

    df = data.copy()

    # Calculate True Range components
    df['h_minus_l'] = df['high'] - df['low']
    df['h_minus_pc'] = np.abs(df['high'] - df['close'].shift(1))
    df['l_minus_pc'] = np.abs(df['low'] - df['close'].shift(1))

    # Calculate True Range (TR)
    df['tr'] = df[['h_minus_l', 'h_minus_pc', 'l_minus_pc']].max(axis=1)

    # Calculate ATR using Wilder's smoothing (equivalent to EMA with alpha=1/period)
    alpha = 1.0 / period
    atr = df['tr'].ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    return atr


def calculate_bollinger_bands(data, period=20, std_dev=2.0):
    """
    Calculates Bollinger Bands (Middle, Upper, Lower).

    Args:
        data (pd.DataFrame): DataFrame with 'close' column.
        period (int): The period for the moving average.
        std_dev (float): The number of standard deviations for the bands.

    Returns:
        tuple: A tuple containing three pandas Series (middle_band, upper_band, lower_band).
               Returns NaNs if insufficient data.
    """
    if 'close' not in data.columns:
        raise ValueError("DataFrame must contain 'close' column.")
    if len(data) < period:
        nan_series = pd.Series(index=data.index, dtype=float)
        return nan_series, nan_series, nan_series

    # Calculate Middle Band (SMA)
    middle_band = data['close'].rolling(window=period, min_periods=period).mean()

    # Calculate Standard Deviation over the same period
    rolling_std = data['close'].rolling(window=period, min_periods=period).std()

    # Calculate Upper and Lower Bands
    upper_band = middle_band + (rolling_std * std_dev)
    lower_band = middle_band - (rolling_std * std_dev)

    return middle_band, upper_band, lower_band


def calculate_bollinger_bands_width(data, period=20, std_dev=2.0):
    """
    Calculates the width of the Bollinger Bands ((Upper - Lower) / Middle).

    Args:
        data (pd.DataFrame): DataFrame with 'close' column.
        period (int): The period for the moving average.
        std_dev (float): The number of standard deviations for the bands.

    Returns:
        pd.Series: A Series containing the Bollinger Bands width. Returns NaNs if insufficient data.
    """
    middle_band, upper_band, lower_band = calculate_bollinger_bands(data, period, std_dev)

    # Avoid division by zero or NaN issues if middle_band is 0 or NaN
    # Replace NaN or zero in middle_band temporarily for division
    safe_middle_band = middle_band.replace(0, np.nan)  # Avoid division by zero
    bb_width = (upper_band - lower_band) / safe_middle_band

    # Replace any infinities resulting from division by near-zero std dev with NaN
    bb_width = bb_width.replace([np.inf, -np.inf], np.nan)

    return bb_width
