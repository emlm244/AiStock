"""
Analytics and reporting for trading performance.

Provides per-symbol stats, trade frequency analysis, drawdown tracking,
and CSV export functionality for transparency and monitoring.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass
class SymbolPerformance:
    """Per-symbol trading statistics."""

    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float  # Percentage
    total_pnl: Decimal
    avg_win: Decimal
    avg_loss: Decimal
    largest_win: Decimal
    largest_loss: Decimal
    expectancy: Decimal  # Average P&L per trade
    profit_factor: float  # Gross profit / Gross loss


@dataclass
class TimeframeStats:
    """Trade frequency by timeframe."""

    timeframe: str
    total_trades: int
    avg_trades_per_day: float
    total_pnl: Decimal
    win_rate: float


@dataclass
class DrawdownMetrics:
    """Drawdown analysis."""

    current_drawdown_pct: float
    max_drawdown_pct: float
    max_drawdown_duration_days: float
    current_drawdown_duration_days: float
    peak_equity: Decimal
    current_equity: Decimal


def calculate_symbol_performance(
    trade_log: list[dict[str, Any]], symbol: str
) -> SymbolPerformance | None:
    """
    Calculate per-symbol trading statistics.

    Args:
        trade_log: List of trade dictionaries with symbol, realised_pnl
        symbol: Symbol to analyze

    Returns:
        SymbolPerformance or None if no trades
    """
    symbol_trades = [t for t in trade_log if t.get('symbol') == symbol]

    if not symbol_trades:
        return None

    total_trades = len(symbol_trades)
    pnls = [Decimal(str(t['realised_pnl'])) for t in symbol_trades if 'realised_pnl' in t]

    if not pnls:
        return None

    winning_trades = [p for p in pnls if p > 0]
    losing_trades = [p for p in pnls if p < 0]

    total_pnl = sum(pnls, Decimal('0'))
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0.0

    avg_win = sum(winning_trades, Decimal('0')) / len(winning_trades) if winning_trades else Decimal('0')
    avg_loss = sum(losing_trades, Decimal('0')) / len(losing_trades) if losing_trades else Decimal('0')

    largest_win = max(winning_trades) if winning_trades else Decimal('0')
    largest_loss = min(losing_trades) if losing_trades else Decimal('0')

    expectancy = total_pnl / total_trades if total_trades > 0 else Decimal('0')

    gross_profit = sum(winning_trades, Decimal('0'))
    gross_loss = abs(sum(losing_trades, Decimal('0')))
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0

    return SymbolPerformance(
        symbol=symbol,
        total_trades=total_trades,
        winning_trades=len(winning_trades),
        losing_trades=len(losing_trades),
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_win=avg_win,
        avg_loss=avg_loss,
        largest_win=largest_win,
        largest_loss=largest_loss,
        expectancy=expectancy,
        profit_factor=profit_factor,
    )


def calculate_drawdown_metrics(equity_curve: list[tuple[datetime, Decimal]]) -> DrawdownMetrics | None:
    """
    Calculate drawdown metrics from equity curve.

    Args:
        equity_curve: List of (timestamp, equity) tuples

    Returns:
        DrawdownMetrics or None if insufficient data
    """
    if len(equity_curve) < 2:
        return None

    current_equity = equity_curve[-1][1]
    peak_equity = equity_curve[0][1]
    max_drawdown_pct = 0.0
    max_drawdown_duration_days = 0.0
    current_drawdown_duration_days = 0.0

    peak_timestamp = equity_curve[0][0]
    max_drawdown_start = equity_curve[0][0]
    max_drawdown_end = equity_curve[0][0]
    current_drawdown_start = equity_curve[0][0]

    for timestamp, equity in equity_curve:
        # Update peak
        if equity > peak_equity:
            peak_equity = equity
            peak_timestamp = timestamp
            current_drawdown_start = timestamp  # Reset current drawdown

        # Calculate drawdown from peak
        drawdown_pct = float((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0.0

        # Update max drawdown
        if drawdown_pct > max_drawdown_pct:
            max_drawdown_pct = drawdown_pct
            max_drawdown_start = peak_timestamp
            max_drawdown_end = timestamp

        # Update current drawdown duration
        if equity < peak_equity:
            current_drawdown_duration_days = (timestamp - current_drawdown_start).total_seconds() / 86400

    # Calculate max drawdown duration
    if max_drawdown_pct > 0:
        max_drawdown_duration_days = (max_drawdown_end - max_drawdown_start).total_seconds() / 86400

    # Current drawdown percentage
    current_drawdown_pct = float((peak_equity - current_equity) / peak_equity * 100) if peak_equity > 0 else 0.0

    return DrawdownMetrics(
        current_drawdown_pct=current_drawdown_pct,
        max_drawdown_pct=max_drawdown_pct,
        max_drawdown_duration_days=max_drawdown_duration_days,
        current_drawdown_duration_days=current_drawdown_duration_days,
        peak_equity=peak_equity,
        current_equity=current_equity,
    )


def export_symbol_performance_csv(
    trade_log: list[dict[str, Any]], symbols: list[str], output_path: str
) -> None:
    """
    Export per-symbol performance to CSV.

    Args:
        trade_log: List of trade dictionaries
        symbols: List of symbols to analyze
        output_path: Output CSV file path
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'symbol',
            'total_trades',
            'winning_trades',
            'losing_trades',
            'win_rate_pct',
            'total_pnl',
            'avg_win',
            'avg_loss',
            'largest_win',
            'largest_loss',
            'expectancy',
            'profit_factor',
        ])

        for symbol in symbols:
            perf = calculate_symbol_performance(trade_log, symbol)
            if perf:
                writer.writerow([
                    perf.symbol,
                    perf.total_trades,
                    perf.winning_trades,
                    perf.losing_trades,
                    round(perf.win_rate, 2),
                    float(perf.total_pnl),
                    float(perf.avg_win),
                    float(perf.avg_loss),
                    float(perf.largest_win),
                    float(perf.largest_loss),
                    float(perf.expectancy),
                    round(perf.profit_factor, 2),
                ])


