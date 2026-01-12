"""
Configuration dataclasses for the backtesting framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..config import RiskLimits
    from ..fsd import FSDConfig


@dataclass
class WalkForwardConfig:
    """
    Configuration for walk-forward validation.

    Walk-forward validation helps detect overfitting by:
    1. Training on historical data
    2. Testing on out-of-sample data
    3. Moving the window forward and repeating
    """

    # Training window configuration
    initial_train_days: int = 252  # 1 year initial training period
    test_window_days: int = 21  # 1 month test period per fold
    step_days: int = 21  # Move forward 1 month between folds

    # Validation mode
    mode: Literal['expanding', 'rolling'] = 'expanding'
    rolling_window_days: int = 504  # 2 years for rolling mode

    # Final out-of-sample holdout
    final_holdout_days: int = 63  # 3 months final OOS test
    enable_final_holdout: bool = True

    # Minimum requirements
    min_folds: int = 3  # Minimum folds for valid walk-forward
    min_test_trades: int = 10  # Minimum trades per test period

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.initial_train_days < 30:
            raise ValueError('initial_train_days must be at least 30')
        if self.test_window_days < 5:
            raise ValueError('test_window_days must be at least 5')
        if self.step_days < 1:
            raise ValueError('step_days must be at least 1')
        if self.mode == 'rolling' and self.rolling_window_days < self.initial_train_days:
            raise ValueError('rolling_window_days must be >= initial_train_days')


@dataclass
class RealisticExecutionConfig:
    """
    Configuration for realistic execution modeling.

    Models transaction costs more accurately than fixed slippage:
    - Size-dependent slippage (larger orders = more slippage)
    - Volume constraints (can't fill more than X% of bar volume)
    - Bid-ask spread simulation
    - Market impact (temporary + permanent)
    """

    # Size-dependent slippage
    base_slippage_bps: float = 5.0  # Base slippage in basis points
    size_impact_factor: float = 0.5  # Additional slippage per 1% of volume
    max_slippage_bps: float = 50.0  # Maximum slippage cap

    # Volume constraints
    max_volume_participation: float = 0.05  # Max 5% of bar volume
    enable_volume_fill_limits: bool = True
    min_bar_volume: int = 100  # Skip bars with volume below this

    # Bid-ask spread simulation (for EOD data)
    spread_estimate_bps: float = 10.0  # Default spread estimate
    use_dynamic_spread: bool = True  # Estimate spread from volatility
    spread_volatility_factor: float = 0.1  # Spread = 10% of bar range

    # Market impact model (square-root model)
    enable_market_impact: bool = True
    temporary_impact_factor: float = 0.1  # Temporary price impact
    permanent_impact_factor: float = 0.01  # Permanent price impact

    # Commission
    commission_per_share: Decimal = field(default_factory=lambda: Decimal('0.005'))
    min_commission: Decimal = field(default_factory=lambda: Decimal('1.00'))

    # Partial fills
    enable_partial_fills: bool = True
    min_fill_fraction: float = 0.2  # Minimum fill fraction

    # Execution strategy
    execution_style: str = 'adaptive'  # market, limit, twap, vwap, adaptive
    limit_offset_bps: float = 5.0
    twap_slices: int = 4
    twap_window_minutes: int = 15
    vwap_slices: int = 4
    vwap_window_minutes: int = 15
    avoid_open_minutes: int = 15
    avoid_close_minutes: int = 15

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.base_slippage_bps < 0:
            raise ValueError('base_slippage_bps cannot be negative')
        if self.max_slippage_bps < self.base_slippage_bps:
            raise ValueError('max_slippage_bps must be >= base_slippage_bps')
        if not 0 < self.max_volume_participation <= 1:
            raise ValueError('max_volume_participation must be in (0, 1]')
        valid_styles = {'market', 'limit', 'twap', 'vwap', 'adaptive'}
        if self.execution_style.lower().strip() not in valid_styles:
            raise ValueError(f'execution_style must be one of {valid_styles}, got {self.execution_style!r}')
        if self.limit_offset_bps < 0:
            raise ValueError('limit_offset_bps cannot be negative')
        if self.twap_slices < 1:
            raise ValueError('twap_slices must be >= 1')
        if self.twap_window_minutes < 0:
            raise ValueError('twap_window_minutes cannot be negative')
        if self.vwap_slices < 1:
            raise ValueError('vwap_slices must be >= 1')
        if self.vwap_window_minutes < 0:
            raise ValueError('vwap_window_minutes cannot be negative')
        if self.avoid_open_minutes < 0:
            raise ValueError('avoid_open_minutes cannot be negative')
        if self.avoid_close_minutes < 0:
            raise ValueError('avoid_close_minutes cannot be negative')


@dataclass
class BacktestPlanConfig:
    """
    Full configuration for a backtest plan.

    This is the main configuration object that ties together:
    - Data parameters (symbols, dates, timeframe)
    - Walk-forward configuration
    - Execution configuration
    - Risk parameters
    - FSD (Q-Learning) configuration
    """

    # Data configuration
    symbols: list[str] = field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    timeframe: str = '1m'  # Minute bars

    # Walk-forward configuration (optional)
    walkforward: WalkForwardConfig | None = None

    # Execution configuration (optional)
    execution: RealisticExecutionConfig | None = None

    # Universe validation
    validate_universe: bool = True  # Check survivorship bias
    exclude_survivorship_bias: bool = True  # Exclude symbols with bias issues

    # Capital configuration
    initial_capital: Decimal = field(default_factory=lambda: Decimal('100000'))

    # Risk configuration (optional - uses defaults if not provided)
    risk_limits: RiskLimits | None = None

    # FSD (Q-Learning) configuration (optional)
    fsd_config: FSDConfig | None = None

    # Output configuration
    output_dir: str = 'backtest_results'
    save_trade_log: bool = True
    save_equity_curve: bool = True
    generate_report: bool = True

    # Performance options
    use_cache: bool = True  # Use Massive.com data cache
    parallel_folds: int = 1  # Reserved for future parallel fold execution (currently sequential)

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not self.symbols:
            raise ValueError('At least one symbol is required')
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError('end_date must be after start_date')
        if self.initial_capital <= 0:
            raise ValueError('initial_capital must be positive')

    def total_days(self) -> int:
        """Calculate total number of trading days in the backtest period."""
        if not self.start_date or not self.end_date:
            return 0
        return (self.end_date - self.start_date).days

    def expected_folds(self) -> int:
        """Calculate expected number of walk-forward folds."""
        if not self.walkforward or not self.start_date or not self.end_date:
            return 1

        total_days = self.total_days()
        holdout = self.walkforward.final_holdout_days if self.walkforward.enable_final_holdout else 0
        available_days = total_days - holdout - self.walkforward.initial_train_days

        if available_days <= 0:
            return 0

        return max(1, available_days // self.walkforward.step_days)


@dataclass
class DataFetchStatus:
    """Status of a data fetch operation."""

    success: bool
    symbols_requested: int = 0
    symbols_fetched: int = 0
    symbols_cached: int = 0
    api_calls_used: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def elapsed_minutes(self) -> float:
        """Elapsed time in minutes."""
        return self.elapsed_seconds / 60


@dataclass
class PeriodResult:
    """Result of a single backtest period."""

    start_date: date
    end_date: date
    is_train: bool = False
    is_test: bool = False

    # Returns
    total_return: Decimal = field(default_factory=lambda: Decimal('0'))
    total_return_pct: float = 0.0

    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    calmar_ratio: float = 0.0

    # Trade statistics
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    average_trade_pnl: Decimal = field(default_factory=lambda: Decimal('0'))

    # Execution costs
    total_slippage: Decimal = field(default_factory=lambda: Decimal('0'))
    total_commission: Decimal = field(default_factory=lambda: Decimal('0'))

    # Equity curve
    equity_curve: list[tuple[date, Decimal]] = field(default_factory=list)

    # Trade log
    trades: list[dict[str, object]] = field(default_factory=list)
