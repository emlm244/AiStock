"""
Configuration dataclasses for backtesting and strategy execution.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .capital_management import CapitalManagementConfig
    from .risk import AdvancedRiskConfig
    from .stop_control import StopConfig


@dataclass(frozen=True)
class DataQualityConfig:
    """Data quality and validation settings."""

    min_bars: int = 30  # Minimum bars required (reduced from 100 for testing)
    max_gap_bars: int = 10
    min_volume: float = 0.0
    require_complete_ohlc: bool = True
    require_monotonic_timestamps: bool = True
    zero_volume_allowed: bool = False
    fill_missing_with_last: bool = False
    max_price_change_pct: float = 0.50  # 50% max single-bar change
    min_price: float = 0.01  # Minimum valid price


@dataclass(frozen=True)
class DataSource:
    """Configuration for data loading."""

    path: str
    timezone: dt.tzinfo = field(default=dt.timezone.utc)
    symbols: tuple[str, ...] = field(default_factory=tuple)
    warmup_bars: int = 50
    bar_interval: dt.timedelta = field(default_factory=lambda: dt.timedelta(minutes=1))
    enforce_trading_hours: bool = True
    exchange: str = 'NYSE'  # Default exchange for trading hours check
    allow_extended_hours: bool = False  # Whether to allow extended hours trading


@dataclass(frozen=True)
class StrategyConfig:
    """Legacy configuration for rule-based strategies (unused in FSD mode)."""

    pass  # Retained for backward compatibility only


# Legacy RiskConfig removed - use RiskLimits class instead


@dataclass(frozen=True)
class RiskLimits:
    """
    Comprehensive risk limits for live trading and backtesting.

    This is the primary risk configuration class used throughout the system.
    """

    # Core risk limits
    max_daily_loss_pct: float = 0.05  # 5% daily loss → halt
    max_drawdown_pct: float = 0.15  # 15% drawdown → kill switch
    max_position_fraction: float = 0.20  # 20% per asset max
    max_gross_exposure: float = 2.0  # 200% of equity max
    max_leverage: float = 2.0  # 2:1 leverage max
    max_holding_period_bars: int = 100  # Force exit after N bars

    # Position sizing
    per_trade_risk_pct: float = 0.01  # 1% risk per trade
    per_symbol_notional_cap: float = 100000.0  # Max notional per symbol
    max_single_position_units: float = 1000.0  # Max units per position

    # Order rate limiting
    rate_limit_enabled: bool = True
    max_orders_per_minute: int = 10  # Rate limit: 10/min
    max_orders_per_day: int = 100  # Rate limit: 100/day

    # Kill switch
    kill_switch_enabled: bool = True  # Enable kill switch

    def validate(self) -> None:
        """
        P2-4 Fix: Validate risk limits parameters.

        Raises:
            ValueError: If any parameter is invalid
        """
        if not 0.0 < self.max_daily_loss_pct <= 1.0:
            raise ValueError(f'max_daily_loss_pct must be in (0, 1], got {self.max_daily_loss_pct}')

        if not 0.0 < self.max_drawdown_pct <= 1.0:
            raise ValueError(f'max_drawdown_pct must be in (0, 1], got {self.max_drawdown_pct}')

        if not 0.0 < self.max_position_fraction <= 1.0:
            raise ValueError(f'max_position_fraction must be in (0, 1], got {self.max_position_fraction}')

        if self.max_gross_exposure <= 0:
            raise ValueError(f'max_gross_exposure must be positive, got {self.max_gross_exposure}')

        if self.max_leverage <= 0:
            raise ValueError(f'max_leverage must be positive, got {self.max_leverage}')

        if self.max_holding_period_bars < 1:
            raise ValueError(f'max_holding_period_bars must be >= 1, got {self.max_holding_period_bars}')

        if not 0.0 < self.per_trade_risk_pct <= 1.0:
            raise ValueError(f'per_trade_risk_pct must be in (0, 1], got {self.per_trade_risk_pct}')

        if self.per_symbol_notional_cap <= 0:
            raise ValueError(f'per_symbol_notional_cap must be positive, got {self.per_symbol_notional_cap}')

        if self.max_single_position_units <= 0:
            raise ValueError(f'max_single_position_units must be positive, got {self.max_single_position_units}')

        if self.max_orders_per_minute < 1:
            raise ValueError(f'max_orders_per_minute must be >= 1, got {self.max_orders_per_minute}')

        if self.max_orders_per_day < 1:
            raise ValueError(f'max_orders_per_day must be >= 1, got {self.max_orders_per_day}')


@dataclass(frozen=True)
class AccountCapabilities:
    """
    Account-level trading capabilities and restrictions.

    Controls what instruments can be traded, trading hours,
    and cash account settlement rules.
    """

    # Account basics
    account_type: str = 'cash'  # 'cash' or 'margin'
    account_balance: float = 0.0  # Total account balance (not trading allocation)

    # Tradeable instruments
    enable_stocks: bool = True
    enable_etfs: bool = True
    enable_futures: bool = False  # Requires $2,000+ margin minimum
    enable_options: bool = False  # Requires options approval

    # PDT Rule (Pattern Day Trader - margin accounts under $25k)
    pdt_rule_enabled: bool = True  # Track day trades for margin accounts
    max_day_trades_per_5_days: int = 3  # PDT limit

    # Trading hours
    allow_extended_hours: bool = False  # Pre-market + after-hours

    # Cash account settlement (T+2 for stocks)
    enforce_settlement: bool = True  # Track T+2 settlement for cash accounts

    def validate(self) -> None:
        """Validate account capabilities configuration."""
        valid_account_types = ('cash', 'margin')
        if self.account_type not in valid_account_types:
            raise ValueError(
                f"account_type must be one of {valid_account_types}, got {self.account_type!r}"
            )

        if self.max_day_trades_per_5_days < 0:
            raise ValueError(
                f'max_day_trades_per_5_days must be non-negative, got {self.max_day_trades_per_5_days}'
            )

        if self.account_balance < 0:
            raise ValueError(f'account_balance must be non-negative, got {self.account_balance}')

        # At least one instrument type must be enabled
        if not any(attr for attr in (self.enable_stocks, self.enable_etfs, self.enable_futures, self.enable_options)):
            raise ValueError('At least one instrument type must be enabled')


@dataclass(frozen=True)
class ContractSpec:
    """
    IBKR contract specification.

    For futures contracts, use expiration_date to specify the contract month/date.
    The con_id field stores the IBKR unique contract identifier for reliable matching.

    Example for ES futures:
        ContractSpec(
            symbol='ES',
            sec_type='FUT',
            exchange='CME',
            multiplier=50,
            expiration_date='20260320',  # March 2026 expiry
            underlying='ES',
        )
    """

    symbol: str
    sec_type: str = 'STK'  # Security type: STK, FUT, OPT, CASH, etc.
    exchange: str = 'SMART'  # Exchange: SMART, NASDAQ, NYSE, CME, NYMEX, etc.
    currency: str = 'USD'  # Currency
    local_symbol: str = ''  # Local symbol (if different from symbol)
    multiplier: Optional[int] = None  # Contract multiplier (for futures/options)
    # Futures-specific fields
    expiration_date: Optional[str] = None  # YYYYMMDD format (lastTradeDateOrContractMonth)
    con_id: Optional[int] = None  # IBKR unique contract identifier
    underlying: Optional[str] = None  # Underlying symbol (e.g., 'ES' for ES futures)


@dataclass(frozen=True)
class BrokerConfig:
    """
    Broker connection and contract configuration.
    """

    backend: str = 'paper'  # "paper" or "ibkr"
    ib_host: str = '127.0.0.1'  # IBKR TWS/Gateway host
    ib_port: int = 7497  # IBKR port (7497=paper, 7496=live)
    ib_client_id: Optional[int] = None  # IBKR client ID (REQUIRED for IBKR backend)
    ib_account: Optional[str] = None  # IBKR account ID
    ib_sec_type: str = 'STK'  # Default security type
    ib_exchange: str = 'SMART'  # Default exchange
    ib_currency: str = 'USD'  # Default currency
    contracts: dict[str, ContractSpec] = field(default_factory=dict)

    def validate(self) -> None:
        """
        P2-4 Fix: Validate broker configuration.

        Raises:
            ValueError: If any parameter is invalid
        """
        valid_backends = {'paper', 'ibkr'}
        if self.backend not in valid_backends:
            raise ValueError(f'backend must be one of {valid_backends}, got {self.backend!r}')

        if not self.ib_host:
            raise ValueError('ib_host cannot be empty')

        if not 1 <= self.ib_port <= 65535:
            raise ValueError(f'ib_port must be in [1, 65535], got {self.ib_port}')

        if self.ib_client_id is not None and self.ib_client_id < 0:
            raise ValueError(f'ib_client_id must be non-negative, got {self.ib_client_id}')

        if self.backend == 'ibkr':
            if not self.ib_account:
                raise ValueError('ib_account is required when backend is "ibkr"')
            if self.ib_client_id is None:
                raise ValueError('ib_client_id is required when backend is "ibkr". Set IBKR_CLIENT_ID in .env')


@dataclass(frozen=True)
class ExecutionConfig:
    """Order execution settings."""

    order_type: str = 'MARKET'
    execution_style: str = 'adaptive'  # market, limit, twap, vwap, adaptive
    slippage_pct: float = 0.001
    slip_bps_limit: float = 10.0  # Slippage in basis points
    commission_per_share: float = 0.005
    partial_fill_probability: float = 0.0  # 0=always full fill, 1=always partial
    min_fill_fraction: float = 0.1  # Minimum fraction for partial fills
    limit_offset_bps: float = 5.0
    twap_slices: int = 4
    twap_window_minutes: int = 15
    vwap_slices: int = 4
    vwap_window_minutes: int = 15
    avoid_open_minutes: int = 15
    avoid_close_minutes: int = 15


@dataclass(frozen=True)
class EngineConfig:
    """Backtesting engine configuration."""

    initial_equity: float = 10000.0
    commission_per_trade: float = 0.001  # 0.1%
    slippage_bps: float = 10.0  # Slippage in basis points

    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskLimits = field(default_factory=RiskLimits)  # Use RiskLimits instead of RiskConfig
    data_quality: DataQualityConfig = field(default_factory=DataQualityConfig)


@dataclass(frozen=True)
class UniverseConfig:
    """Universe selection configuration (unused - symbols specified directly in FSD mode)."""

    pass  # Retained for backward compatibility only


@dataclass(frozen=True)
class BacktestConfig:
    """Complete backtest configuration."""

    data: DataSource
    engine: EngineConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    universe: Optional[UniverseConfig] = None
    broker: Optional[BrokerConfig] = None
    capital_management: Optional['CapitalManagementConfig'] = None
    stop_control: Optional['StopConfig'] = None
    account_capabilities: Optional[AccountCapabilities] = None
    # Advanced risk management (Kelly Criterion, correlation limits, regime detection, volatility scaling)
    advanced_risk: Optional['AdvancedRiskConfig'] = None

    def validate(self):
        """
        P2-4 Fix: Enhanced validation of configuration parameters.

        Validates all nested configurations.
        """
        # Engine validation
        if self.engine.initial_equity <= 0:
            raise ValueError('initial_equity must be positive')

        if self.engine.commission_per_trade < 0:
            raise ValueError('commission_per_trade cannot be negative')

        if self.engine.slippage_bps < 0:
            raise ValueError('slippage_bps cannot be negative')

        # Data validation
        if not self.data.symbols and self.universe is None:
            raise ValueError('Must provide either data.symbols or universe config')

        if self.data.warmup_bars < 0:
            raise ValueError('warmup_bars cannot be negative')

        # Execution validation
        if self.execution.slippage_pct < 0:
            raise ValueError('slippage_pct cannot be negative')

        if self.execution.commission_per_share < 0:
            raise ValueError('commission_per_share cannot be negative')

        valid_execution_styles = {'market', 'limit', 'twap', 'vwap', 'adaptive'}
        execution_style = self.execution.execution_style.lower().strip()
        if execution_style not in valid_execution_styles:
            raise ValueError(f'execution_style must be one of {valid_execution_styles}, got {execution_style!r}')

        if self.execution.limit_offset_bps < 0:
            raise ValueError('limit_offset_bps cannot be negative')

        if self.execution.twap_slices < 1:
            raise ValueError('twap_slices must be >= 1')

        if self.execution.twap_window_minutes < 0:
            raise ValueError('twap_window_minutes cannot be negative')

        if self.execution.vwap_slices < 1:
            raise ValueError('vwap_slices must be >= 1')

        if self.execution.vwap_window_minutes < 0:
            raise ValueError('vwap_window_minutes cannot be negative')

        if self.execution.avoid_open_minutes < 0:
            raise ValueError('avoid_open_minutes cannot be negative')

        if self.execution.avoid_close_minutes < 0:
            raise ValueError('avoid_close_minutes cannot be negative')

        if not 0.0 <= self.execution.partial_fill_probability <= 1.0:
            raise ValueError('partial_fill_probability must be in [0, 1]')

        if not 0.0 < self.execution.min_fill_fraction <= 1.0:
            raise ValueError('min_fill_fraction must be in (0, 1]')

        # Validate nested configs
        self.engine.risk.validate()
        if self.broker:
            self.broker.validate()
        if self.account_capabilities:
            self.account_capabilities.validate()
        if self.advanced_risk:
            self.advanced_risk.validate()
