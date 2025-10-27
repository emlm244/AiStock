# config/settings.py

import os


class Settings:
    # ==================================================
    # User Configurable Parameters (via Prompt or Defaults)
    # ==================================================
    # These are defaults; many will be overridden by user prompts in main.py
    TRADING_MODE = 'crypto'  # Options: 'stock', 'crypto', 'forex'
    TRADE_INSTRUMENTS = ['ETH/USD', 'BTC/USD']  # List of symbols to trade
    AUTONOMOUS_MODE = True  # Master switch for enhanced adaptation
    ENABLE_ADAPTIVE_RISK = True  # Allow SL/TP to adapt to volatility? (Requires AUTONOMOUS_MODE)
    ENABLE_AUTO_RETRAINING = True  # Allow automated ML retraining? (Requires AUTONOMOUS_MODE)
    ENABLE_DYNAMIC_STRATEGY_WEIGHTING = True  # Allow strategy weights to change? (Requires AUTONOMOUS_MODE)
    CONTINUE_AFTER_CLOSE = True  # Allow trading outside Regular Trading Hours (RTH)? Relevant for stocks.

    # ==================================================
    # General Settings
    # ==================================================
    TIMEFRAME = '30 secs'  # e.g., '1 sec', '5 secs', '1 min', '5 mins', '1 hour', '1 day'
    DATA_SOURCE = 'live'  # 'live' or 'historical' (for backtesting - not fully implemented)
    TIMEZONE = os.getenv(
        'TIMEZONE', 'America/New_York'
    )  # Timezone for logging, daily resets, market hours interpretation
    TWS_TIMEZONE = os.getenv(
        'TIMEZONE', 'America/New_York'
    )  # IMPORTANT: Timezone where TWS/Gateway application is running (affects timestamp parsing)
    EXCHANGE_TIMEZONES = {  # Timezones of specific exchanges for accurate market hour checks (used as fallback if ContractDetails unavailable)
        'SMART': 'America/New_York',
        'NYSE': 'America/New_York',
        'NASDAQ': 'America/New_York',
        'ARCA': 'America/New_York',
        'PAXOS': 'UTC',  # Crypto typically UTC
        'IDEALPRO': 'UTC',  # Forex typically UTC
        # Add other exchanges as needed
    }

    # ==================================================
    # Account & Capital
    # ==================================================
    TOTAL_CAPITAL = 10000  # Initial seed capital (will be updated from broker)

    # ==================================================
    # Trading Execution Settings
    # ==================================================
    # Position Sizing & Risk per Trade
    RISK_PER_TRADE = 0.01  # Percentage of total equity to risk per trade (e.g., 0.01 = 1%)
    # Optional: Max units per asset (absolute quantity) - Use carefully, % equity is often better
    # MAX_POSITION_SIZE_UNITS = 10000
    # Optional: Max % of equity allowed in a single position's value
    MAX_SINGLE_POSITION_PERCENT = 0.25

    # Order Configuration
    ORDER_TYPE = 'MKT'  # Default order type for parent entry ('MKT', 'LMT')
    # Optional: Add offset for Limit orders (e.g., place LMT slightly away from current price)
    # LMT_ORDER_OFFSET_TICKS = 2 # Number of minimum ticks away from reference price

    # Estimated Costs for Sizing (used if enabled in data_utils.calculate_position_size)
    ESTIMATED_COMMISSION_PER_SHARE = 0.005  # Example commission per share/unit (adjust based on broker schedule)
    ESTIMATED_SLIPPAGE_PER_SHARE = 0.01  # Example slippage per share/unit (adjust based on asset/volatility)

    # ==================================================
    # Strategy Management
    # ==================================================
    ENABLED_STRATEGIES = {  # Strategies to load initially
        'trend_following': True,
        'mean_reversion': True,
        'momentum': True,
        'machine_learning': True,
    }
    # Dynamic Weighting (if ENABLE_DYNAMIC_STRATEGY_WEIGHTING)
    STRAT_PERF_LOOKBACK_DAYS = 3  # Lookback window (days) for strategy performance calculation
    STRAT_MIN_TRADES_WEIGHTING = (
        10  # Min trades required within lookback for performance to influence weight significantly
    )
    # Signal Aggregation
    AGGREGATION_SIGNAL_THRESHOLD = 0.5  # Required average weighted signal strength to trigger a trade (0 to 1)

    # ==================================================
    # ML Strategy Specifics
    # ==================================================
    ML_CONFIDENCE_THRESHOLD = 0.60  # Minimum prediction probability to generate ML signal
    # ML_USE_PARTIAL_FIT = False # Use online learning? (Experimental, requires careful implementation)
    ML_MODEL_AUTO_RELOAD = True  # Check for new model files periodically?
    ML_MODEL_RELOAD_INTERVAL_MIN = 15  # How often to check for new model files (reduced)
    # Automated Retraining (if ENABLE_AUTO_RETRAINING)
    RETRAINING_INTERVAL_HOURS = 24 * 7  # How often to trigger retraining based on time (e.g., weekly)
    RETRAINING_PERFORMANCE_THRESHOLD = (
        0.48  # Trigger retraining if ML strategy win rate drops below this % (0.0 to 1.0)
    )
    RETRAINING_MIN_TRADES_THRESHOLD = (
        25  # Minimum ML trades before performance check triggers retraining (increased slightly)
    )

    # ==================================================
    # Technical Indicator & Regime Settings
    # ==================================================
    # --> Moving Averages (Trend Following & Features)
    MOVING_AVERAGE_PERIODS = {'short_term': 9, 'long_term': 21}
    # --> RSI (Mean Reversion & ML Features)
    RSI_PERIOD = 14
    RSI_OVERBOUGHT = 70  # RSI level suggesting overbought (also adaptive optimizer bound)
    RSI_OVERSOLD = 30  # RSI level suggesting oversold (also adaptive optimizer bound)
    # --> MACD (ML Features)
    MACD_SETTINGS = {'fast_period': 12, 'slow_period': 26, 'signal_period': 9}
    # --> Momentum Strategy
    MOMENTUM_PRICE_CHANGE_PERIOD = 5  # Lookback period for price change calc
    MOMENTUM_PRICE_CHANGE_THRESHOLD = 0.02  # Min % price change to trigger signal
    MOMENTUM_VOLUME_MULTIPLIER = 1.5  # Min volume increase over average to confirm signal
    # --> ATR (Volatility & Stops/TPs)
    ATR_PERIOD = 14
    MIN_ATR_VALUE = 1e-8  # Minimum ATR value to prevent division by zero (adjusted)
    # --> ADX (Regime Detection)
    ADX_PERIOD = 14
    ADX_TREND_THRESHOLD = 25  # ADX level above which market is considered trending
    # --> Bollinger Bands (Regime Detection)
    BBANDS_PERIOD = 20
    BBANDS_STDDEV = 2.0
    BBW_SQUEEZE_THRESHOLD = 0.015  # BB Width (% of middle band) below which squeeze is detected
    VOLATILITY_THRESHOLD_ATR_PCT = 0.02  # ATR % of close price above which is considered 'High' Volatility
    LOW_VOLATILITY_THRESHOLD_ATR_PCT = 0.005  # ATR % of close price below which is considered 'Low' Volatility

    # ==================================================
    # Risk Management Settings
    # ==================================================
    # --> Stop Loss Configuration
    STOP_LOSS_TYPE = 'ATR'  # Options: 'PERCENT', 'ATR'
    STOP_LOSS_PERCENT = 0.005  # % distance if STOP_LOSS_TYPE = 'PERCENT'
    STOP_LOSS_ATR_MULTIPLIER = 2.0  # ATR multiple if STOP_LOSS_TYPE = 'ATR'
    # --> Take Profit Configuration
    TAKE_PROFIT_TYPE = 'RATIO'  # Options: 'PERCENT', 'ATR', 'RATIO' (Risk/Reward Ratio)
    TAKE_PROFIT_PERCENT = 0.01  # % distance if TAKE_PROFIT_TYPE = 'PERCENT'
    TAKE_PROFIT_ATR_MULTIPLIER = 4.0  # ATR multiple if TAKE_PROFIT_TYPE = 'ATR'
    TAKE_PROFIT_RR_RATIO = 2.0  # Risk/Reward ratio if TAKE_PROFIT_TYPE = 'RATIO'

    # --> Adaptive Risk (uses Volatility Regime, if ENABLE_ADAPTIVE_RISK)
    ADAPTIVE_SL_TP_VOLATILITY_MAP = {
        # Volatility Regime: Multiplier applied to base SL/TP distance/ratio
        'Low': 0.8,
        'Squeeze': 0.7,  # Add squeeze behavior
        'Normal': 1.0,
        'High': 1.2,
    }
    # Minimum distance for SL/TP based on risk per unit factor (relative to price)
    MIN_RISK_PER_UNIT_FACTOR = 0.0001  # e.g., risk per unit must be at least 0.01% of entry price

    # --> Portfolio Level Risk Limits
    MAX_DAILY_LOSS = 0.03  # Max % loss of *initial* capital allowed per day
    MAX_DRAWDOWN_LIMIT = 0.15  # Max % drawdown from peak equity before halting
    # Optional: Factor to determine drawdown recovery threshold (e.g., 0.8 means DD must recover below 80% of limit)
    DRAWDOWN_RECOVERY_THRESHOLD_FACTOR = 0.8

    # ==================================================
    # Logging & System Settings
    # ==================================================
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG')  # 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    LOG_TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S %Z%z'  # Format for timestamps in logs
    # IBKR_GENERIC_TICKS = "100,101,104,106,165,233,236,258" # Example: Specific tick types if needed

    # System Behavior
    STATE_SAVE_INTERVAL_SECONDS = 300  # How often to save bot state (5 minutes)
    RECONCILIATION_INTERVAL_SECONDS = 600  # How often to reconcile with broker data (10 minutes)
    MARKET_REGIME_UPDATE_INTERVAL_SECONDS = 60  # How often to recalculate market regime
    MAX_BARS_IN_MEMORY = 5000  # Max historical/live bars per symbol kept in memory
    CANCEL_ORDERS_ON_EXIT = False  # Cancel open orders when bot stops? Use True with caution.
    MAX_DATA_STALENESS_SECONDS = 60  # Max age of latest price data before pausing trading for a symbol

    # --> Parameter Optimizer (Simplified adaptive heuristics, if AUTONOMOUS_MODE)
    OPTIMIZER_INTERVAL_HOURS = 4  # How often the optimizer heuristics run
    OPTIMIZER_LOOKBACK_DAYS = 1  # How far back optimizer looks at trade history
    OPTIMIZER_MIN_TRADES = 15  # Min trades needed for optimizer heuristics to apply to a strategy parameter

    # ==================================================
    # Autonomous Mode Settings (New AI Controller)
    # ==================================================
    TRADING_MODE_TYPE = 'autonomous'  # Options: 'autonomous', 'expert'

    # Autonomous optimization intervals
    AUTO_OPTIMIZE_INTERVAL_HOURS = 24  # Run optimization every 24 hours
    AUTO_OPTIMIZE_MIN_TRADES = 50  # Or after 50 trades, whichever comes first
    AUTO_OPTIMIZE_LOOKBACK_DAYS = 7  # Look back 7 days for optimization data
    OPTIMIZATION_N_CALLS = 20  # Number of Bayesian optimization iterations

    # Strategy selection and position sizing
    STRATEGY_SELECTION_INTERVAL_HOURS = 6  # Update strategy selection every 6 hours
    POSITION_SIZING_UPDATE_INTERVAL = 20  # Update position sizing every 20 trades

    # Parameter bounds for AI optimization (safety limits)
    AUTO_OPTIMIZE_BOUNDS = {
        'risk_per_trade_min': 0.005,  # 0.5% minimum
        'risk_per_trade_max': 0.02,  # 2% maximum
        'stop_loss_atr_min': 1.0,
        'stop_loss_atr_max': 4.0,
        'take_profit_rr_min': 1.5,
        'take_profit_rr_max': 4.0,
    }

    # ==================================================
    # API Connection / Data Settings
    # ==================================================
    RECONNECT_DELAY_SECONDS = 15  # Delay before attempting API reconnect (increased)
    # MAX_API_RETRIES = 3 # Max connection retries (Currently illustrative, logic in API handler)
    # API_RETRY_DELAY = 5 # Delay between retries (Currently illustrative)
