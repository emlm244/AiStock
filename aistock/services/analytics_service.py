"""Analytics and reporting service."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..analytics import (
    export_drawdown_csv,
    export_symbol_performance_csv,
    generate_capital_sizing_report,
)


class AnalyticsService:
    """Performance analytics and reporting service."""

    def __init__(self, checkpoint_dir: str = 'state'):
        self.checkpoint_dir = checkpoint_dir

        # State
        self.trade_log: list[dict[str, Any]] = []
        self.equity_curve: list[tuple[datetime, Decimal]] = []
        self.symbols: list[str] = []

        self.logger = logging.getLogger(__name__)

    def record_trade(
        self,
        timestamp: datetime,
        symbol: str,
        quantity: float,
        price: float,
        realized_pnl: float,
    ) -> None:
        """Record a trade for analytics."""
        self.trade_log.append({
            'timestamp': timestamp,
            'symbol': symbol,
            'quantity': quantity,
            'price': price,
            'realised_pnl': realized_pnl,
        })

        # Keep bounded
        if len(self.trade_log) > 1000:
            self.trade_log = self.trade_log[-1000:]

    def record_equity_point(self, timestamp: datetime, equity: Decimal) -> None:
        """Record equity for drawdown analysis."""
        self.equity_curve.append((timestamp, equity))

    def set_symbols(self, symbols: list[str]) -> None:
        """Set symbols for reporting."""
        self.symbols = symbols

    def get_performance_summary(self) -> dict[str, Any]:
        """Get performance summary statistics."""
        if not self.trade_log:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_pnl': 0.0,
            }

        winning = sum(1 for t in self.trade_log if t['realised_pnl'] > 0)
        total_pnl = sum(t['realised_pnl'] for t in self.trade_log)

        return {
            'total_trades': len(self.trade_log),
            'winning_trades': winning,
            'win_rate': winning / len(self.trade_log) if self.trade_log else 0.0,
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / len(self.trade_log) if self.trade_log else 0.0,
        }

    def export_reports(self, current_equity: Decimal) -> dict[str, bool]:
        """Export all analytics reports.

        Returns:
            Dict of report_name -> success
        """
        results = {}

        # Symbol performance
        if self.trade_log and self.symbols:
            try:
                export_symbol_performance_csv(
                    self.trade_log,
                    self.symbols,
                    f'{self.checkpoint_dir}/symbol_performance.csv',
                )
                results['symbol_performance'] = True
                self.logger.info('Exported symbol_performance.csv')
            except Exception as exc:
                self.logger.warning(f'Failed to export symbol performance: {exc}')
                results['symbol_performance'] = False

        # Drawdown analysis
        if self.equity_curve:
            try:
                export_drawdown_csv(
                    self.equity_curve,
                    f'{self.checkpoint_dir}/drawdown_analysis.csv',
                )
                results['drawdown_analysis'] = True
                self.logger.info('Exported drawdown_analysis.csv')
            except Exception as exc:
                self.logger.warning(f'Failed to export drawdown: {exc}')
                results['drawdown_analysis'] = False

        # Capital sizing
        try:
            sizing_report = generate_capital_sizing_report(
                current_capital=current_equity,
                target_monthly_return_pct=10.0,
                avg_monthly_return_pct=None,
            )
            self.logger.info(f'Capital sizing: {sizing_report}')
            results['capital_sizing'] = True
        except Exception as exc:
            self.logger.warning(f'Failed to generate capital sizing: {exc}')
            results['capital_sizing'] = False

        return results
