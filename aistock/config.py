"""
Central configuration dataclasses for the simplified AIStock Robot runtime.

The previous codebase scattered configuration across mutable global modules and
interactive prompts, which made deterministic runs impossible.  The new
configuration model is explicit, structured, and serialisable so that every run
can be reproduced by reusing the same configuration payload.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from enum import Enum


class RunMode(str, Enum):
    """Supported execution modes."""

    RESEARCH = "research"  # Offline analytics / notebooks
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"

    def is_live(self) -> bool:
        return self in {RunMode.PAPER, RunMode.LIVE}


@dataclass(frozen=True)
class RiskLimits:
    """
    Hard risk controls enforced by :class:`aistock.risk.RiskEngine`.

    Percentages are expressed as decimals (e.g. 0.02 == 2%).
    """

    max_daily_loss_pct: float = 0.02
    max_drawdown_pct: float = 0.10
    per_trade_risk_pct: float = 0.01
    max_position_fraction: float = 0.25  # Of equity
    max_gross_exposure: float = 1.5  # multiple of equity
    max_leverage: float = 2.0
    per_symbol_notional_cap: float = 50_000.0
    max_single_position_units: float = 10_000.0
    max_holding_period_bars: int = 10_000
    kill_switch_enabled: bool = True

    def validate(self) -> None:
        for field_name, value in [
            ("max_daily_loss_pct", self.max_daily_loss_pct),
            ("max_drawdown_pct", self.max_drawdown_pct),
            ("per_trade_risk_pct", self.per_trade_risk_pct),
            ("max_position_fraction", self.max_position_fraction),
        ]:
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.max_position_fraction > 1:
            raise ValueError("max_position_fraction must be <= 1")
        if self.max_gross_exposure <= 0:
            raise ValueError("max_gross_exposure must be positive")
        if self.max_leverage <= 0:
            raise ValueError("max_leverage must be positive")
        if self.per_symbol_notional_cap < 0:
            raise ValueError("per_symbol_notional_cap must be >= 0")
        if self.max_single_position_units < 0:
            raise ValueError("max_single_position_units must be >= 0")
        if self.max_holding_period_bars <= 0:
            raise ValueError("max_holding_period_bars must be positive")


@dataclass(frozen=True)
class DataSource:
    """
    Declarative description of a historical data source.

    The loader intentionally captures only what is required for deterministic
    simulation: where the files live and how timestamps should be interpreted.
    """

    path: str
    timezone: timezone = timezone.utc
    symbols: Sequence[str] | None = None
    bar_interval: timedelta = timedelta(minutes=1)
    warmup_bars: int = 100
    allow_nan: bool = False
    exchange: str = "NYSE"  # Exchange for calendar validation
    enforce_trading_hours: bool = True  # Skip bars outside trading hours
    allow_extended_hours: bool = False  # Include pre-market/after-hours


@dataclass(frozen=True)
class DataQualityConfig:
    """Rules for validating input datasets."""

    max_gap_bars: int = 5
    require_monotonic_timestamps: bool = True
    fill_missing_with_last: bool = False
    zero_volume_allowed: bool = True


@dataclass(frozen=True)
class UniverseConfig:
    """
    Parameters controlling automatic universe selection.

    The selector analyses recent history for every symbol available in the data
    directory, ranks candidates by a blended momentum/volatility/volume score,
    and returns the highest scoring names.
    """

    max_symbols: int = 10
    lookback_bars: int = 250
    min_avg_volume: float = 0.0
    min_price: float | None = None
    max_price: float | None = None
    include: Sequence[str] = field(default_factory=tuple)
    exclude: Sequence[str] = field(default_factory=tuple)
    momentum_weight: float = 0.6
    volatility_weight: float = 0.3
    volume_weight: float = 0.1

    def validate(self) -> None:
        if self.max_symbols <= 0:
            raise ValueError("max_symbols must be positive")
        if self.lookback_bars <= 1:
            raise ValueError("lookback_bars must be greater than 1")
        if self.min_avg_volume < 0:
            raise ValueError("min_avg_volume must be non-negative")
        if any(symbol == "" for symbol in self.include):
            raise ValueError("include list contains empty symbol")
        if any(symbol == "" for symbol in self.exclude):
            raise ValueError("exclude list contains empty symbol")
        weight_sum = self.momentum_weight + self.volatility_weight + self.volume_weight
        if weight_sum <= 0:
            raise ValueError("At least one universe weight must be positive")

@dataclass(frozen=True)
class StrategyConfig:
    """Parameters for the built-in moving-average strategy."""

    short_window: int = 8
    long_window: int = 21
    exit_window: int = 10  # trailing stop look-back
    take_profit_multiple: float = 2.0
    stop_loss_multiple: float = 1.5
    ml_enabled: bool = False
    ml_model_path: str = "models/ml_model.json"
    ml_confidence_threshold: float = 0.55
    ml_feature_lookback: int = 30

    def validate(self) -> None:
        if self.short_window <= 0 or self.long_window <= 0:
            raise ValueError("Strategy windows must be positive")
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be < long_window")
        if self.exit_window <= 0:
            raise ValueError("exit_window must be positive")
        if self.take_profit_multiple <= 0 or self.stop_loss_multiple <= 0:
            raise ValueError("profit/loss multiples must be positive")
        if self.ml_confidence_threshold <= 0 or self.ml_confidence_threshold >= 1:
            raise ValueError("ml_confidence_threshold must be between 0 and 1")


@dataclass(frozen=True)
class EngineConfig:
    """
    Core runtime configuration shared across run modes.

    - ``initial_equity`` is expressed in account currency units.
    - ``commission_per_trade`` is a flat fee applied to each filled order.
    - ``slippage_bps`` is expressed in basis points (1/100th of a percent).
    """

    risk: RiskLimits = field(default_factory=RiskLimits)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    data_quality: DataQualityConfig = field(default_factory=DataQualityConfig)
    initial_equity: float = 100_000.0
    commission_per_trade: float = 1.0
    slippage_bps: float = 5.0  # 0.05 %
    reporting_currency: str = "USD"
    clock_timezone: timezone = timezone.utc

    def validate(self) -> None:
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if self.commission_per_trade < 0:
            raise ValueError("commission_per_trade must be >= 0")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps must be >= 0")
        self.risk.validate()
        self.strategy.validate()
        self.data_quality  # noqa: B018 - ensure dataclass field instantiation


@dataclass(frozen=True)
class ExecutionConfig:
    """Execution assumptions for paper/backtest brokers."""

    default_order_quantity: float = 1.0
    market_latency_ms: int = 150
    partial_fill_probability: float = 0.0
    cancel_on_disconnect: bool = True
    slip_bps_limit: float = 20.0

    def validate(self) -> None:
        if self.default_order_quantity <= 0:
            raise ValueError("default_order_quantity must be positive")
        if self.market_latency_ms < 0:
            raise ValueError("market_latency_ms must be >= 0")
        if not 0 <= self.partial_fill_probability <= 1:
            raise ValueError("partial_fill_probability must be between 0 and 1")
        if self.slip_bps_limit < 0:
            raise ValueError("slip_bps_limit must be >= 0")


@dataclass(frozen=True)
class BrokerConfig:
    """
    Broker configuration with P0 Fix for secrets management.

    Credentials are loaded from environment variables by default:
    - IBKR_HOST (default: 127.0.0.1)
    - IBKR_PORT (default: 7497)
    - IBKR_CLIENT_ID (default: 1001)
    - IBKR_ACCOUNT (required for live IBKR trading)

    Direct credential arguments override environment variables.
    """

    backend: str = "paper"  # paper, ibkr
    ib_host: str = field(default_factory=lambda: os.getenv("IBKR_HOST", "127.0.0.1"))
    ib_port: int = field(default_factory=lambda: int(os.getenv("IBKR_PORT", "7497")))
    ib_client_id: int = field(default_factory=lambda: int(os.getenv("IBKR_CLIENT_ID", "1001")))
    ib_account: str | None = field(default_factory=lambda: os.getenv("IBKR_ACCOUNT"))
    ib_exchange: str = "SMART"
    ib_sec_type: str = "STK"
    ib_currency: str = "USD"
    reconnect_interval: int = 5
    contracts: dict[str, ContractSpec] = field(default_factory=dict)
    enable_market_data: bool = True

    def validate(self) -> None:
        if self.backend not in {"paper", "ibkr"}:
            raise ValueError("backend must be 'paper' or 'ibkr'")
        if self.ib_port <= 0:
            raise ValueError("ib_port must be positive")
        if self.ib_client_id < 0:
            raise ValueError("ib_client_id must be non-negative")
        # P0 Fix: Require IBKR_ACCOUNT for live trading
        if self.backend == "ibkr" and not self.ib_account:
            raise ValueError(
                "IBKR_ACCOUNT environment variable is required for live IBKR trading. "
                "Set it via: export IBKR_ACCOUNT=your_account_id"
            )


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    sec_type: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"
    multiplier: float | None = None
    local_symbol: str | None = None



@dataclass(frozen=True)
class BacktestConfig:
    """
    Aggregate configuration used by :class:`aistock.engine.BacktestRunner`.
    """

    data: DataSource
    engine: EngineConfig = field(default_factory=EngineConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    run_mode: RunMode = RunMode.BACKTEST
    universe: UniverseConfig | None = None

    def validate(self) -> None:
        self.engine.validate()
        self.execution.validate()
        self.broker.validate()
        if self.universe:
            self.universe.validate()

    @property
    def symbols(self) -> Iterable[str]:
        if self.data.symbols:
            return self.data.symbols
        raise ValueError(
            "No symbols specified in BacktestConfig; provide DataSource.symbols or configure UniverseConfig."
        )
