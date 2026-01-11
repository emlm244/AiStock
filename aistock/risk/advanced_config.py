"""Advanced risk management configuration dataclasses."""

from dataclasses import dataclass, field


@dataclass
class KellyCriterionConfig:
    """Configuration for Kelly Criterion position sizing.

    Uses win rate and avg win/loss from FSDEngine.symbol_performance
    to compute optimal bet size: K = W - (1-W)/R
    where W = win rate, R = avg_win / avg_loss

    Reference: Kelly (1956) "A New Interpretation of Information Rate"
    """

    enable: bool = False
    fraction: float = 0.5  # Half-Kelly (conservative) by default
    min_trades_required: int = 10  # Minimum trades before Kelly kicks in
    max_kelly_fraction: float = 0.25  # Cap at 25% of capital
    min_kelly_fraction: float = 0.01  # Floor at 1% of capital
    fallback_fraction: float = 0.05  # Use when insufficient data

    def validate(self) -> None:
        """Validate configuration parameters."""
        if not 0.0 < self.fraction <= 1.0:
            raise ValueError(f'fraction must be in (0, 1], got {self.fraction}')
        if self.min_trades_required < 1:
            raise ValueError(f'min_trades_required must be >= 1, got {self.min_trades_required}')
        if not 0.0 < self.max_kelly_fraction <= 1.0:
            raise ValueError(f'max_kelly_fraction must be in (0, 1], got {self.max_kelly_fraction}')
        if not 0.0 <= self.min_kelly_fraction < self.max_kelly_fraction:
            raise ValueError(
                f'min_kelly_fraction ({self.min_kelly_fraction}) must be < '
                f'max_kelly_fraction ({self.max_kelly_fraction})'
            )
        if not 0.0 < self.fallback_fraction <= 1.0:
            raise ValueError(f'fallback_fraction must be in (0, 1], got {self.fallback_fraction}')


@dataclass
class CorrelationLimitsConfig:
    """Configuration for correlation-based trade blocking.

    Computes rolling correlation between positions and blocks
    new trades when portfolio would become too correlated.
    """

    enable: bool = False
    max_correlation: float = 0.7  # Block when correlation > 70%
    lookback_bars: int = 50  # Bars for correlation calculation
    min_data_points: int = 20  # Minimum bars before computing correlation
    block_on_high_correlation: bool = True  # Block vs just warn

    def validate(self) -> None:
        """Validate configuration parameters."""
        if not 0.0 <= self.max_correlation <= 1.0:
            raise ValueError(f'max_correlation must be in [0, 1], got {self.max_correlation}')
        if self.lookback_bars < 10:
            raise ValueError(f'lookback_bars must be >= 10, got {self.lookback_bars}')
        if self.min_data_points < 2:
            raise ValueError(f'min_data_points must be >= 2, got {self.min_data_points}')
        if self.min_data_points > self.lookback_bars:
            raise ValueError(
                f'min_data_points ({self.min_data_points}) must be <= lookback_bars ({self.lookback_bars})'
            )


