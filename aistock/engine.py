"""
Custom Trading Engine for AIStock Robot (FSD Mode).

This is our own custom trading engine that replaces BackTrader.
It provides a simple, focused engine specifically designed for FSD mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass
class Trade:
    """
    Record of an executed trade.
    """

    timestamp: datetime
    symbol: str
    quantity: Decimal
    price: Decimal
    realised_pnl: Decimal
    equity: Decimal
    order_id: str = ''
    strategy: str = 'FSD'


@dataclass
class BacktestResult:
    """
    Result of a backtest run.
    """

    total_return: Decimal
    max_drawdown: Decimal
    win_rate: float
    trades: list[Trade]
    metrics: dict[str, Any]
    equity_curve: list[tuple[datetime, float]]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'total_return': float(self.total_return),
            'max_drawdown': float(self.max_drawdown),
            'win_rate': self.win_rate,
            'num_trades': len(self.trades),
            'metrics': self.metrics,
        }


class TradingEngine:
    """
    Custom trading engine for executing FSD strategies.

    This engine:
    - Processes market data bars
    - Executes trades based on FSD decisions
    - Tracks portfolio state
    - Calculates performance metrics
    """

    def __init__(self, initial_cash: Decimal):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, Decimal] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[tuple[datetime, float]] = []

    def execute_trade(self, symbol: str, quantity: Decimal, price: Decimal, timestamp: datetime) -> Trade:
        """
        Execute a trade and update portfolio state.

        Args:
            symbol: Trading symbol
            quantity: Quantity to trade (positive = buy, negative = sell)
            price: Execution price
            timestamp: Trade timestamp

        Returns:
            Trade record
        """
        # Calculate cost
        cost = quantity * price

        # Update cash
        self.cash -= cost

        # Update position
        current_position = self.positions.get(symbol, Decimal('0'))
        new_position = current_position + quantity
        self.positions[symbol] = new_position

        # Calculate realized P&L (simplified)
        realised_pnl = Decimal('0')
        if (current_position > 0 and quantity < 0) or (current_position < 0 and quantity > 0):
            # Closing or reducing position - realize P&L
            closed_qty = min(abs(quantity), abs(current_position))
            realised_pnl = closed_qty * price if current_position > 0 else -closed_qty * price

        # Calculate current equity
        equity = self.calculate_equity({symbol: price})

        # Create trade record
        trade = Trade(
            timestamp=timestamp,
            symbol=symbol,
            quantity=quantity,
            price=price,
            realised_pnl=realised_pnl,
            equity=equity,
            order_id=f'T{len(self.trades) + 1:06d}',
            strategy='FSD',
        )

        self.trades.append(trade)
        self.equity_curve.append((timestamp, float(equity)))

        return trade

    def calculate_equity(self, current_prices: dict[str, Decimal]) -> Decimal:
        """
        Calculate current portfolio equity.

        Args:
            current_prices: Current market prices for all symbols

        Returns:
            Total equity value
        """
        equity = self.cash

        for symbol, quantity in self.positions.items():
            if symbol in current_prices:
                equity += quantity * current_prices[symbol]

        return equity

    def get_performance_metrics(self) -> dict[str, Any]:
        """
        Calculate performance metrics.

        Returns:
            Dictionary of performance metrics
        """
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'total_return': 0.0,
                'max_drawdown': 0.0,
            }

        # Calculate returns
        final_equity = float(self.equity_curve[-1][1]) if self.equity_curve else float(self.initial_cash)
        total_return = (final_equity - float(self.initial_cash)) / float(self.initial_cash)

        # Calculate win rate
        winning_trades = sum(1 for t in self.trades if t.realised_pnl > 0)
        win_rate = winning_trades / len(self.trades) if self.trades else 0.0

        # Calculate max drawdown
        peak = float(self.initial_cash)
        max_dd = 0.0

        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        return {
            'total_trades': len(self.trades),
            'win_rate': win_rate,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'final_equity': final_equity,
            'total_pnl': final_equity - float(self.initial_cash),
        }


__all__ = ['Trade', 'BacktestResult', 'TradingEngine']
