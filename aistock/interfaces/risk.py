"""Risk engine protocol interface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol


class RiskEngineProtocol(Protocol):
    """Protocol defining the risk engine interface.

    This allows swapping risk implementations for different strategies
    or testing with mock risk engines.
    """

    def check_pre_trade(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        equity: Decimal,
        last_prices: dict[str, Decimal],
    ) -> None:
        """Check if trade passes risk checks.

        Raises:
            RiskViolation: If trade violates risk limits
        """
        ...

    def register_trade(
        self,
        realised_pnl: Decimal,
        commission: Decimal,
        timestamp: datetime,
        equity: Decimal,
        last_prices: dict[str, Decimal],
    ) -> None:
        """Register a completed trade."""
        ...

    def record_order_submission(self, timestamp: datetime) -> None:
        """Record order submission for rate limiting."""
        ...

    def is_halted(self) -> bool:
        """Check if trading is halted."""
        ...

    def halt(self, reason: str) -> None:
        """Halt trading with a reason."""
        ...

    def halt_reason(self) -> str | None:
        """Get halt reason if halted."""
        ...

    def reset_daily(self, timestamp: datetime) -> None:
        """Reset daily counters."""
        ...
