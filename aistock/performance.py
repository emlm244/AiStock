"""
Performance metrics calculation.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Tuple
import numpy as np


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


def compute_returns(equity_curve: List[Tuple[datetime, Decimal]]) -> List[float]:
    """
    Compute returns from equity curve.
    
    Args:
        equity_curve: List of (timestamp, equity) tuples
    
    Returns:
        List of percentage returns
    """
    if len(equity_curve) < 2:
        return []
    
    returns = []
    for i in range(1, len(equity_curve)):
        prev_equity = float(equity_curve[i-1][1])
        curr_equity = float(equity_curve[i][1])
        
        if prev_equity > 0:
            ret = (curr_equity - prev_equity) / prev_equity
            returns.append(ret)
    
    return returns


def sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
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
    
    returns_array = np.array(returns)
    mean_return = np.mean(returns_array)
    std_return = np.std(returns_array, ddof=1)
    
    if std_return == 0:
        return 0.0
    
    # Annualize
    annual_mean = mean_return * periods_per_year
    annual_std = std_return * np.sqrt(periods_per_year)
    
    return (annual_mean - risk_free_rate) / annual_std


def sortino_ratio(returns: List[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
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
    
    returns_array = np.array(returns)
    mean_return = np.mean(returns_array)
    
    # Calculate downside deviation (only negative returns)
    negative_returns = returns_array[returns_array < 0]
    
    if len(negative_returns) == 0:
        return float('inf')  # No downside
    
    downside_std = np.std(negative_returns, ddof=1)
    
    if downside_std == 0:
        return 0.0
    
    # Annualize
    annual_mean = mean_return * periods_per_year
    annual_downside_std = downside_std * np.sqrt(periods_per_year)
    
    return (annual_mean - risk_free_rate) / annual_downside_std


def compute_drawdown(equity_curve: List[Tuple[datetime, Decimal]]) -> Decimal:
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
    running_max = np.maximum.accumulate(equity_values)
    drawdowns = (equity_values - running_max) / running_max
    
    max_dd = abs(np.min(drawdowns))
    return Decimal(str(max_dd))


def trade_performance(trade_pnls: List[Decimal]) -> TradePerformance:
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
    
    average_win = np.mean(wins) if wins else 0.0
    average_loss = np.mean(losses) if losses else 0.0
    
    total_wins = sum(wins)
    total_losses = abs(sum(losses))
    
    profit_factor = total_wins / total_losses if total_losses > 0 else 0.0
    
    expectancy = (win_rate * average_win) + ((1 - win_rate) * average_loss)
    
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
