"""
Deterministic backtesting engine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from .brokers.paper import PaperBroker
from .calendar import is_trading_time
from .config import BacktestConfig
from .data import Bar, DataFeed, load_csv_directory
from .execution import Order, OrderSide, OrderType
from .logging import configure_logger
from .performance import compute_drawdown, compute_returns, sharpe_ratio, sortino_ratio, trade_performance
from .portfolio import Portfolio
from .risk import RiskEngine, RiskViolation
from .sizing import target_quantity
from .strategy import StrategyContext, default_strategy_suite
from .universe import UniverseSelector, UniverseSelectionResult


@dataclass
class Trade:
    symbol: str
    timestamp: datetime
    quantity: Decimal
    price: Decimal
    realised_pnl: Decimal
    equity: Decimal
    order_id: int
    strategy: str


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: list[tuple[datetime, Decimal]]
    metrics: dict[str, float]
    max_drawdown: Decimal
    total_return: Decimal
    win_rate: float


@dataclass
class BacktestRunner:
    config: BacktestConfig

    def run(self, override_data: dict[str, list[Bar]] | None = None) -> BacktestResult:
        self.config.validate()
        data_source = self.config.data
        selection: UniverseSelectionResult | None = None

        if not data_source.symbols and override_data is None:
            if not self.config.universe:
                raise ValueError(
                    "Backtest requires DataSource.symbols or a UniverseConfig for automatic selection."
                )
            selector = UniverseSelector(data_source, self.config.engine.data_quality)
            selection = selector.select(self.config.universe)
            if not selection.symbols:
                raise ValueError("Universe selector did not return any tradable symbols.")
            data_source = replace(data_source, symbols=tuple(selection.symbols))

        raw_data = override_data or load_csv_directory(data_source, self.config.engine.data_quality)
        feed = DataFeed(
            bars_by_symbol=raw_data,
            bar_interval=self.config.data.bar_interval,
            warmup_bars=self.config.data.warmup_bars,
            fill_missing=self.config.engine.data_quality.fill_missing_with_last,
        )

        portfolio = Portfolio(cash=Decimal(str(self.config.engine.initial_equity)))
        risk = RiskEngine(self.config.engine.risk, portfolio, self.config.data.bar_interval)
        logger = configure_logger("Backtest", level="INFO", structured=True)

        if selection:
            logger.info(
                "universe_selected",
                extra={
                    "symbols": selection.symbols,
                    "scores": selection.scores,
                },
            )

        strategy_suite = default_strategy_suite(self.config.engine.strategy)

        history: dict[str, list] = {symbol: [] for symbol in raw_data}
        last_prices: dict[str, Decimal] = {
            symbol: bars[0].close for symbol, bars in raw_data.items() if bars
        }

        trades: list[Trade] = []
        equity_curve: list[tuple[datetime, Decimal]] = []

        commission = Decimal(str(self.config.engine.commission_per_trade))

        def handle_fill(report):
            signed_qty = report.quantity if report.side == OrderSide.BUY else -report.quantity
            fill_price = report.price
            realised = portfolio.apply_fill(report.symbol, signed_qty, fill_price, commission, report.timestamp)
            last_prices[report.symbol] = fill_price
            equity_now = portfolio.total_equity(last_prices)
            risk.register_trade(realised, commission, report.timestamp, equity_now, last_prices)
            trades.append(
                Trade(
                    symbol=report.symbol,
                    timestamp=report.timestamp,
                    quantity=signed_qty,
                    price=fill_price,
                    realised_pnl=realised,
                    equity=equity_now,
                    order_id=report.order_id,
                    strategy="Blended",
                )
            )
            logger.info(
                "fill",
                extra={
                    "order_id": report.order_id,
                    "symbol": report.symbol,
                    "qty": float(signed_qty),
                    "price": float(fill_price),
                    "equity": float(equity_now),
                },
            )

        broker = PaperBroker(self.config.execution)
        broker.set_fill_handler(handle_fill)

        try:
            broker.start()

            for timestamp, symbol, bar in feed.iter_stream():
                # P0 Fix: Skip bars outside trading hours if calendar enforcement is enabled
                if self.config.data.enforce_trading_hours and not is_trading_time(
                    timestamp,
                    exchange=self.config.data.exchange,
                    allow_extended_hours=self.config.data.allow_extended_hours,
                ):
                    logger.debug(
                        "skip_non_trading_hour",
                        extra={"timestamp": timestamp.isoformat(), "symbol": symbol},
                    )
                    continue

                history[symbol].append(bar)
                last_prices[symbol] = bar.close
                context = StrategyContext(symbol=symbol, history=history[symbol])
                target = strategy_suite.blended_target(context)
                equity = portfolio.total_equity(last_prices)
                risk._ensure_reset(timestamp, equity)

                current_position = portfolio.position(symbol)
                desired_quantity = target_quantity(
                    target.target_weight,
                    Decimal(str(equity)),
                    bar.close,
                    self.config.engine.risk,
                    target.confidence,
                )

                delta = desired_quantity - current_position.quantity
                if abs(delta) < Decimal("1e-6"):
                    equity_curve.append((timestamp, equity))
                    continue

                try:
                    risk.check_pre_trade(symbol, delta, bar.close, equity, last_prices)
                except RiskViolation as err:
                    logger.warning("risk_violation", extra={"reason": str(err), "symbol": symbol})
                    equity_curve.append((timestamp, equity))
                    continue

                side = OrderSide.BUY if delta > 0 else OrderSide.SELL
                order = Order(
                    symbol=symbol,
                    quantity=abs(delta),
                    side=side,
                    order_type=OrderType.MARKET,
                    submit_time=timestamp,
                )
                broker.submit(order)
                broker.process_bar(bar, timestamp)
                equity_curve.append((timestamp, portfolio.total_equity(last_prices)))

            if equity_curve:
                final_equity = equity_curve[-1][1]
                total_return = (final_equity / Decimal(str(self.config.engine.initial_equity))) - Decimal("1")
            else:
                total_return = Decimal("0")

            returns = compute_returns(equity_curve)
            metrics = {
                "sharpe": sharpe_ratio(returns),
                "sortino": sortino_ratio(returns),
            }
            perf = trade_performance([trade.realised_pnl for trade in trades])
            metrics.update(
                {
                    "expectancy": perf.expectancy,
                    "average_win": perf.average_win,
                    "average_loss": perf.average_loss,
                    "total_trades": perf.total_trades,
                }
            )

            return BacktestResult(
                trades=trades,
                equity_curve=equity_curve,
                metrics=metrics,
                max_drawdown=compute_drawdown(equity_curve),
                total_return=total_return,
                win_rate=perf.win_rate,
            )
        finally:
            broker.stop()
