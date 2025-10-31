"""Central state manager."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .state_snapshot import StateSnapshot

if TYPE_CHECKING:
    from ..interfaces.portfolio import PortfolioProtocol
    from ..interfaces.risk import RiskEngineProtocol


class StateManager:
    """Centralized state manager with ownership pattern.

    Components don't hold state directly - they get read-only snapshots.
    State manager owns all mutable state and coordinates updates.
    """

    def __init__(
        self,
        portfolio: PortfolioProtocol,
        risk_engine: RiskEngineProtocol,
    ):
        self.portfolio = portfolio
        self.risk_engine = risk_engine

        # Mutable state
        self._last_prices: dict[str, Decimal] = {}
        self._pending_orders: list[dict[str, Any]] = []
        self._session_start: datetime | None = None
        self._trade_count = 0

        # Thread safety
        self._lock = threading.Lock()

        self.logger = logging.getLogger(__name__)

    def get_snapshot(self) -> StateSnapshot:
        """Get immutable snapshot of current state."""
        with self._lock:
            positions = {}
            for symbol, pos in self.portfolio.snapshot_positions().items():
                positions[symbol] = {
                    'quantity': float(pos.quantity),
                    'avg_price': float(pos.average_price),
                }

            return StateSnapshot(
                timestamp=datetime.now(),
                cash=self.portfolio.get_cash(),
                equity=self.portfolio.total_equity(self._last_prices),
                positions=positions,
                daily_pnl=Decimal('0'),  # Would get from risk engine
                peak_equity=Decimal('0'),  # Would get from risk engine
                is_halted=self.risk_engine.is_halted(),
                halt_reason=self.risk_engine.halt_reason(),
                pending_orders=list(self._pending_orders),
                last_prices=dict(self._last_prices),
                trade_count=self._trade_count,
                session_start=self._session_start,
            )

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update last price for symbol."""
        with self._lock:
            self._last_prices[symbol] = price

    def add_pending_order(self, order: dict[str, Any]) -> None:
        """Add pending order."""
        with self._lock:
            self._pending_orders.append(order)

    def remove_pending_order(self, order_id: int) -> None:
        """Remove pending order."""
        with self._lock:
            self._pending_orders = [
                o for o in self._pending_orders if o.get('order_id') != order_id
            ]

    def increment_trade_count(self) -> None:
        """Increment trade count."""
        with self._lock:
            self._trade_count += 1

    def start_session(self) -> None:
        """Mark session start."""
        with self._lock:
            self._session_start = datetime.now()
            self._trade_count = 0

    def reset_session(self) -> None:
        """Reset session state."""
        with self._lock:
            self._session_start = None
            self._trade_count = 0
            self._pending_orders.clear()
