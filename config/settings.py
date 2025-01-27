class Settings:
    # ==================================================
    # User Configurable Parameters
    # ==================================================

    # General Settings
    TIMEFRAME = '1 min'  # Options: '1 min', '5 min', '1 hour', '1 day', etc.
    DATA_SOURCE = 'live'  # Options: 'live', 'demo'

    # Account Information
    TOTAL_CAPITAL = 20  # Total trading capital

    # Trading Mode
    TRADING_MODE = 'crypto'  # Options: 'stock', 'crypto'

    # Instruments to trade (supporting both stock and crypto symbols)
    TRADE_INSTRUMENTS = ['ETH/USD']  # Example: ['AAPL', 'ETH/USD', 'BTC/USD']

    # Subscription Settings
    SUBSCRIPTIONS = {
        'stock': {
            'enabled': True,
            'data_sources': ['Cboe', 'IEX'],
            'snapshot_enabled': True,
            'max_snapshots': 100,
        },
        'crypto': {
            'enabled': True,
            'data_sources': ['ZeroHash'],
            'snapshot_enabled': False,  # Typically not required for crypto
        }
    }

    # Market Closure Handling
    CONTINUE_AFTER_CLOSE = False  # Default to not continue trading after market close

    # Trading Settings
    MAX_POSITION_SIZE = 100  # Max shares (or units) per trade
    RISK_PER_TRADE = 0.02    # Risk 2% of total capital per trade

    # Strategy Preferences
    ENABLED_STRATEGIES = {
        'trend_following': True,
        'mean_reversion': True,
        'momentum': True,
        'machine_learning': True,
    }

    # Technical Indicator Settings
    MOVING_AVERAGE_PERIODS = {
        'short_term': 5,
        'long_term': 20,
    }
    RSI_PERIOD = 14
    MACD_SETTINGS = {
        'fast_period': 12,
        'slow_period': 26,
        'signal_period': 9,
    }

    # Risk Management Settings
    STOP_LOSS_PERCENT = 0.005   # 0.5%
    TAKE_PROFIT_PERCENT = 0.01  # 1%
    MAX_DAILY_LOSS = 0.05       # 5% of total capital

    # Logging Settings
    LOG_LEVEL = 'INFO'  # Options: 'DEBUG', 'INFO', 'WARNING', 'ERROR'

    # Snapshot Behavior (existing in code but can remain if needed)
    SNAPSHOT_ENABLED = True            # Enable or disable snapshot usage
    SNAPSHOT_DYNAMIC_TIMER = True      # Align snapshot timing with TIMEFRAME

    # System Parameters (AI may adjust these)
    ORDER_TYPE = 'MKT'
