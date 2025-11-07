"""Capital management strategies for fixed-capital and profit-taking trading.

This module provides strategies for managing trading capital, including:
- Fixed capital with profit withdrawal
- Compounding strategies
- Capital protection policies
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TypedDict

from .portfolio import Portfolio


class WithdrawalStats(TypedDict):
    """Statistics for profit withdrawal strategy."""

    total_withdrawn: float
    target_capital: float
    withdrawal_threshold: float
    last_withdrawal: str | None
    enabled: bool


@dataclass
class CapitalManagementConfig:
    """Configuration for capital management strategies."""

    target_capital: Decimal  # Target trading capital to maintain
    withdrawal_threshold: Decimal  # Min profit before withdrawal
    withdrawal_frequency: str = 'daily'  # daily, weekly, monthly
    enabled: bool = True


class ProfitWithdrawalStrategy:
    """
    Fixed-capital trading strategy with automatic profit withdrawal.

    This strategy maintains a fixed trading capital by withdrawing profits
    that exceed the target capital plus a threshold. This prevents position
    sizes from growing indefinitely and locks in gains.

    Example:
        >>> config = CapitalManagementConfig(
        ...     target_capital=Decimal('100000'),
        ...     withdrawal_threshold=Decimal('5000'),
        ...     withdrawal_frequency='daily'
        ... )
        >>> strategy = ProfitWithdrawalStrategy(config)
        >>> withdrawn = strategy.check_and_withdraw(portfolio, last_prices)
    """

    def __init__(self, config: CapitalManagementConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.last_withdrawal: datetime | None = None
        self.total_withdrawn = Decimal('0')

    def check_and_withdraw(self, portfolio: Portfolio, last_prices: dict[str, Decimal]) -> Decimal:
        """
        Check if profits should be withdrawn and execute withdrawal.

        Args:
            portfolio: Portfolio instance to manage
            last_prices: Current market prices for equity calculation

        Returns:
            Amount withdrawn (0 if no withdrawal)

        Example:
            >>> # Portfolio has $110k equity with $100k target
            >>> withdrawn = strategy.check_and_withdraw(portfolio, prices)
            >>> # Returns $10k if above threshold
        """
        if not self.config.enabled:
            return Decimal('0')

        # Calculate current equity
        equity = portfolio.get_equity(last_prices)

        # Calculate excess over target
        excess = equity - self.config.target_capital

        # Only withdraw if excess exceeds threshold
        if excess < self.config.withdrawal_threshold:
            self.logger.debug(
                f'No withdrawal: excess ${excess:.2f} below threshold ${self.config.withdrawal_threshold:.2f}'
            )
            return Decimal('0')

        # Check withdrawal frequency
        if not self._should_withdraw_now():
            self.logger.debug('Withdrawal frequency not met, skipping')
            return Decimal('0')

        # Calculate safe withdrawal amount (leave some buffer)
        # Only withdraw from cash, not tied up in positions
        available_cash = portfolio.get_cash()
        withdrawal_amount = min(excess, available_cash)

        if withdrawal_amount <= 0:
            self.logger.warning(
                f'Cannot withdraw ${excess:.2f}: only ${available_cash:.2f} cash available '
                f'(rest tied up in positions)'
            )
            return Decimal('0')

        # Execute withdrawal
        try:
            portfolio.withdraw_cash(withdrawal_amount, reason='profit_taking_automated')
            self.last_withdrawal = datetime.now(timezone.utc)
            self.total_withdrawn += withdrawal_amount

            self.logger.info(
                f'Profit withdrawal executed: ${withdrawal_amount:.2f} '
                f'(total withdrawn: ${self.total_withdrawn:.2f})'
            )

            return withdrawal_amount

        except ValueError as e:
            self.logger.error(f'Withdrawal failed: {e}')
            return Decimal('0')

    def _should_withdraw_now(self) -> bool:
        """Check if withdrawal should occur based on frequency setting."""
        if self.last_withdrawal is None:
            return True  # First withdrawal

        now = datetime.now(timezone.utc)
        time_since_last = now - self.last_withdrawal

        if self.config.withdrawal_frequency == 'daily':
            return time_since_last.days >= 1
        elif self.config.withdrawal_frequency == 'weekly':
            return time_since_last.days >= 7
        elif self.config.withdrawal_frequency == 'monthly':
            return time_since_last.days >= 30
        else:
            self.logger.warning(f'Unknown frequency: {self.config.withdrawal_frequency}, defaulting to daily')
            return time_since_last.days >= 1

    def get_stats(self) -> WithdrawalStats:
        """Get withdrawal statistics.

        Returns:
            Dictionary with withdrawal stats including total withdrawn,
            target capital, threshold, last withdrawal timestamp, and enabled status.
        """
        return {
            'total_withdrawn': float(self.total_withdrawn),
            'target_capital': float(self.config.target_capital),
            'withdrawal_threshold': float(self.config.withdrawal_threshold),
            'last_withdrawal': self.last_withdrawal.isoformat() if self.last_withdrawal else None,
            'enabled': self.config.enabled,
        }


class CompoundingStrategy:
    """
    Compounding strategy that reinvests all profits.

    This is the default behavior - no withdrawals occur.
    Useful for maximum growth but increases risk over time.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def check_and_withdraw(self, portfolio: Portfolio, last_prices: dict[str, Decimal]) -> Decimal:
        """No-op for compounding strategy."""
        return Decimal('0')

    def get_stats(self) -> dict[str, str]:
        """Get strategy stats."""
        return {'strategy': 'compounding', 'withdrawals': 'disabled'}
