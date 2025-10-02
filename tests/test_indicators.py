# tests/test_indicators.py
"""Tests for technical indicators."""

import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.oscillators import calculate_rsi, calculate_macd
from indicators.moving_averages import calculate_sma, calculate_ema
from indicators.volatility import calculate_atr
from indicators.trend import calculate_adx


@pytest.fixture
def sample_ohlc_data():
    """Create sample OHLC data for testing."""
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(100) * 2)
    high = close + np.random.rand(100) * 2
    low = close - np.random.rand(100) * 2
    open_ = close + np.random.randn(100)

    return pd.DataFrame({
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=dates)


def test_rsi_calculation(sample_ohlc_data):
    """Test RSI calculation."""
    rsi = calculate_rsi(sample_ohlc_data, period=14)

    assert isinstance(rsi, pd.Series)
    assert len(rsi) == len(sample_ohlc_data)
    # RSI should be between 0 and 100
    assert (rsi.dropna() >= 0).all() and (rsi.dropna() <= 100).all()
    # First 14 values should be NaN (warmup period)
    assert rsi.iloc[:13].isna().all()


def test_macd_calculation(sample_ohlc_data):
    """Test MACD calculation."""
    macd, signal, hist = calculate_macd(sample_ohlc_data, fast=12, slow=26, signal_period=9)

    assert isinstance(macd, pd.Series)
    assert isinstance(signal, pd.Series)
    assert isinstance(hist, pd.Series)
    assert len(macd) == len(sample_ohlc_data)
    # Histogram should be macd - signal
    np.testing.assert_array_almost_equal(
        hist.dropna().values,
        (macd - signal).dropna().values,
        decimal=5
    )


def test_sma_calculation(sample_ohlc_data):
    """Test SMA calculation."""
    sma = calculate_sma(sample_ohlc_data, period=20)

    assert isinstance(sma, pd.Series)
    assert len(sma) == len(sample_ohlc_data)
    # First 19 values should be NaN
    assert sma.iloc[:19].isna().all()
    # SMA values should be reasonable (within data range)
    assert sma.dropna().min() >= sample_ohlc_data['close'].min()
    assert sma.dropna().max() <= sample_ohlc_data['close'].max()


def test_ema_calculation(sample_ohlc_data):
    """Test EMA calculation."""
    ema = calculate_ema(sample_ohlc_data, period=20)

    assert isinstance(ema, pd.Series)
    assert len(ema) == len(sample_ohlc_data)
    # EMA should react faster than SMA
    sma = calculate_sma(sample_ohlc_data, period=20)
    # EMA variance should be higher than SMA (more responsive)
    assert ema.dropna().var() >= sma.dropna().var() * 0.8  # Allow some tolerance


def test_atr_calculation(sample_ohlc_data):
    """Test ATR calculation."""
    atr = calculate_atr(sample_ohlc_data, period=14)

    assert isinstance(atr, pd.Series)
    assert len(atr) == len(sample_ohlc_data)
    # ATR should be positive
    assert (atr.dropna() > 0).all()
    # ATR should be less than typical price range
    typical_range = (sample_ohlc_data['high'] - sample_ohlc_data['low']).max()
    assert atr.dropna().max() <= typical_range


def test_adx_calculation(sample_ohlc_data):
    """Test ADX calculation."""
    adx = calculate_adx(sample_ohlc_data, period=14)

    assert isinstance(adx, pd.Series)
    assert len(adx) == len(sample_ohlc_data)
    # ADX should be between 0 and 100
    assert (adx.dropna() >= 0).all() and (adx.dropna() <= 100).all()


def test_indicator_with_insufficient_data():
    """Test indicators handle insufficient data gracefully."""
    small_data = pd.DataFrame({
        'close': [100, 101, 102],
        'high': [101, 102, 103],
        'low': [99, 100, 101],
        'open': [100, 101, 102],
        'volume': [1000, 1000, 1000]
    })

    # RSI with period 14 on only 3 data points
    rsi = calculate_rsi(small_data, period=14)
    assert rsi.isna().all()  # All should be NaN


def test_indicator_with_nan_values():
    """Test indicators handle NaN values in input data."""
    data_with_nan = pd.DataFrame({
        'close': [100, 101, np.nan, 103, 104],
        'high': [101, 102, np.nan, 104, 105],
        'low': [99, 100, np.nan, 102, 103],
        'open': [100, 101, np.nan, 103, 104],
        'volume': [1000, 1000, np.nan, 1000, 1000]
    })

    # Should handle NaN gracefully
    rsi = calculate_rsi(data_with_nan, period=3)
    assert isinstance(rsi, pd.Series)