def export_drawdown_csv(equity_curve: list[tuple[datetime, Decimal]], output_path: str) -> None:
    """
    Export drawdown analysis to CSV.

    Args:
        equity_curve: List of (timestamp, equity) tuples
        output_path: Output CSV file path
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    metrics = calculate_drawdown_metrics(equity_curve)
    if not metrics:
        return

    with output_file.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['metric', 'value'])
        writer.writerow(['current_drawdown_pct', round(metrics.current_drawdown_pct, 2)])
        writer.writerow(['max_drawdown_pct', round(metrics.max_drawdown_pct, 2)])
        writer.writerow(['max_drawdown_duration_days', round(metrics.max_drawdown_duration_days, 2)])
        writer.writerow(['current_drawdown_duration_days', round(metrics.current_drawdown_duration_days, 2)])
        writer.writerow(['peak_equity', float(metrics.peak_equity)])
        writer.writerow(['current_equity', float(metrics.current_equity)])


def generate_capital_sizing_report(
    current_capital: Decimal,
    target_monthly_return_pct: float,
    avg_monthly_return_pct: float | None = None,
) -> dict[str, Any]:
    """
    Generate capital sizing guidance based on target returns.

    Args:
        current_capital: Current trading capital
        target_monthly_return_pct: Desired monthly return percentage
        avg_monthly_return_pct: Observed average monthly return (optional)

    Returns:
        Dictionary with capital sizing recommendations
    """
    target_monthly_dollars = current_capital * Decimal(str(target_monthly_return_pct / 100))

    if avg_monthly_return_pct is not None and avg_monthly_return_pct > 0:
        # Calculate required capital to hit target
        required_capital = Decimal(str(target_monthly_return_pct / avg_monthly_return_pct)) * current_capital
        capital_gap = required_capital - current_capital
    else:
        # Conservative estimate: 1-2% monthly return
        conservative_return = 1.5  # 1.5% monthly
        required_capital = Decimal(str(target_monthly_return_pct / conservative_return)) * current_capital
        capital_gap = required_capital - current_capital

    return {
        'current_capital': float(current_capital),
        'target_monthly_return_pct': target_monthly_return_pct,
        'target_monthly_dollars': float(target_monthly_dollars),
        'avg_monthly_return_pct': avg_monthly_return_pct,
        'required_capital': float(required_capital),
        'capital_gap': float(capital_gap),
        'recommendation': (
            f'To achieve {target_monthly_return_pct}% monthly return '
            f'(${float(target_monthly_dollars):,.2f}/month), '
            f'you need ${float(required_capital):,.2f} in capital. '
            f'Current gap: ${float(capital_gap):,.2f}.'
        ),
    }
