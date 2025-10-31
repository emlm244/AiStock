"""High-level trading service."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..interfaces.broker import BrokerProtocol
    from ..interfaces.decision import DecisionEngineProtocol
    from ..interfaces.portfolio import PortfolioProtocol
    from ..interfaces.risk import RiskEngineProtocol


class TradingService:
    """High-level trading operations service.

    Encapsulates the complete trading workflow from decision to execution.
    """

    def __init__(
        self,
        portfolio: PortfolioProtocol,
        risk_engine: RiskEngineProtocol,
        decision_engine: DecisionEngineProtocol,
        broker: BrokerProtocol,
    ):
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.decision_engine = decision_engine
        self.broker = broker

        self.logger = logging.getLogger(__name__)

    def evaluate_and_execute(
        self,
        symbol: str,
        market_data: dict[str, Any],
        timestamp: datetime,
    ) -> dict[str, Any]:
        """Evaluate trading opportunity and execute if appropriate.

        Args:
            symbol: Trading symbol
            market_data: Market data dict with 'bars' and 'last_prices'
            timestamp: Current timestamp

        Returns:
            dict with 'executed', 'order_id', 'reason'
        """
        bars = market_data.get('bars', [])
        last_prices = market_data.get('last_prices', {})

        if not bars:
            return {'executed': False, 'reason': 'no_market_data'}

        # Get decision
        decision = self.decision_engine.evaluate_opportunity(symbol, bars, last_prices)

        if not decision.get('should_trade'):
            return {
                'executed': False,
                'reason': decision.get('reason', 'no_trade_signal'),
                'confidence': decision.get('confidence', 0.0),
            }

        # Execute trade
        result = self._execute_decision(symbol, decision, bars, last_prices, timestamp)
        return result

    def _execute_decision(
        self,
        symbol: str,
        decision: dict[str, Any],
        bars: list[Any],
        last_prices: dict[str, Decimal],
        timestamp: datetime,
    ) -> dict[str, Any]:
        """Execute a trading decision."""
        action = decision.get('action', {})
        if not action:
            return {'executed': False, 'reason': 'no_action'}

        # Calculate order details
        size_fraction = Decimal(str(action.get('size_fraction', 0.0)))
        if size_fraction <= 0:
            return {'executed': False, 'reason': 'invalid_size'}

        equity = self.portfolio.total_equity(last_prices)
        current_price = bars[-1].close
        target_notional = Decimal(str(equity)) * size_fraction

        signal = int(action.get('signal', 0))
        if signal == 0:
            return {'executed': False, 'reason': 'no_signal'}

        # Calculate delta
        desired_qty = target_notional / current_price
        current_pos = self.portfolio.position(symbol)
        delta = desired_qty if signal > 0 else -desired_qty
        delta -= current_pos.quantity

        if abs(delta) < Decimal('0.00001'):
            return {'executed': False, 'reason': 'quantity_too_small'}

        # Risk check
        try:
            self.risk_engine.check_pre_trade(
                symbol, delta, current_price, Decimal(str(equity)), last_prices
            )
        except Exception as exc:
            return {'executed': False, 'reason': f'risk_violation: {exc}'}

        # Submit order (actual implementation would use OrderService)
        try:
            # This is simplified - real implementation uses OrderService
            self.logger.info(f'Would execute: {symbol} {float(delta)} @ {float(current_price)}')
            return {
                'executed': True,
                'order_id': None,  # Would get from broker
                'symbol': symbol,
                'quantity': float(delta),
                'price': float(current_price),
                'confidence': decision.get('confidence', 0.0),
            }
        except Exception as exc:
            return {'executed': False, 'reason': f'execution_error: {exc}'}

    def get_portfolio_summary(self, last_prices: dict[str, Decimal]) -> dict[str, Any]:
        """Get portfolio summary."""
        positions = []
        for symbol, pos in self.portfolio.snapshot_positions().items():
            positions.append({
                'symbol': symbol,
                'quantity': float(pos.quantity),
                'avg_price': float(pos.average_price),
                'current_price': float(last_prices.get(symbol, pos.average_price)),
                'unrealized_pnl': float(
                    (last_prices.get(symbol, pos.average_price) - pos.average_price) * pos.quantity
                ),
            })

        return {
            'cash': float(self.portfolio.get_cash()),
            'equity': float(self.portfolio.total_equity(last_prices)),
            'positions': positions,
            'position_count': self.portfolio.position_count(),
            'is_halted': self.risk_engine.is_halted(),
            'halt_reason': self.risk_engine.halt_reason(),
        }
