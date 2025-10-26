"""
Performance analytics helpers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class TradePerformance:
    total_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    expectancy: float


def compute_drawdown(equity_curve: Sequence[tuple[datetime, Decimal]]) -> Decimal:
    peak = Decimal("0")
    max_dd = Decimal("0")
    for _, equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak > 0:
            drawdown = (peak - equity) / peak
            if drawdown > max_dd:
                max_dd = drawdown
    return max_dd


def compute_returns(equity_curve: Sequence[tuple[datetime, Decimal]]) -> list[float]:
    returns: list[float] = []
    for (_, prev_equity), (_, current_equity) in zip(equity_curve, equity_curve[1:]):
        if prev_equity == 0:
            continue
        returns.append(float((current_equity - prev_equity) / prev_equity))
    return returns


def sharpe_ratio(returns: Sequence[float], risk_free_rate: float = 0.0) -> float:
    if not returns:
        return 0.0
    excess = [r - risk_free_rate for r in returns]
    mean = sum(excess) / len(excess)
    variance = sum((r - mean) ** 2 for r in excess) / len(excess) if len(excess) > 1 else 0.0
    std = math.sqrt(variance)
    if std == 0.0:
        return 0.0
    return mean / std * math.sqrt(252.0)


def sortino_ratio(returns: Sequence[float], risk_free_rate: float = 0.0) -> float:
    downside = [min(0.0, r - risk_free_rate) for r in returns]
    downside_sq = [d ** 2 for d in downside]
    if not downside_sq:
        return 0.0
    downside_dev = math.sqrt(sum(downside_sq) / len(downside_sq))
    if downside_dev == 0.0:
        return 0.0
    mean = sum(returns) / len(returns)
    return (mean - risk_free_rate) / downside_dev * math.sqrt(252.0)


def trade_performance(trade_pnls: Sequence[Decimal]) -> TradePerformance:
    if not trade_pnls:
        return TradePerformance(0, 0.0, 0.0, 0.0, 0.0)
    wins = [float(p) for p in trade_pnls if p > 0]
    losses = [float(p) for p in trade_pnls if p < 0]
    win_rate = len(wins) / len(trade_pnls)
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = (win_rate * average_win) + ((1 - win_rate) * average_loss)
    return TradePerformance(len(trade_pnls), win_rate, average_win, average_loss, expectancy)
