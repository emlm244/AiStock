"""Position management and reconciliation service."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..interfaces.broker import BrokerProtocol
    from ..interfaces.portfolio import PortfolioProtocol


class PositionService:
    """Position management and reconciliation service."""

    def __init__(self, portfolio: PortfolioProtocol, broker: BrokerProtocol):
        self.portfolio = portfolio
        self.broker = broker

        self.logger = logging.getLogger(__name__)

    def get_positions(self) -> list[dict[str, Any]]:
        """Get all portfolio positions with current prices."""
        positions = []

        for symbol, pos in self.portfolio.snapshot_positions().items():
            positions.append({
                'symbol': symbol,
                'quantity': float(pos.quantity),
                'avg_price': float(pos.average_price),
                'last_update': pos.last_update_utc,
            })

        return positions

    def get_position(self, symbol: str) -> dict[str, Any]:
        """Get single position details."""
        pos = self.portfolio.position(symbol)

        return {
            'symbol': symbol,
            'quantity': float(pos.quantity),
            'avg_price': float(pos.average_price),
            'last_update': pos.last_update_utc,
        }

    def reconcile_with_broker(self) -> dict[str, Any]:
        """Reconcile portfolio positions with broker.

        Returns:
            Dict with 'mismatches', 'in_sync'
        """
        try:
            broker_positions = self.broker.get_positions()
            portfolio_positions = self.portfolio.snapshot_positions()

            mismatches = []

            # Check portfolio vs broker
            for symbol, pos in portfolio_positions.items():
                internal_qty = float(pos.quantity)
                broker_qty, _ = broker_positions.get(symbol, (0.0, 0.0))

                if abs(internal_qty - broker_qty) > 0.001:
                    mismatches.append({
                        'symbol': symbol,
                        'portfolio_qty': internal_qty,
                        'broker_qty': broker_qty,
                        'delta': internal_qty - broker_qty,
                    })

            # Check broker positions not in portfolio
            for symbol, (broker_qty, _) in broker_positions.items():
                if symbol not in portfolio_positions and abs(broker_qty) > 0.001:
                    mismatches.append({
                        'symbol': symbol,
                        'portfolio_qty': 0.0,
                        'broker_qty': broker_qty,
                        'delta': -broker_qty,
                    })

            self.logger.info(f'Reconciliation: {len(mismatches)} mismatches')

            return {
                'in_sync': len(mismatches) == 0,
                'mismatches': mismatches,
                'portfolio_position_count': len(portfolio_positions),
                'broker_position_count': len(broker_positions),
            }

        except Exception as exc:
            self.logger.error(f'Reconciliation failed: {exc}')
            return {
                'in_sync': False,
                'error': str(exc),
            }

    def get_exposure_summary(self, last_prices: dict[str, Decimal]) -> dict[str, Any]:
        """Get portfolio exposure summary."""
        total_long = Decimal('0')
        total_short = Decimal('0')
        positions_snapshot = self.portfolio.snapshot_positions()

        for symbol, pos in positions_snapshot.items():
            price = last_prices.get(symbol, pos.average_price)
            notional = abs(pos.quantity) * price

            if pos.quantity > 0:
                total_long += notional
            elif pos.quantity < 0:
                total_short += notional

        return {
            'total_long': float(total_long),
            'total_short': float(total_short),
            'net_exposure': float(total_long - total_short),
            'gross_exposure': float(total_long + total_short),
        }
