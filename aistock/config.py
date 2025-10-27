"""
Configuration dataclasses for backtesting and strategy execution.
"""

from dataclasses import dataclass, field
from datetime import timezone
from typing import Optional


@dataclass
class DataQualityConfig:
    """Data quality and validation settings."""
    min_bars: int = 100
    max_gap_bars: int = 10
    min_volume: float = 0.0
    require_complete_ohlc: bool = True


@dataclass
class DataSource:
    """Configuration for data loading."""
    path: str
    timezone: timezone = field(default=timezone.utc)
    symbols: tuple[str, ...] = field(default_factory=tuple)
    warmup_bars: int = 50


@dataclass
class StrategyConfig:
    """Configuration for rule-based strategies."""
    enabled_strategies: dict[str, bool] = field(default_factory=lambda: {
        'trend_following': True,
        'mean_reversion': True,
        'momentum': True,
        'machine_learning': False,  # Requires trained model
    })
    
    # Moving averages
    ma_short_period: int = 9
    ma_long_period: int = 21
    
    # RSI
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    
    # ATR
    atr_period: int = 14
    
    # Signal aggregation
    min_signal_strength: float = 0.5


@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_daily_loss_pct: float = 0.03  # 3%
    max_drawdown_pct: float = 0.15     # 15%
    risk_per_trade_pct: float = 0.01   # 1%
    max_position_pct: float = 0.25     # 25%
    
    # Stop loss/take profit
    stop_loss_type: str = 'ATR'  # 'PERCENT' or 'ATR'
    stop_loss_pct: float = 0.02
    stop_loss_atr_mult: float = 2.0
    
    take_profit_type: str = 'RATIO'  # 'PERCENT', 'ATR', or 'RATIO'
    take_profit_pct: float = 0.04
    take_profit_atr_mult: float = 4.0
    take_profit_rr_ratio: float = 2.0


@dataclass
class ExecutionConfig:
    """Order execution settings."""
    order_type: str = 'MARKET'
    slippage_pct: float = 0.001
    commission_per_share: float = 0.005


@dataclass
class EngineConfig:
    """Backtesting engine configuration."""
    initial_equity: float = 10000.0
    commission_per_trade: float = 0.001  # 0.1%
    
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: Optional[RiskConfig] = field(default_factory=RiskConfig)
    data_quality: DataQualityConfig = field(default_factory=DataQualityConfig)


@dataclass
class UniverseConfig:
    """Universe selection configuration."""
    method: str = 'top_volume'  # 'top_volume', 'top_volatility', 'custom'
    max_symbols: int = 10
    min_volume: float = 1000000.0
    min_price: float = 5.0


@dataclass
class BacktestConfig:
    """Complete backtest configuration."""
    data: DataSource
    engine: EngineConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    universe: Optional[UniverseConfig] = None
    
    def validate(self):
        """Validate configuration parameters."""
        if self.engine.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        
        if self.engine.commission_per_trade < 0:
            raise ValueError("commission_per_trade cannot be negative")
        
        if not self.data.symbols and self.universe is None:
            raise ValueError("Must provide either data.symbols or universe config")
