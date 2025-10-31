"""Configuration builder for fluent API."""

from __future__ import annotations

from ..config import BrokerConfig, DataQualityConfig, ExecutionConfig, RiskLimits
from ..fsd import FSDConfig
from .trading_config import TradingConfig


class ConfigBuilder:
    """Fluent builder for TradingConfig.

    Example:
        config = (ConfigBuilder()
            .with_initial_capital(10000)
            .with_symbols(['AAPL', 'MSFT'])
            .with_conservative_risk()
            .build())
    """

    def __init__(self):
        self._fsd = FSDConfig()
        self._risk = RiskLimits()
        self._execution = ExecutionConfig()
        self._data_quality = DataQualityConfig()
        self._broker: BrokerConfig | None = None

        self._initial_capital = 10000.0
        self._symbols: list[str] | None = None
        self._timeframes: list[str] | None = None
        self._enable_professional = True
        self._safeguard_config: dict | None = None
        self._minimum_balance = 0.0
        self._minimum_balance_enabled = True
        self._checkpoint_dir = 'state'
        self._enable_checkpointing = True
        self._restore_from_checkpoint = False

    def with_initial_capital(self, capital: float) -> ConfigBuilder:
        """Set initial capital."""
        self._initial_capital = capital
        return self

    def with_symbols(self, symbols: list[str]) -> ConfigBuilder:
        """Set trading symbols."""
        self._symbols = symbols
        return self

    def with_timeframes(self, timeframes: list[str]) -> ConfigBuilder:
        """Set trading timeframes."""
        self._timeframes = timeframes
        return self

    def with_fsd_config(self, fsd: FSDConfig) -> ConfigBuilder:
        """Set FSD configuration."""
        self._fsd = fsd
        return self

    def with_conservative_risk(self) -> ConfigBuilder:
        """Apply conservative risk settings."""
        self._risk.max_position_pct = 0.05  # 5% per position
        self._risk.max_daily_loss_pct = 0.02  # 2% daily loss
        self._risk.max_drawdown_pct = 0.10  # 10% drawdown
        return self

    def with_aggressive_risk(self) -> ConfigBuilder:
        """Apply aggressive risk settings."""
        self._risk.max_position_pct = 0.15  # 15% per position
        self._risk.max_daily_loss_pct = 0.10  # 10% daily loss
        self._risk.max_drawdown_pct = 0.25  # 25% drawdown
        return self

    def with_minimum_balance(self, balance: float, enabled: bool = True) -> ConfigBuilder:
        """Set minimum balance protection."""
        self._minimum_balance = balance
        self._minimum_balance_enabled = enabled
        return self

    def with_broker(self, broker: BrokerConfig) -> ConfigBuilder:
        """Set broker configuration."""
        self._broker = broker
        return self

    def enable_professional_features(self, enabled: bool = True) -> ConfigBuilder:
        """Enable/disable professional features."""
        self._enable_professional = enabled
        return self

    def with_checkpointing(self, enabled: bool = True, restore: bool = False) -> ConfigBuilder:
        """Configure checkpointing."""
        self._enable_checkpointing = enabled
        self._restore_from_checkpoint = restore
        return self

    def build(self) -> TradingConfig:
        """Build the final configuration."""
        config = TradingConfig(
            fsd=self._fsd,
            risk=self._risk,
            execution=self._execution,
            data_quality=self._data_quality,
            broker=self._broker,
            initial_capital=self._initial_capital,
            symbols=self._symbols,
            timeframes=self._timeframes,
            enable_professional_features=self._enable_professional,
            safeguard_config=self._safeguard_config,
            minimum_balance=self._minimum_balance,
            minimum_balance_enabled=self._minimum_balance_enabled,
            checkpoint_dir=self._checkpoint_dir,
            enable_checkpointing=self._enable_checkpointing,
            restore_from_checkpoint=self._restore_from_checkpoint,
        )

        config.validate()
        return config
