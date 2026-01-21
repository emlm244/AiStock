"""
Backtest report generation.

Generates comprehensive reports from backtest results including:
- Summary metrics
- Walk-forward analysis
- Equity curves
- Trade statistics
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from .config import TradeRecord

logger = logging.getLogger(__name__)

_DEFAULT_DECIMAL = Decimal('0')


def _safe_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return _DEFAULT_DECIMAL


def _extract_returns(equity_curve: list[tuple[datetime, Decimal]] | list[tuple[object, Decimal]]) -> list[float]:
    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev_equity = float(equity_curve[i - 1][1])
        current_equity = float(equity_curve[i][1])
        if prev_equity:
            returns.append((current_equity - prev_equity) / prev_equity)
    return returns


def _calculate_var_cvar(returns: list[float], confidence: float = 0.95) -> tuple[Decimal, Decimal]:
    if not returns:
        return (_DEFAULT_DECIMAL, _DEFAULT_DECIMAL)

    sorted_returns = sorted(returns)
    index = max(0, min(len(sorted_returns) - 1, int((1 - confidence) * len(sorted_returns))))
    var_return = sorted_returns[index]
    if var_return >= 0:
        return (_DEFAULT_DECIMAL, _DEFAULT_DECIMAL)

    tail = [r for r in sorted_returns if r <= var_return]
    cvar_return = sum(tail) / len(tail) if tail else var_return
    return (_safe_decimal(abs(var_return)), _safe_decimal(abs(cvar_return)))


def _calculate_max_drawdown(equity_curve: list[tuple[object, Decimal]]) -> Decimal:
    peak = _DEFAULT_DECIMAL
    max_drawdown = _DEFAULT_DECIMAL
    for _, equity_value in equity_curve:
        equity = _safe_decimal(equity_value)
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _trade_pnls(trades: list[TradeRecord]) -> list[Decimal]:
    pnls: list[Decimal] = []
    for trade in trades:
        pnl = trade.get('pnl')
        if pnl is None:
            continue
        pnls.append(_safe_decimal(pnl))
    return pnls


def _calculate_trade_stats(trades: list[TradeRecord]) -> TradeStats:
    pnls = _trade_pnls(trades)
    if not pnls:
        return TradeStats(
            profit_factor=0.0,
            average_trade_pnl=_DEFAULT_DECIMAL,
            average_win=_DEFAULT_DECIMAL,
            average_loss=_DEFAULT_DECIMAL,
            largest_win=_DEFAULT_DECIMAL,
            largest_loss=_DEFAULT_DECIMAL,
        )

    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    total_wins = sum(wins, _DEFAULT_DECIMAL)
    total_losses = sum(losses, _DEFAULT_DECIMAL)

    if total_losses < 0:
        profit_factor = float(total_wins / abs(total_losses))
    elif total_wins > 0:
        profit_factor = float('inf')
    else:
        profit_factor = 0.0

    return TradeStats(
        profit_factor=profit_factor,
        average_trade_pnl=sum(pnls, _DEFAULT_DECIMAL) / Decimal(str(len(pnls))),
        average_win=sum(wins, _DEFAULT_DECIMAL) / Decimal(str(len(wins))) if wins else _DEFAULT_DECIMAL,
        average_loss=sum(losses, _DEFAULT_DECIMAL) / Decimal(str(len(losses))) if losses else _DEFAULT_DECIMAL,
        largest_win=max(wins) if wins else _DEFAULT_DECIMAL,
        largest_loss=min(losses) if losses else _DEFAULT_DECIMAL,
    )


@dataclass(frozen=True)
class TradeStats:
    """Summary statistics derived from per-trade P&L values."""

    profit_factor: float
    average_trade_pnl: Decimal
    average_win: Decimal
    average_loss: Decimal
    largest_win: Decimal
    largest_loss: Decimal


@dataclass
class BacktestReport:
    """Comprehensive backtest report."""

    # Identification
    report_id: str = ''
    generated_at: str = ''

    # Period
    start_date: str = ''
    end_date: str = ''
    total_days: int = 0

    # Returns
    total_return: Decimal = field(default_factory=lambda: Decimal('0'))
    total_return_pct: float = 0.0
    annualized_return: float = 0.0

    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: Decimal = field(default_factory=lambda: Decimal('0'))
    max_drawdown_pct: float = 0.0
    calmar_ratio: float = 0.0

    # Trade statistics
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    average_trade_pnl: Decimal = field(default_factory=lambda: Decimal('0'))
    average_win: Decimal = field(default_factory=lambda: Decimal('0'))
    average_loss: Decimal = field(default_factory=lambda: Decimal('0'))
    largest_win: Decimal = field(default_factory=lambda: Decimal('0'))
    largest_loss: Decimal = field(default_factory=lambda: Decimal('0'))
    average_trade_duration: float = 0.0  # In bars

    # Risk-adjusted metrics
    value_at_risk_95: Decimal = field(default_factory=lambda: Decimal('0'))
    expected_shortfall: Decimal = field(default_factory=lambda: Decimal('0'))

    # Walk-forward specific
    in_sample_sharpe: float | None = None
    out_of_sample_sharpe: float | None = None
    overfitting_ratio: float | None = None
    oos_profitable_rate: float | None = None

    # Execution costs
    total_slippage_cost: Decimal = field(default_factory=lambda: Decimal('0'))
    total_commission_cost: Decimal = field(default_factory=lambda: Decimal('0'))
    total_execution_cost: Decimal = field(default_factory=lambda: Decimal('0'))

    # Data quality
    symbols_tested: int = 0
    symbols_with_issues: int = 0
    data_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'report_id': self.report_id,
            'generated_at': self.generated_at,
            'period': {
                'start_date': self.start_date,
                'end_date': self.end_date,
                'total_days': self.total_days,
            },
            'returns': {
                'total_return': str(self.total_return),
                'total_return_pct': self.total_return_pct,
                'annualized_return': self.annualized_return,
            },
            'risk_metrics': {
                'sharpe_ratio': self.sharpe_ratio,
                'sortino_ratio': self.sortino_ratio,
                'max_drawdown': str(self.max_drawdown),
                'max_drawdown_pct': self.max_drawdown_pct,
                'calmar_ratio': self.calmar_ratio,
                'value_at_risk_95': str(self.value_at_risk_95),
                'expected_shortfall': str(self.expected_shortfall),
            },
            'trade_statistics': {
                'total_trades': self.total_trades,
                'win_rate': self.win_rate,
                'profit_factor': self.profit_factor,
                'average_win': str(self.average_win),
                'average_loss': str(self.average_loss),
                'largest_win': str(self.largest_win),
                'largest_loss': str(self.largest_loss),
                'average_trade_pnl': str(self.average_trade_pnl),
                'average_trade_duration': self.average_trade_duration,
            },
            'walk_forward': {
                'in_sample_sharpe': self.in_sample_sharpe,
                'out_of_sample_sharpe': self.out_of_sample_sharpe,
                'overfitting_ratio': self.overfitting_ratio,
                'oos_profitable_rate': self.oos_profitable_rate,
            }
            if self.in_sample_sharpe is not None
            else None,
            'execution_costs': {
                'total_slippage': str(self.total_slippage_cost),
                'total_commission': str(self.total_commission_cost),
                'total_cost': str(self.total_execution_cost),
            },
            'data_quality': {
                'symbols_tested': self.symbols_tested,
                'symbols_with_issues': self.symbols_with_issues,
                'warnings': self.data_warnings,
            },
        }


def generate_backtest_report(
    result: Any,  # BacktestResult
    output_dir: str,
) -> BacktestReport:
    """
    Generate a comprehensive backtest report.

    Args:
        result: BacktestResult from orchestrator.
        output_dir: Directory to save report files.

    Returns:
        BacktestReport with all metrics.
    """
    import uuid

    report = BacktestReport(
        report_id=str(uuid.uuid4())[:8],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    config = result.config

    # Period info
    if config.start_date and config.end_date:
        report.start_date = config.start_date.isoformat()
        report.end_date = config.end_date.isoformat()
        report.total_days = (config.end_date - config.start_date).days

    # Symbols info
    report.symbols_tested = len(config.symbols)

    # Universe validation warnings
    if result.universe_validation:
        report.symbols_with_issues = result.universe_validation.invalid_symbols
        report.data_warnings = result.universe_validation.warnings[:10]  # First 10

    # Walk-forward results
    if result.walkforward_result:
        wf = result.walkforward_result
        report.in_sample_sharpe = wf.in_sample_sharpe
        report.out_of_sample_sharpe = wf.out_of_sample_sharpe
        report.overfitting_ratio = wf.overfitting_ratio
        report.oos_profitable_rate = wf.oos_profitable_rate
        report.sharpe_ratio = wf.out_of_sample_sharpe  # Use OOS as primary

        # Aggregate trades from all folds
        total_trades = 0
        total_return = Decimal('0')
        max_drawdown_pct = 0.0
        trade_records: list[TradeRecord] = []
        execution_slippage = Decimal('0')
        execution_commission = Decimal('0')
        sortino_values: list[float] = []
        calmar_values: list[float] = []
        returns: list[float] = []
        max_drawdown = _DEFAULT_DECIMAL
        return_pcts: list[float] = []
        for fold in wf.folds:
            if fold.test_result:
                total_trades += fold.test_result.total_trades
                total_return += fold.test_result.total_return
                max_drawdown_pct = max(max_drawdown_pct, fold.test_result.max_drawdown_pct)
                trade_records.extend(fold.test_result.trades)
                execution_slippage += fold.test_result.total_slippage
                execution_commission += fold.test_result.total_commission
                sortino_values.append(fold.test_result.sortino_ratio)
                calmar_values.append(fold.test_result.calmar_ratio)
                returns.extend(_extract_returns(fold.test_result.equity_curve))
                max_drawdown = max(max_drawdown, _calculate_max_drawdown(fold.test_result.equity_curve))
                return_pcts.append(fold.test_result.total_return_pct)

        report.total_trades = total_trades
        report.total_return = total_return
        report.max_drawdown_pct = max_drawdown_pct
        if return_pcts:
            report.total_return_pct = sum(return_pcts) / len(return_pcts)
        if sortino_values:
            report.sortino_ratio = sum(sortino_values) / len(sortino_values)
        if calmar_values:
            report.calmar_ratio = sum(calmar_values) / len(calmar_values)

        trade_stats = _calculate_trade_stats(trade_records)
        report.win_rate = (total_trades and sum(1 for pnl in _trade_pnls(trade_records) if pnl > 0) / total_trades) or 0
        report.profit_factor = trade_stats.profit_factor
        report.average_trade_pnl = trade_stats.average_trade_pnl
        report.average_win = trade_stats.average_win
        report.average_loss = trade_stats.average_loss
        report.largest_win = trade_stats.largest_win
        report.largest_loss = trade_stats.largest_loss
        report.total_slippage_cost = execution_slippage
        report.total_commission_cost = execution_commission
        report.total_execution_cost = execution_slippage + execution_commission
        report.max_drawdown = max_drawdown
        var_95, cvar_95 = _calculate_var_cvar(returns)
        report.value_at_risk_95 = var_95
        report.expected_shortfall = cvar_95

    # Single period results
    elif result.period_results:
        period = result.period_results[0]
        trade_stats = _calculate_trade_stats(period.trades)
        report.total_return = period.total_return
        report.total_return_pct = period.total_return_pct
        report.sharpe_ratio = period.sharpe_ratio
        report.sortino_ratio = period.sortino_ratio
        report.total_trades = period.total_trades
        report.win_rate = period.win_rate
        report.profit_factor = trade_stats.profit_factor
        report.average_trade_pnl = trade_stats.average_trade_pnl
        report.average_win = trade_stats.average_win
        report.average_loss = trade_stats.average_loss
        report.largest_win = trade_stats.largest_win
        report.largest_loss = trade_stats.largest_loss
        report.max_drawdown_pct = period.max_drawdown_pct
        report.calmar_ratio = period.calmar_ratio
        report.total_slippage_cost = period.total_slippage
        report.total_commission_cost = period.total_commission
        report.total_execution_cost = period.total_slippage + period.total_commission
        report.max_drawdown = _calculate_max_drawdown(period.equity_curve)
        returns = _extract_returns(period.equity_curve)
        var_95, cvar_95 = _calculate_var_cvar(returns)
        report.value_at_risk_95 = var_95
        report.expected_shortfall = cvar_95

    # Calculate annualized return
    if report.total_days > 0:
        years = report.total_days / 365.25
        if years > 0 and report.total_return_pct > -1:
            report.annualized_return = (1 + report.total_return_pct) ** (1 / years) - 1

    # Save reports
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Save JSON report
    json_path = output_path / f'backtest_report_{report.report_id}.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report.to_dict(), f, indent=2)
    logger.info(f'Saved JSON report to {json_path}')

    # Save HTML report
    html_path = output_path / f'backtest_report_{report.report_id}.html'
    html_content = generate_html_report(report, result)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    logger.info(f'Saved HTML report to {html_path}')

    return report


def generate_html_report(report: BacktestReport, result: Any = None) -> str:
    """
    Generate an HTML report.

    Args:
        report: BacktestReport with metrics.
        result: Optional BacktestResult for additional details.

    Returns:
        HTML string.
    """
    # Determine overfitting status
    overfitting_status = 'N/A'
    overfitting_class = ''
    if report.overfitting_ratio is not None:
        if report.overfitting_ratio > 2.0:
            overfitting_status = 'HIGH OVERFITTING'
            overfitting_class = 'status-bad'
        elif report.overfitting_ratio > 1.5:
            overfitting_status = 'MODERATE'
            overfitting_class = 'status-warning'
        else:
            overfitting_status = 'ACCEPTABLE'
            overfitting_class = 'status-good'

    # Generate fold table rows
    fold_rows = ''
    if result and result.walkforward_result:
        for fold in result.walkforward_result.folds:
            train_sharpe = fold.train_result.sharpe_ratio if fold.train_result else 0
            test_sharpe = fold.test_result.sharpe_ratio if fold.test_result else 0
            train_return = fold.train_result.total_return_pct if fold.train_result else 0
            test_return = fold.test_result.total_return_pct if fold.test_result else 0

            fold_rows += f'''
            <tr>
                <td>{fold.fold_number}</td>
                <td>{fold.train_start} - {fold.train_end}</td>
                <td>{fold.test_start} - {fold.test_end}</td>
                <td>{train_sharpe:.2f}</td>
                <td>{test_sharpe:.2f}</td>
                <td>{train_return:.2%}</td>
                <td class="{'positive' if test_return > 0 else 'negative'}">{test_return:.2%}</td>
            </tr>
            '''

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backtest Report - {report.report_id}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        h1 {{
            font-size: 2em;
            margin-bottom: 10px;
        }}
        .meta {{
            opacity: 0.8;
            font-size: 0.9em;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .card h2 {{
            font-size: 1.1em;
            color: #666;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
        }}
        .metric:last-child {{
            border-bottom: none;
        }}
        .metric-label {{
            color: #666;
        }}
        .metric-value {{
            font-weight: 600;
            font-family: 'Monaco', 'Menlo', monospace;
        }}
        .positive {{
            color: #27ae60;
        }}
        .negative {{
            color: #e74c3c;
        }}
        .status-good {{
            background: #27ae60;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
        }}
        .status-warning {{
            background: #f39c12;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
        }}
        .status-bad {{
            background: #e74c3c;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
            font-weight: 600;
        }}
        .warning-list {{
            list-style: none;
            padding: 0;
        }}
        .warning-list li {{
            padding: 8px;
            background: #fff3cd;
            border-left: 3px solid #ffc107;
            margin-bottom: 5px;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Backtest Report</h1>
            <div class="meta">
                ID: {report.report_id} | Generated: {report.generated_at}<br>
                Period: {report.start_date} to {report.end_date} ({report.total_days} days)
            </div>
        </header>

        <div class="grid">
            <div class="card">
                <h2>Returns</h2>
                <div class="metric">
                    <span class="metric-label">Total Return</span>
                    <span class="metric-value {'positive' if report.total_return_pct > 0 else 'negative'}">{report.total_return_pct:.2%}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Annualized Return</span>
                    <span class="metric-value">{report.annualized_return:.2%}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Total P&L</span>
                    <span class="metric-value">${float(report.total_return):,.2f}</span>
                </div>
            </div>

            <div class="card">
                <h2>Risk Metrics</h2>
                <div class="metric">
                    <span class="metric-label">Sharpe Ratio</span>
                    <span class="metric-value">{report.sharpe_ratio:.2f}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Sortino Ratio</span>
                    <span class="metric-value">{report.sortino_ratio:.2f}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Max Drawdown</span>
                    <span class="metric-value negative">{report.max_drawdown_pct:.2%}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Calmar Ratio</span>
                    <span class="metric-value">{report.calmar_ratio:.2f}</span>
                </div>
            </div>

            <div class="card">
                <h2>Trade Statistics</h2>
                <div class="metric">
                    <span class="metric-label">Total Trades</span>
                    <span class="metric-value">{report.total_trades}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Win Rate</span>
                    <span class="metric-value">{report.win_rate:.1%}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Profit Factor</span>
                    <span class="metric-value">{report.profit_factor:.2f}</span>
                </div>
            </div>

            <div class="card">
                <h2>Walk-Forward Analysis</h2>
                <div class="metric">
                    <span class="metric-label">In-Sample Sharpe</span>
                    <span class="metric-value">{report.in_sample_sharpe or 'N/A'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Out-of-Sample Sharpe</span>
                    <span class="metric-value">{report.out_of_sample_sharpe or 'N/A'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Overfitting Ratio</span>
                    <span class="metric-value">{report.overfitting_ratio:.2f if report.overfitting_ratio else 'N/A'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Status</span>
                    <span class="metric-value {overfitting_class}">{overfitting_status}</span>
                </div>
            </div>
        </div>

        {'<div class="card"><h2>Walk-Forward Folds</h2><table><thead><tr><th>Fold</th><th>Train Period</th><th>Test Period</th><th>Train Sharpe</th><th>Test Sharpe</th><th>Train Return</th><th>Test Return</th></tr></thead><tbody>' + fold_rows + '</tbody></table></div>' if fold_rows else ''}

        {f'<div class="card"><h2>Data Warnings ({len(report.data_warnings)})</h2><ul class="warning-list">{"".join(f"<li>{w}</li>" for w in report.data_warnings[:5])}</ul></div>' if report.data_warnings else ''}

        <div class="card">
            <h2>Execution Costs</h2>
            <div class="metric">
                <span class="metric-label">Total Slippage</span>
                <span class="metric-value">${float(report.total_slippage_cost):,.2f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Total Commission</span>
                <span class="metric-value">${float(report.total_commission_cost):,.2f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Total Execution Cost</span>
                <span class="metric-value">${float(report.total_execution_cost):,.2f}</span>
            </div>
        </div>
    </div>
</body>
</html>"""

    return html
