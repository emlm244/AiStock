"""Unified trading configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import BrokerConfig, DataQualityConfig, ExecutionConfig, RiskLimits
from ..fsd import FSDConfig


@dataclass
class TradingConfig:
    """Unified trading configuration combining all aspects.

    Composition pattern: combines FSD, Risk, Execution, Data configs.
    """

    # Core components
    fsd: FSDConfig
    risk: RiskLimits
    execution: ExecutionConfig
    data_quality: DataQualityConfig

    # Optional components
    broker: BrokerConfig | None = None

    # Session settings
    initial_capital: float = 10000.0
    symbols: list[str] | None = None
    timeframes: list[str] | None = None

    # Professional features
    enable_professional_features: bool = True
    safeguard_config: dict[str, Any] | None = None

    # Risk overrides
    minimum_balance: float = 0.0
    minimum_balance_enabled: bool = True

    # Checkpointing
    checkpoint_dir: str = 'state'
    enable_checkpointing: bool = True
    restore_from_checkpoint: bool = False

    def validate(self) -> None:
        """Validate all configuration components."""
        self.fsd.validate()

        # Validate risk limits
        if not 0.0 < self.risk.max_position_pct <= 1.0:
            raise ValueError(f'Invalid max_position_pct: {self.risk.max_position_pct}')

        # Validate capital
        if self.initial_capital <= 0:
            raise ValueError(f'Initial capital must be positive: {self.initial_capital}')

        # Validate minimum balance
        if self.minimum_balance_enabled and self.minimum_balance < 0:
            raise ValueError(f'Minimum balance cannot be negative: {self.minimum_balance}')

        # Validate symbols
        if self.symbols is not None and not self.symbols:
            raise ValueError('Symbols list cannot be empty if provided')

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'fsd': {
                'learning_rate': self.fsd.learning_rate,
                'discount_factor': self.fsd.discount_factor,
                'exploration_rate': self.fsd.exploration_rate,
                'min_confidence_threshold': self.fsd.min_confidence_threshold,
            },
            'risk': {
                'max_position_pct': self.risk.max_position_pct,
                'max_daily_loss_pct': self.risk.max_daily_loss_pct,
                'max_drawdown_pct': self.risk.max_drawdown_pct,
            },
            'initial_capital': self.initial_capital,
            'symbols': self.symbols,
            'timeframes': self.timeframes,
            'enable_professional_features': self.enable_professional_features,
            'minimum_balance': self.minimum_balance,
            'minimum_balance_enabled': self.minimum_balance_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradingConfig:
        """Create from dictionary."""
        fsd_data = data.get('fsd', {})
        risk_data = data.get('risk', {})

        fsd_config = FSDConfig(
            learning_rate=fsd_data.get('learning_rate', 0.001),
            discount_factor=fsd_data.get('discount_factor', 0.95),
            exploration_rate=fsd_data.get('exploration_rate', 0.1),
            min_confidence_threshold=fsd_data.get('min_confidence_threshold', 0.6),
        )

        risk_config = RiskLimits(
            max_position_pct=risk_data.get('max_position_pct', 0.1),
            max_daily_loss_pct=risk_data.get('max_daily_loss_pct', 0.05),
            max_drawdown_pct=risk_data.get('max_drawdown_pct', 0.15),
        )

        # Note: Simplified - real implementation would handle all fields
        return cls(
            fsd=fsd_config,
            risk=risk_config,
            execution=ExecutionConfig(),
            data_quality=DataQualityConfig(),
            initial_capital=data.get('initial_capital', 10000.0),
            symbols=data.get('symbols'),
            timeframes=data.get('timeframes'),
            enable_professional_features=data.get('enable_professional_features', True),
            minimum_balance=data.get('minimum_balance', 0.0),
            minimum_balance_enabled=data.get('minimum_balance_enabled', True),
        )
