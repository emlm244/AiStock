import random
from config.settings import Settings
from utils.logger import setup_logger

class AdaptiveParameterOptimizer:
    def __init__(self, settings, logger=None):
        self.settings = settings
        self.logger = logger or setup_logger(__name__, 'logs/parameter_optimizer.log', level=self.settings.LOG_LEVEL)
        self.performance_history = []

        # Define acceptable ranges for parameters
        self.parameter_ranges = {
            'STOP_LOSS_PERCENT': (0.001, 0.02),  # 0.1% to 2%
            'TAKE_PROFIT_PERCENT': (0.005, 0.05),  # 0.5% to 5%
            'MAX_DAILY_LOSS': (0.01, 0.1),  # 1% to 10% of total capital
            'MOVING_AVERAGE_PERIODS.short_term': (3, 50),
            'MOVING_AVERAGE_PERIODS.long_term': (10, 200),
            'RSI_PERIOD': (5, 30),
            'MACD_SETTINGS.fast_period': (5, 20),
            'MACD_SETTINGS.slow_period': (20, 50),
            'MACD_SETTINGS.signal_period': (5, 20),
            'MOMENTUM_PRICE_CHANGE_PERIOD': (3, 20),
            'MOMENTUM_PRICE_CHANGE_THRESHOLD': (0.005, 0.05),
            'MOMENTUM_VOLUME_MULTIPLIER': (1.0, 3.0),
            'ML_VOLATILITY_WINDOW': (3, 20),
            'ML_MOMENTUM_WINDOW': (3, 20),
            'ML_SMA_WINDOW': (5, 30),
            # Add more parameters as needed
        }

    def update_parameters(self, trade_history):
        # Update performance history
        self.performance_history.extend(trade_history)

        # Simple logic to adjust parameters based on recent performance
        if len(self.performance_history) >= 10:
            recent_trades = self.performance_history[-10:]
            recent_pnl = sum(trade['pnl'] for trade in recent_trades)

            if recent_pnl < 0:
                self.logger.info("Recent performance is negative. Adjusting parameters.")
                self.adjust_parameters()
            else:
                self.logger.info("Recent performance is positive. No parameter adjustment needed.")

    def adjust_parameters(self):
        # Adjust parameters within defined ranges
        for param, (min_value, max_value) in self.parameter_ranges.items():
            current_value = self.get_nested_attr(self.settings, param)
            adjustment = random.uniform(-0.1, 0.1) * current_value  # Adjust by ±10%
            new_value = current_value + adjustment
            new_value = max(min_value, min(max_value, new_value))  # Clamp to range
            self.set_nested_attr(self.settings, param, new_value)
            self.logger.info(f"Parameter {param} adjusted to {new_value}")

    def get_nested_attr(self, obj, attr):
        attrs = attr.split('.')
        for a in attrs[:-1]:
            obj = getattr(obj, a)
        return getattr(obj, attrs[-1])

    def set_nested_attr(self, obj, attr, value):
        attrs = attr.split('.')
        for a in attrs[:-1]:
            obj = getattr(obj, a)
        setattr(obj, attrs[-1], value)
