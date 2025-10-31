"""Configuration validator."""

from __future__ import annotations

import logging
from typing import Any


class ConfigValidator:
    """Validates configuration for common errors."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def validate(self, config: Any) -> bool:
        """Validate configuration.

        Returns:
            True if valid (may have warnings), False if errors found
        """
        self.warnings.clear()
        self.errors.clear()

        # Check FSD config
        if hasattr(config, 'fsd'):
            self._validate_fsd(config.fsd)

        # Check risk config
        if hasattr(config, 'risk'):
            self._validate_risk(config.risk)

        # Check capital
        if hasattr(config, 'initial_capital'):
            if config.initial_capital < 1000:
                self.warnings.append(f'Initial capital is low: {config.initial_capital}')

        # Check symbols
        if hasattr(config, 'symbols') and config.symbols:
            if len(config.symbols) > 20:
                self.warnings.append(f'Many symbols ({len(config.symbols)}), may impact performance')

        # Log results
        for warning in self.warnings:
            self.logger.warning(f'Config warning: {warning}')
        for error in self.errors:
            self.logger.error(f'Config error: {error}')

        return len(self.errors) == 0

    def _validate_fsd(self, fsd) -> None:
        """Validate FSD configuration."""
        if fsd.learning_rate > 0.01:
            self.warnings.append(f'High learning rate: {fsd.learning_rate} (may be unstable)')

        if fsd.exploration_rate < 0.05:
            self.warnings.append(f'Low exploration: {fsd.exploration_rate} (may not explore enough)')

        if fsd.min_confidence_threshold > 0.8:
            self.warnings.append(f'High confidence threshold: {fsd.min_confidence_threshold} (may trade rarely)')

    def _validate_risk(self, risk) -> None:
        """Validate risk configuration."""
        if risk.max_position_pct > 0.2:
            self.warnings.append(f'Large position size: {risk.max_position_pct} (high risk)')

        if risk.max_daily_loss_pct > 0.10:
            self.warnings.append(f'High daily loss limit: {risk.max_daily_loss_pct} (high risk)')
