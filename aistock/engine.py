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

from .performance import calculate_realized_pnl


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

    def __post_init__(self) -> None:
        """Validate timestamp includes timezone info for downstream audit consistency."""
        if self.timestamp.tzinfo is None or self.timestamp.tzinfo.utcoffset(self.timestamp) is None:
            raise ValueError('Trade timestamp must be timezone-aware')


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
        self.cost_basis: dict[str, Decimal] = {}  # Average entry price per symbol
        self.last_known_prices: dict[str, Decimal] = {}  # Track last price for equity calc
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

        # Get current position and cost basis
        current_position = self.positions.get(symbol, Decimal('0'))
        current_basis = self.cost_basis.get(symbol, Decimal('0'))

        # Calculate realized P&L using shared helper to keep logic consistent with Portfolio.
        realised_pnl = calculate_realized_pnl(
            position_quantity=current_position,
            average_price=current_basis,
            fill_quantity=quantity,
            fill_price=price,
        )

        # Update position
        new_position = current_position + quantity

        # Update cost basis
        if new_position == 0:
            # Fully closed - remove cost basis
            if symbol in self.cost_basis:
                del self.cost_basis[symbol]
        elif (current_position > 0 and new_position < 0) or (current_position < 0 and new_position > 0):
            # REVERSAL: position crossed zero, reset cost basis for new direction
            # CHECK THIS BEFORE magnitude comparison to catch reversals that also increase abs(position)
            self.cost_basis[symbol] = price
        elif abs(new_position) > abs(current_position):
            # Opening or adding to position - update weighted average basis
            if current_position == 0:
                # Opening new position
                self.cost_basis[symbol] = price
            else:
                # Adding to existing position - weighted average
                added_qty = abs(quantity)
                total_qty = abs(current_position) + added_qty

                # CRITICAL FIX: Guard against division by zero
                if total_qty == 0:
                    # Edge case: both quantities are zero (shouldn't happen but defensive)
                    self.cost_basis[symbol] = price
                else:
                    weighted_basis = (abs(current_position) * current_basis + added_qty * price) / total_qty
                    self.cost_basis[symbol] = weighted_basis
        # else: reducing position - cost basis stays the same

        # Track last known price for this symbol
        self.last_known_prices[symbol] = price

        self.positions[symbol] = new_position

        # Calculate current equity using all last known prices
        equity = self.calculate_equity(self.last_known_prices)

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

        Raises:
            ValueError: If current_prices missing required symbol
        """
        equity = self.cash

        for symbol, quantity in self.positions.items():
            # CRITICAL FIX: Validate that price exists for all open positions
            if symbol not in current_prices:
                raise ValueError(
                    f'Missing price for symbol {symbol} (position: {quantity}). '
                    f'Available prices: {list(current_prices.keys())}'
                )
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
