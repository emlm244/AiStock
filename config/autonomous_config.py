# config/autonomous_config.py

"""
Autonomous Configuration - Simplified 3-Parameter Setup

Allows users to configure the bot with just:
1. Max Capital
2. Timeframe
3. Symbols

All other parameters are set to safe defaults and optimized by AI.
"""

from dataclasses import dataclass, field

from config.settings import Settings


@dataclass
class AutonomousConfig:
    """
    Simplified configuration for autonomous mode

    User only needs to set 3 parameters:
    - max_capital: How much money to trade with
    - timeframe: How fast to trade (e.g., "1 min", "5 mins")
    - symbols: What instruments to trade
    """

    max_capital: float
    timeframe: str
    symbols: list[str]

    # Optional: Asset type (auto-detected from symbols if not provided)
    asset_type: str = field(default='crypto')

    def __post_init__(self):
        """Validate and auto-detect asset type"""
        if not self.symbols:
            raise ValueError('At least one symbol must be provided')

        # Auto-detect asset type from symbols
        if self.asset_type == 'crypto':
            # Check if symbols look like crypto
            for symbol in self.symbols:
                if 'BTC' in symbol or 'ETH' in symbol or 'USDT' in symbol:
                    self.asset_type = 'crypto'
                    break
                elif '/' in symbol and 'USD' in symbol:
                    # Could be crypto (BTC/USD) or forex (EUR/USD)
                    if any(crypto in symbol for crypto in ['BTC', 'ETH', 'SOL', 'ADA']):
                        self.asset_type = 'crypto'
                    else:
                        self.asset_type = 'forex'
                else:
                    self.asset_type = 'stock'

    def to_full_settings(self) -> Settings:
        """
        Convert simplified 3-parameter config to full Settings object

        Sets safe defaults for all parameters that will be optimized by AI
        """
        settings = Settings()

        # Apply user-specified parameters
        settings.TOTAL_CAPITAL = self.max_capital
        settings.TIMEFRAME = self.timeframe
        settings.TRADE_INSTRUMENTS = self.symbols
        settings.TRADING_MODE = self.asset_type

        # Set autonomous mode
        settings.TRADING_MODE_TYPE = 'autonomous'
        settings.AUTONOMOUS_MODE = True
        settings.ENABLE_ADAPTIVE_RISK = True
        settings.ENABLE_AUTO_RETRAINING = True
        settings.ENABLE_DYNAMIC_STRATEGY_WEIGHTING = True

        # Set safe defaults for AI-optimizable parameters
        # These will be optimized by the AutonomousOptimizer

        # Risk Management (conservative defaults)
        settings.RISK_PER_TRADE = 0.01  # 1% - will be optimized
        settings.STOP_LOSS_TYPE = 'ATR'
        settings.STOP_LOSS_ATR_MULTIPLIER = 2.0  # Will be optimized
        settings.TAKE_PROFIT_TYPE = 'RATIO'
        settings.TAKE_PROFIT_RR_RATIO = 2.0  # Will be optimized

        # Technical Indicators (standard defaults)
        settings.RSI_PERIOD = 14  # Will be optimized
        settings.RSI_OVERBOUGHT = 70
        settings.RSI_OVERSOLD = 30
        settings.ATR_PERIOD = 14  # Will be optimized

        settings.MOVING_AVERAGE_PERIODS = {
            'short_term': 9,  # Will be optimized
            'long_term': 21,  # Will be optimized
        }

        settings.MACD_SETTINGS = {'fast_period': 12, 'slow_period': 26, 'signal_period': 9}

        # Strategy Settings
        settings.ENABLED_STRATEGIES = {
            'trend_following': True,
            'mean_reversion': True,
            'momentum': True,
            'machine_learning': True,
        }

        # ML Strategy
        settings.ML_CONFIDENCE_THRESHOLD = 0.60  # Will be optimized
        settings.ML_MODEL_AUTO_RELOAD = True
        settings.RETRAINING_INTERVAL_HOURS = 24 * 7  # Weekly

        # Optimization Settings
        settings.AUTO_OPTIMIZE_INTERVAL_HOURS = 24  # Optimize daily
        settings.AUTO_OPTIMIZE_MIN_TRADES = 50  # Or after 50 trades
        settings.AUTO_OPTIMIZE_LOOKBACK_DAYS = 7

        settings.STRATEGY_SELECTION_INTERVAL_HOURS = 6
        settings.POSITION_SIZING_UPDATE_INTERVAL = 20  # trades

        # Define optimization bounds
        settings.AUTO_OPTIMIZE_BOUNDS = {
            'risk_per_trade_min': 0.005,  # 0.5%
            'risk_per_trade_max': 0.02,  # 2%
            'stop_loss_atr_min': 1.0,
            'stop_loss_atr_max': 4.0,
            'take_profit_rr_min': 1.5,
            'take_profit_rr_max': 4.0,
        }

        # Asset-specific settings
        if self.asset_type == 'crypto':
            settings.CONTINUE_AFTER_CLOSE = True  # Crypto trades 24/7
        elif self.asset_type == 'stock':
            settings.CONTINUE_AFTER_CLOSE = False  # Stocks only during market hours

        return settings

    @classmethod
    def from_user_input(cls) -> 'AutonomousConfig':
        """
        Create config from interactive user input

        Returns:
            AutonomousConfig instance
        """
        print('\n' + '=' * 60)
        print('  AUTONOMOUS MODE - SIMPLIFIED CONFIGURATION')
        print('=' * 60)
        print('\nThe AI will optimize all strategy parameters automatically.')
        print('You only need to provide 3 inputs:\n')

        # Get capital
        while True:
            try:
                capital_input = input('1. Max Capital to trade with (e.g., 10000): $')
                max_capital = float(capital_input)
                if max_capital <= 0:
                    print('   Error: Capital must be positive')
                    continue
                break
            except ValueError:
                print('   Error: Please enter a valid number')

        # Get timeframe
        print('\n2. Trading Timeframe:')
        print("   Examples: '1 sec', '30 secs', '1 min', '5 mins', '1 hour'")
        timeframe = input('   Enter timeframe: ').strip()

        # Get symbols
        print('\n3. Symbols to trade (comma-separated):')
        print('   Examples:')
        print('   - Crypto: BTC/USD, ETH/USD')
        print('   - Stocks: AAPL, TSLA, GOOGL')
        print('   - Forex: EUR/USD, GBP/USD')
        symbols_input = input('   Enter symbols: ').strip()
        symbols = [s.strip() for s in symbols_input.split(',')]

        # Create config
        config = cls(max_capital=max_capital, timeframe=timeframe, symbols=symbols)

        # Show summary
        print('\n' + '=' * 60)
        print('  CONFIGURATION SUMMARY')
        print('=' * 60)
        print(f'  Capital:   ${config.max_capital:,.2f}')
        print(f'  Timeframe: {config.timeframe}')
        print(f'  Symbols:   {", ".join(config.symbols)}')
        print(f'  Asset Type: {config.asset_type}')
        print('\n  AI will optimize:')
        print('  - Risk per trade (0.5% - 2%)')
        print('  - Stop loss levels')
        print('  - Take profit levels')
        print('  - Technical indicator periods')
        print('  - Strategy selection')
        print('  - Position sizing')
        print('=' * 60)

        # Confirm
        confirm = input('\nProceed with this configuration? (y/n): ').strip().lower()
        if confirm != 'y':
            print('Configuration cancelled. Please run setup again.')
            raise ValueError('User cancelled configuration')

        return config

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            'max_capital': self.max_capital,
            'timeframe': self.timeframe,
            'symbols': self.symbols,
            'asset_type': self.asset_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'AutonomousConfig':
        """Create from dictionary"""
        return cls(
            max_capital=data['max_capital'],
            timeframe=data['timeframe'],
            symbols=data['symbols'],
            asset_type=data.get('asset_type', 'crypto'),
        )