@dataclass
class RegimeDetectionConfig:
    """Configuration for market regime detection.

    Classifies market into 5 regimes based on RSI, trend, and volatility:
    - strong_bull: RSI > 70, positive 20-day return, low volatility
    - mild_bull: RSI 55-70, positive momentum
    - sideways: RSI 45-55, low momentum, normal volatility
    - mild_bear: RSI 30-45, negative momentum
    - strong_bear: RSI < 30, negative 20-day return, high volatility

    Position multipliers scale position sizes based on regime.
    """

    enable: bool = False
    rsi_strong_bull: float = 70.0
    rsi_mild_bull: float = 55.0
    rsi_mild_bear: float = 45.0
    rsi_strong_bear: float = 30.0
    trend_lookback_bars: int = 20
    volatility_lookback_bars: int = 20
    volatility_high_threshold: float = 0.025  # 2.5% daily std
    volatility_low_threshold: float = 0.010  # 1.0% daily std
    strong_trend_threshold: float = 0.05  # 5% return for strong trend

    # Position size multipliers per regime
    strong_bull_multiplier: float = 1.2
    mild_bull_multiplier: float = 1.0
    sideways_multiplier: float = 0.6
    mild_bear_multiplier: float = 0.4
    strong_bear_multiplier: float = 0.2

    def validate(self) -> None:
        """Validate configuration parameters."""
        if not (self.rsi_strong_bear < self.rsi_mild_bear < self.rsi_mild_bull < self.rsi_strong_bull):
            raise ValueError(
                'RSI thresholds must be monotonically increasing: '
                f'strong_bear ({self.rsi_strong_bear}) < mild_bear ({self.rsi_mild_bear}) < '
                f'mild_bull ({self.rsi_mild_bull}) < strong_bull ({self.rsi_strong_bull})'
            )
        if self.trend_lookback_bars < 1:
            raise ValueError(f'trend_lookback_bars must be >= 1, got {self.trend_lookback_bars}')
        if self.volatility_lookback_bars < 1:
            raise ValueError(f'volatility_lookback_bars must be >= 1, got {self.volatility_lookback_bars}')
        if self.volatility_low_threshold >= self.volatility_high_threshold:
            raise ValueError(
                f'volatility_low_threshold ({self.volatility_low_threshold}) must be < '
                f'volatility_high_threshold ({self.volatility_high_threshold})'
            )
        # Validate multipliers are positive
        for name, mult in [
            ('strong_bull', self.strong_bull_multiplier),
            ('mild_bull', self.mild_bull_multiplier),
            ('sideways', self.sideways_multiplier),
            ('mild_bear', self.mild_bear_multiplier),
            ('strong_bear', self.strong_bear_multiplier),
        ]:
            if mult <= 0:
                raise ValueError(f'{name}_multiplier must be positive, got {mult}')


@dataclass
class VolatilityScalingConfig:
    """Configuration for volatility-based position scaling.

    Uses VIX when available (from extract_state's vix_level),
    falls back to computed realized volatility.

    Scales position sizes inversely with volatility:
    - High volatility = smaller positions
    - Low volatility = larger positions
    """

    enable: bool = False
    target_volatility: float = 0.15  # Target 15% annualized vol
    max_scale_up: float = 2.0  # Max 2x position size in low vol
    max_scale_down: float = 0.25  # Min 0.25x in high vol
    vix_high_threshold: float = 30.0  # VIX above 30 = high vol
    vix_low_threshold: float = 15.0  # VIX below 15 = low vol
    vix_symbols: tuple[str, ...] = ('VIX', '^VIX', 'VIXY', 'VXX')
    use_realized_vol_fallback: bool = True
    realized_vol_lookback: int = 20

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.target_volatility <= 0:
            raise ValueError(f'target_volatility must be positive, got {self.target_volatility}')
        if self.max_scale_up < 1.0:
            raise ValueError(f'max_scale_up must be >= 1.0, got {self.max_scale_up}')
        if not 0.0 < self.max_scale_down <= 1.0:
            raise ValueError(f'max_scale_down must be in (0, 1], got {self.max_scale_down}')
        if self.vix_low_threshold >= self.vix_high_threshold:
            raise ValueError(
                f'vix_low_threshold ({self.vix_low_threshold}) must be < vix_high_threshold ({self.vix_high_threshold})'
            )
        if self.realized_vol_lookback < 2:
            raise ValueError(f'realized_vol_lookback must be >= 2, got {self.realized_vol_lookback}')


@dataclass
class AdvancedRiskConfig:
    """Composite config for all advanced risk features.

    Holds configuration for Kelly Criterion, correlation limits,
    regime detection, and volatility scaling.
    """

    kelly: KellyCriterionConfig = field(default_factory=KellyCriterionConfig)
    correlation: CorrelationLimitsConfig = field(default_factory=CorrelationLimitsConfig)
    regime: RegimeDetectionConfig = field(default_factory=RegimeDetectionConfig)
    volatility_scaling: VolatilityScalingConfig = field(default_factory=VolatilityScalingConfig)

    def validate(self) -> None:
        """Validate all sub-configurations."""
        self.kelly.validate()
        self.correlation.validate()
        self.regime.validate()
        self.volatility_scaling.validate()
