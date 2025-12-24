"""Analytics reporting for trading sessions."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from ..analytics import PnlValue
    from ..interfaces.portfolio import PortfolioProtocol


class TradeLogEntry(TypedDict):
    timestamp: datetime
    symbol: str
    quantity: float
    price: float
    realised_pnl: PnlValue


class AnalyticsReporter:
    """Generates analytics reports on shutdown.

    Responsibilities:
    - Symbol performance CSV export
    - Drawdown analysis
    - Capital sizing guidance
    """

    def __init__(self, portfolio: PortfolioProtocol, checkpoint_dir: str):
        self.portfolio = portfolio
        self.checkpoint_dir = checkpoint_dir
        self.logger = logging.getLogger(__name__)

        # Track state
        self.trade_log: list[TradeLogEntry] = []
        self.equity_curve: deque[tuple[datetime, Decimal]] = deque(maxlen=10000)  # Bounded to prevent memory leak
        self.symbols: list[str] = []

    def record_trade(
        self,
        timestamp: datetime,
        symbol: str,
        quantity: float,
        price: float,
        realized_pnl: float,
    ) -> None:
        """Record a trade for analytics."""
        self.trade_log.append(
            {
                'timestamp': timestamp,
                'symbol': symbol,
                'quantity': quantity,
                'price': price,
                'realised_pnl': realized_pnl,
            }
        )

        # Keep bounded
        if len(self.trade_log) > 1000:
            self.trade_log = self.trade_log[-1000:]

    def record_equity(self, timestamp: datetime, equity: Decimal) -> None:
        """Record equity for drawdown analysis."""
        self.equity_curve.append((timestamp, equity))

    def set_symbols(self, symbols: list[str]) -> None:
        """Set symbols for reporting."""
        self.symbols = symbols

    def generate_reports(self, last_prices: dict[str, Decimal]) -> None:
        """Generate all analytics reports on shutdown."""
        try:
            from ..analytics import (
                export_drawdown_csv,
                export_symbol_performance_csv,
                generate_capital_sizing_report,
            )

            # Symbol performance
            if self.trade_log and self.symbols:
                export_symbol_performance_csv(
                    self.trade_log, self.symbols, f'{self.checkpoint_dir}/symbol_performance.csv'
                )
                self.logger.info('Exported symbol_performance.csv')

            # Drawdown analysis
            if self.equity_curve:
                export_drawdown_csv(list(self.equity_curve), f'{self.checkpoint_dir}/drawdown_analysis.csv')
                self.logger.info('Exported drawdown_analysis.csv')

            # Capital sizing
            current_equity = self.portfolio.total_equity(last_prices)
            sizing_report = generate_capital_sizing_report(
                current_capital=Decimal(str(current_equity)),
                target_monthly_return_pct=10.0,
                avg_monthly_return_pct=None,
            )
            self.logger.info(f'Capital sizing guidance: {sizing_report}')

        except Exception as exc:
            self.logger.warning(f'Analytics export failed: {exc}')
