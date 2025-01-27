# File: strategies/ml_strategy.py

import sys
sys.path.append('..')
import os
import pandas as pd
import numpy as np

from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
from utils.logger import setup_logger
from config.settings import Settings

# Import oscillator functions
from indicators.oscillators import calculate_rsi, calculate_macd

class MLStrategy:
    def __init__(self):
        self.settings = Settings()
        self.logger = setup_logger(__name__, 'logs/strategies.log', level=self.settings.LOG_LEVEL)

        self.model = SGDClassifier(max_iter=1000, tol=1e-3, random_state=42)
        self.scaler = StandardScaler()
        self.is_model_trained = False

        self.features = [
            'volatility',
            'momentum',
            'sma_ratio',
            'rsi',
            'macd',
            'macd_signal',
            'macd_hist'
        ]
        self.min_data_points_required = 26  # Enough bars for MACD's slow_period

        # Default windows
        self.volatility_window = 5
        self.momentum_window = 5
        self.sma_window = 10
        self.rsi_period = self.settings.RSI_PERIOD
        self.macd_fast = self.settings.MACD_SETTINGS['fast_period']
        self.macd_slow = self.settings.MACD_SETTINGS['slow_period']
        self.macd_signal = self.settings.MACD_SETTINGS['signal_period']

    def generate_signal(self, data):
        try:
            # Check if crypto to handle any specialized logic
            if self.settings.TRADING_MODE == 'crypto':
                pass

            if len(data) < self.min_data_points():
                self.logger.warning("Not enough data to generate features for ML model.")
                return 0

            df = data.copy()
            df.sort_values(by='timestamp', inplace=True)

            # Basic feature engineering
            df['return'] = df['close'].pct_change()
            df['volatility'] = df['return'].rolling(window=self.volatility_window).std()
            df['momentum'] = df['close'] / df['close'].shift(self.momentum_window) - 1
            df['sma'] = df['close'].rolling(window=self.sma_window).mean()
            df['sma_ratio'] = df['close'] / df['sma']

            # RSI
            df['rsi'] = calculate_rsi(df, period=self.rsi_period)

            # MACD
            macd_line, macd_signal_line, macd_hist = calculate_macd(
                df,
                fast_period=self.macd_fast,
                slow_period=self.macd_slow,
                signal_period=self.macd_signal
            )
            df['macd'] = macd_line
            df['macd_signal'] = macd_signal_line
            df['macd_hist'] = macd_hist

            df.dropna(inplace=True)

            # Binary target
            df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, -1)
            df.dropna(inplace=True)

            X = df[self.features]
            y = df['target']

            if not self.is_model_trained:
                self.scaler.fit(X)
                X_scaled = self.scaler.transform(X)
                self.model.partial_fit(X_scaled, y, classes=np.array([-1, 1]))
                self.is_model_trained = True
                self.logger.info("ML model trained with initial data.")
                return 0
            else:
                # Incremental training
                X_scaled = self.scaler.transform(X)
                self.model.partial_fit(X_scaled, y)

                # Predict with latest bar
                latest_features = X_scaled[-1].reshape(1, -1)
                prediction = self.model.predict(latest_features)[0]

                if prediction == 1:
                    self.logger.info("ML model predicts upward movement - Buy signal.")
                    return 1
                else:
                    self.logger.info("ML model predicts downward movement - Sell signal.")
                    return -1

        except Exception as e:
            self.logger.error(f"Error in MLStrategy.generate_signal: {e}", exc_info=True)
            return 0

    def min_data_points(self):
        return max(self.rsi_period, self.macd_slow, self.min_data_points_required)
