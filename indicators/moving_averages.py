import pandas as pd

def calculate_sma(data, period):
    sma = data['close'].rolling(window=period).mean()
    return sma

def calculate_ema(data, period):
    ema = data['close'].ewm(span=period, adjust=False).mean()
    return ema
