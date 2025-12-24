"""
Performance metrics calculation.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


def calculate_realized_pnl(
    position_quantity: Decimal,
    average_price: Decimal,
    fill_quantity: Decimal,
    fill_price: Decimal,
) -> Decimal:
    """
    Calculate realized P&L for a fill given the current position state.

    Args:
        position_quantity: Position size **before** applying the fill (signed).
        average_price: Volume-weighted average entry price of the open position.
        fill_quantity: Filled quantity (signed, positive=buy, negative=sell).
        fill_price: Execution price of the fill.

    Returns:
        Realized P&L contributed by this fill. Returns Decimal('0') when the
        fill increases exposure or the existing position is flat.
    """
    zero = Decimal('0')

    if fill_quantity == zero or position_quantity == zero:
        return zero

    # Only generate P&L when the fill reduces or closes the current exposure.
    is_closing = (position_quantity > zero and fill_quantity < zero) or (
        position_quantity < zero and fill_quantity > zero
    )
    if not is_closing:
        return zero

    closing_quantity = min(abs(fill_quantity), abs(position_quantity))

    if closing_quantity == zero:
        return zero

    if position_quantity > zero:
        # Closing long position.
        return (fill_price - average_price) * closing_quantity

    # Closing short position.
    return (average_price - fill_price) * closing_quantity


@dataclass
class TradePerformance:
    """Trade performance statistics."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    expectancy: float
    average_win: float
    average_loss: float
    profit_factor: float


def compute_returns(equity_curve: list[tuple[datetime, Decimal]]) -> list[float]:
    """
    Compute returns from equity curve.

    Args:
        equity_curve: List of (timestamp, equity) tuples

    Returns:
        List of percentage returns
    """
    if len(equity_curve) < 2:
        return []

    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev_equity = float(equity_curve[i - 1][1])
        curr_equity = float(equity_curve[i][1])

        if prev_equity > 0:
            ret = (curr_equity - prev_equity) / prev_equity
            returns.append(ret)

    return returns


def sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """
    Calculate annualized Sharpe ratio.

    Args:
        returns: List of returns
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods in a year (252 for daily)

    Returns:
        Annualized Sharpe ratio
    """
    if not returns or len(returns) < 2:
        return 0.0

    mean_return = statistics.mean(returns)
    std_return = statistics.stdev(returns)

    if std_return == 0:
        return 0.0

    # Annualize
    annual_mean = mean_return * periods_per_year
    annual_std = std_return * math.sqrt(periods_per_year)

    return (annual_mean - risk_free_rate) / annual_std


def sortino_ratio(returns: list[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """
    Calculate annualized Sortino ratio (uses downside deviation).

    Args:
        returns: List of returns
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods in a year

    Returns:
        Annualized Sortino ratio
    """
    if not returns or len(returns) < 2:
        return 0.0

    mean_return = statistics.mean(returns)

    # Calculate downside deviation (only negative returns)
    negative_returns = [ret for ret in returns if ret < 0]

    if len(negative_returns) == 0:
        return float('inf')  # No downside

    if len(negative_returns) < 2:
        return 0.0
    downside_std = statistics.stdev(negative_returns)

    if downside_std == 0:
        return 0.0

    # Annualize
    annual_mean = mean_return * periods_per_year
    annual_downside_std = downside_std * math.sqrt(periods_per_year)

    return (annual_mean - risk_free_rate) / annual_downside_std


def compute_drawdown(equity_curve: list[tuple[datetime, Decimal]]) -> Decimal:
    """
    Compute maximum drawdown from equity curve.

    Args:
        equity_curve: List of (timestamp, equity) tuples

    Returns:
        Maximum drawdown as Decimal (positive number)
    """
    if len(equity_curve) < 2:
        return Decimal('0')

    equity_values = [float(eq[1]) for eq in equity_curve]
    peak = equity_values[0]
    max_drawdown = 0.0
    for equity in equity_values:
        if equity > peak:
            peak = equity
        if peak <= 0:
            continue
        drawdown = (peak - equity) / peak
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    max_dd = max_drawdown
    return Decimal(str(max_dd))


def trade_performance(trade_pnls: list[Decimal]) -> TradePerformance:
    """
    Calculate trade performance statistics.

    Args:
        trade_pnls: List of realized P&L values

    Returns:
        TradePerformance object with statistics
    """
    if not trade_pnls:
        return TradePerformance(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            expectancy=0.0,
            average_win=0.0,
            average_loss=0.0,
            profit_factor=0.0,
        )

    total_trades = len(trade_pnls)
    winning_trades = sum(1 for pnl in trade_pnls if pnl > 0)
    losing_trades = sum(1 for pnl in trade_pnls if pnl < 0)

    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    wins = [float(pnl) for pnl in trade_pnls if pnl > 0]
    losses = [float(pnl) for pnl in trade_pnls if pnl < 0]

    average_win = statistics.mean(wins) if wins else 0.0
    average_loss = statistics.mean(losses) if losses else 0.0

    total_wins = sum(wins)
    total_losses = abs(sum(losses))

    profit_factor = total_wins / total_losses if total_losses > 0 else 0.0

    expectancy = float((win_rate * average_win) + ((1 - win_rate) * average_loss))

    return TradePerformance(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        expectancy=expectancy,
        average_win=average_win,
        average_loss=average_loss,
        profit_factor=profit_factor,
    )
