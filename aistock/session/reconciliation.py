"""Position reconciliation with broker."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..interfaces.broker import BrokerProtocol
    from ..interfaces.portfolio import PortfolioProtocol
    from ..interfaces.risk import RiskEngineProtocol


class PositionReconciler:
    """Reconciles portfolio positions with broker truth.

    Responsibilities:
    - Periodic position verification
    - Mismatch detection and logging
    - Auto-halt on critical mismatches
    """

    def __init__(
        self,
        portfolio: PortfolioProtocol,
        broker: BrokerProtocol,
        risk_engine: RiskEngineProtocol,
        interval_minutes: int = 60,
    ):
        self.portfolio = portfolio
        self.broker = broker
        self.risk_engine = risk_engine
        self.interval = timedelta(minutes=interval_minutes)

        self._last_reconciliation: datetime | None = None
        self._alerts: list[dict] = []

        self.logger = logging.getLogger(__name__)

    def should_reconcile(self, current_time: datetime) -> bool:
        """Check if it's time for reconciliation."""
        if self._last_reconciliation is None:
            return True

        current_utc = current_time if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)
        last_utc = (
            self._last_reconciliation
            if self._last_reconciliation.tzinfo
            else self._last_reconciliation.replace(tzinfo=timezone.utc)
        )

        if current_utc <= last_utc:
            return False

        return current_utc - last_utc >= self.interval

    def reconcile(self, as_of: datetime) -> None:
        """Reconcile positions and halt if critical mismatch."""
        try:
            as_of_utc = as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)

            broker_positions = self.broker.get_positions()
            portfolio_positions = self.portfolio.snapshot_positions()

            internal_map = {
                sym: (float(pos.quantity), float(pos.average_price)) for sym, pos in portfolio_positions.items()
            }

            mismatches = []

            # Check internal vs broker
            for symbol, (internal_qty, _) in internal_map.items():
                broker_qty, _ = broker_positions.get(symbol, (0.0, 0.0))
                if abs(internal_qty - broker_qty) > 0.001:
                    mismatches.append(
                        {
                            'symbol': symbol,
                            'internal_qty': internal_qty,
                            'broker_qty': broker_qty,
                            'delta': internal_qty - broker_qty,
                        }
                    )

            # Check broker positions not in internal
            for symbol, (broker_qty, _) in broker_positions.items():
                if symbol not in internal_map and abs(broker_qty) > 0.001:
                    mismatches.append(
                        {
                            'symbol': symbol,
                            'internal_qty': 0.0,
                            'broker_qty': broker_qty,
                            'delta': -broker_qty,
                        }
                    )

            if mismatches:
                # Check for critical mismatches (>=10%)
                critical = []
                for m in mismatches:
                    broker_qty = m['broker_qty']
                    delta = abs(m['delta'])
                    pct_diff = (delta / abs(broker_qty)) * 100 if broker_qty != 0 else 100.0
                    if pct_diff >= 10.0:
                        critical.append({**m, 'pct_diff': pct_diff})

                if critical:
                    # CRITICAL: Halt trading
                    self.logger.error(f'Critical position mismatch: {len(critical)} positions >=10% off')
                    self.risk_engine.halt(f'Critical position mismatch: {len(critical)} positions')
                else:
                    # Minor mismatches
                    self.logger.warning(f'Position mismatch: {len(mismatches)} positions differ')

                self._alerts.extend(mismatches)

            else:
                self.logger.info(f'Reconciliation OK: {len(internal_map)} positions verified')

            self._last_reconciliation = as_of_utc

        except Exception as exc:
            self.logger.error(f'Reconciliation failed: {exc}')

    def get_alerts(self, limit: int = 10) -> list[dict]:
        """Get recent reconciliation alerts."""
        return self._alerts[-limit:]
