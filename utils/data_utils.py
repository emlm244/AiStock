import pandas as pd
import numpy as np
from utils.logger import setup_logger

def format_price_data(data):
    df = pd.DataFrame(data)
    return df

def calculate_returns(data):
    data['returns'] = data['close'].pct_change()
    return data

def align_time_series(data_list):
    aligned_data = pd.concat(data_list, axis=1)
    return aligned_data

def calculate_position_size(entry_price, stop_loss_price, risk_per_trade, available_cash, symbol):
    """
    Calculate a position size based on the available cash, per-trade risk, and instrument type.
    - Crypto (symbol has '/'): fractional units allowed, min 0.0001
    - Stocks (no '/'): integer shares, min 1
    """
    error_logger = setup_logger('error_logger', 'logs/error_logs/errors.log')
    try:
        risk_amount = available_cash * risk_per_trade
        risk_per_unit = abs(entry_price - stop_loss_price)
        if risk_per_unit == 0:
            return 0

        raw_position_size = risk_amount / risk_per_unit

        # Determine if the instrument allows fractional (assume '/' => crypto)
        allows_fractional = '/' in symbol

        if allows_fractional:
            # E.g. min trade size 0.0001
            min_trade_size = 0.0001
            # Round to 4 decimal places
            position_size = np.floor(raw_position_size * 10000) / 10000
            if position_size < min_trade_size:
                return 0
        else:
            # For stocks, must be integer shares
            min_trade_size = 1
            position_size = int(np.floor(raw_position_size))
            if position_size < min_trade_size:
                return 0

        # Also ensure not to exceed how many units you can afford
        max_affordable = available_cash / entry_price if entry_price != 0 else 0
        if allows_fractional:
            max_affordable = np.floor(max_affordable * 10000) / 10000
        else:
            max_affordable = int(np.floor(max_affordable))

        if position_size > max_affordable:
            position_size = max_affordable

        error_logger.debug(
            f"Calculated position size: {position_size} units with available cash: {available_cash} USD"
        )

        return position_size
    except Exception as e:
        error_logger.error(f"Error calculating position size: {e}")
        return 0
