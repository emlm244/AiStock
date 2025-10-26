from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .brokers.base import BaseBroker
from .brokers.ibkr import IBKRBroker
from .brokers.paper import PaperBroker
from .calendar import is_trading_time
from .config import BacktestConfig
from .data import Bar
from .execution import ExecutionReport, Order, OrderSide, OrderType
from .fsd import FSDConfig, FSDEngine
from .idempotency import OrderIdempotencyTracker
from .logging import configure_logger
from .persistence import load_checkpoint, save_checkpoint
from .portfolio import Portfolio
from .risk import RiskEngine, RiskViolation
from .sizing import target_quantity
from .strategy import StrategyContext, default_strategy_suite
from .universe import UniverseSelector, UniverseSelectionResult


class LiveTradingSession:
    """
    Orchestrates live or paper trading using the shared strategy/risk pipeline.
    """

    def __init__(
        self,
        config: BacktestConfig,
        mode: str = "bot",  # "bot", "headless", or "fsd"
        fsd_config: FSDConfig | None = None,
        checkpoint_dir: str = "state",
        enable_checkpointing: bool = True,
        restore_from_checkpoint: bool = False,
    ) -> None:
        self.config = config
        self.mode = mode
        self.fsd_config = fsd_config
        self.universe_selection: UniverseSelectionResult | None = None

        if config.data.symbols:
            resolved_symbols = list(config.data.symbols)
        else:
            if not config.universe:
                raise ValueError(
                    "Live session requires DataSource.symbols or a UniverseConfig for automatic selection."
                )
            selector = UniverseSelector(config.data, config.engine.data_quality)
            selection = selector.select(config.universe)
            if not selection.symbols:
                raise ValueError("Universe selector did not return any tradable symbols.")
            resolved_symbols = selection.symbols
            self.universe_selection = selection

        self.symbols = resolved_symbols
        self.logger = configure_logger("LiveSession", structured=True)
        self.strategy_suite = default_strategy_suite(config.engine.strategy)
        self.checkpoint_dir = checkpoint_dir
        self.enable_checkpointing = enable_checkpointing

        if self.universe_selection:
            self.logger.info(
                "universe_selected",
                extra={
                    "symbols": self.universe_selection.symbols,
                    "scores": self.universe_selection.scores,
                },
            )

        # P0 Fix: Restore from checkpoint if requested
        if restore_from_checkpoint:
            try:
                self.portfolio, risk_state = load_checkpoint(checkpoint_dir)
                self.risk = RiskEngine(config.engine.risk, self.portfolio, config.data.bar_interval, state=risk_state)
                self.logger.info(
                    "restored_from_checkpoint",
                    extra={
                        "cash": float(self.portfolio.cash),
                        "positions": len(self.portfolio.positions),
                        "checkpoint_dir": checkpoint_dir,
                    },
                )
            except FileNotFoundError as exc:
                self.logger.warning("checkpoint_not_found", extra={"error": str(exc)})
                self.portfolio = Portfolio(cash=Decimal(str(config.engine.initial_equity)))
                self.risk = RiskEngine(config.engine.risk, self.portfolio, config.data.bar_interval)
        else:
            self.portfolio = Portfolio(cash=Decimal(str(config.engine.initial_equity)))
            self.risk = RiskEngine(config.engine.risk, self.portfolio, config.data.bar_interval)

        self.history: dict[str, list[Bar]] = defaultdict(list)
        self.last_prices: dict[str, Decimal] = {}
        self._lock = threading.Lock()
        self.trade_log: list[dict] = []
        self.equity_curve: list[tuple[datetime, Decimal]] = []
        self._last_equity = Decimal(str(config.engine.initial_equity))

        # P0 Fix: Order idempotency tracker
        self.idempotency_tracker = OrderIdempotencyTracker(
            storage_path=f"{checkpoint_dir}/submitted_orders.json"
        )

        # P0 Fix: Reconciliation state
        self._last_reconciliation_time: datetime | None = None
        self._reconciliation_interval = timedelta(hours=1)  # Reconcile hourly

        backend = config.broker.backend.lower()
        if backend == "paper":
            broker: BaseBroker = PaperBroker(config.execution)
        elif backend == "ibkr":
            broker = IBKRBroker(config.broker)
        else:
            raise ValueError(f"Unknown broker backend: {config.broker.backend}")

        self.broker = broker
        self.broker.set_fill_handler(self._handle_fill)

        self._subscriptions: dict[str, int] = {}
        self._running = False
        self._reconciliation_alerts: list[dict] = []

        # Initialize FSD engine if in FSD mode
        self.fsd_engine: FSDEngine | None = None
        self.fsd_session_stats: dict[str, object] = {}
        if self.mode == "fsd":
            if not self.fsd_config:
                raise ValueError("fsd_config is required when mode='fsd'")
            self.fsd_engine = FSDEngine(self.fsd_config, self.portfolio)
            self.logger.info("fsd_mode_initialized", extra={"max_capital": self.fsd_config.max_capital, "time_limit_minutes": self.fsd_config.time_limit_minutes})

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self.broker.start()
        self._running = True

        # Start FSD session if in FSD mode
        if self.fsd_engine:
            self.fsd_session_stats = self.fsd_engine.start_session()
            self.logger.info("fsd_session_started", extra=self.fsd_session_stats)

        if isinstance(self.broker, IBKRBroker):  # subscribe to real-time bars
            for symbol in self.symbols:
                req_id = self.broker.subscribe_realtime_bars(symbol, self._on_bar)
                self._subscriptions[symbol] = req_id
        else:
            self.logger.info("Paper broker active - feed bars manually via process_bar().")

    def stop(self) -> None:
        if not self._running:
            return

        # End FSD session if in FSD mode
        if self.fsd_engine:
            end_stats = self.fsd_engine.end_session()
            self.logger.info("fsd_session_ended", extra=end_stats)

        for symbol, req_id in list(self._subscriptions.items()):
            self.broker.unsubscribe(req_id)
            self._subscriptions.pop(symbol, None)
        self.broker.stop()
        self._running = False

    # ------------------------------------------------------------------
    def process_bar(self, bar: Bar) -> None:
        """Allows external feeds (e.g. simulation) to push bars in paper mode."""
        self._on_bar(bar.timestamp, bar.symbol, float(bar.open), float(bar.high), float(bar.low), float(bar.close), bar.volume)
        if isinstance(self.broker, PaperBroker):
            self.broker.process_bar(bar, bar.timestamp)

    # ------------------------------------------------------------------
    def _on_bar(self, timestamp: datetime, symbol: str, open_: float, high: float, low: float, close: float, volume: float) -> None:
        bar = Bar(
            symbol=symbol,
            timestamp=timestamp,
            open=Decimal(str(open_)),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal(str(close)),
            volume=volume,
        )
        with self._lock:
            history = self.history[symbol]
            history.append(bar)
            if len(history) > self.config.data.warmup_bars * 5:
                # keep memory bounded
                del history[: len(history) - self.config.data.warmup_bars * 5]
            self.last_prices[symbol] = bar.close

        self._evaluate_signal(timestamp, symbol)

    def _evaluate_signal(self, timestamp: datetime, symbol: str) -> None:
        # P0 Fix: Skip signal evaluation outside trading hours
        if self.config.data.enforce_trading_hours and not is_trading_time(
            timestamp,
            exchange=self.config.data.exchange,
            allow_extended_hours=self.config.data.allow_extended_hours,
        ):
            self.logger.debug(
                "skip_non_trading_hour",
                extra={"timestamp": timestamp.isoformat(), "symbol": symbol},
            )
            return

        # P0 Fix: Periodic reconciliation with broker positions
        if self._should_reconcile(timestamp):
            self._reconcile_positions(timestamp)

        with self._lock:
            history = list(self.history[symbol])
            last_prices = dict(self.last_prices)

        if not history:
            return

        # Route to FSD engine if in FSD mode
        if self.mode == "fsd" and self.fsd_engine:
            self._evaluate_fsd_signal(timestamp, symbol, history, last_prices)
            return

        # BOT mode: Use traditional strategy suite
        context = StrategyContext(symbol=symbol, history=history)
        target = self.strategy_suite.blended_target(context)
        equity = self.portfolio.total_equity(last_prices)
        previous_reset = self.risk.state.last_reset_date
        self.risk._ensure_reset(timestamp, Decimal(str(equity)))
        if self.risk.state.last_reset_date != previous_reset:
            self.idempotency_tracker.clear_old_ids()

        desired_qty = target_quantity(target.target_weight, Decimal(str(equity)), history[-1].close, self.config.engine.risk, target.confidence)
        current_position = self.portfolio.position(symbol)
        delta = desired_qty - current_position.quantity
        if abs(delta) < Decimal("1e-6"):
            return

        # P0 Fix: Generate client order ID for idempotency
        client_order_id = self.idempotency_tracker.generate_client_order_id(symbol, timestamp, delta)

        # Check if this order was already submitted (deduplication)
        if self.idempotency_tracker.is_duplicate(client_order_id):
            self.logger.warning(
                "duplicate_order_skipped",
                extra={"symbol": symbol, "client_order_id": client_order_id},
            )
            return

        order_side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        order = Order(
            symbol=symbol,
            quantity=abs(delta),
            side=order_side,
            order_type=OrderType.MARKET,
            submit_time=timestamp,
            client_order_id=client_order_id,  # P0 Fix: Attach client order ID
        )

        try:
            self.risk.check_pre_trade(symbol, delta, history[-1].close, Decimal(str(equity)), last_prices)
        except RiskViolation as err:
            self.logger.warning("risk_violation", extra={"symbol": symbol, "reason": str(err)})
            return

        # Mark as submitted BEFORE broker.submit() for crash safety
        self.idempotency_tracker.mark_submitted(client_order_id)

        order_id = self.broker.submit(order)
        self.logger.info(
            "order_submitted",
            extra={"symbol": symbol, "order_id": order_id, "client_order_id": client_order_id, "qty": float(delta)},
        )

    def _evaluate_fsd_signal(self, timestamp: datetime, symbol: str, history: list[Bar], last_prices: dict[str, Decimal]) -> None:
        """FSD mode: AI evaluates all symbols and decides what to trade."""
        if not self.fsd_engine:
            return

        # FSD AI evaluates this opportunity
        decision = self.fsd_engine.evaluate_opportunity(symbol, history, last_prices)

        # Log AI decision with confidence breakdown
        self.logger.info(
            "fsd_decision",
            extra={
                "symbol": symbol,
                "should_trade": decision["should_trade"],
                "confidence": float(decision.get("confidence", 0.0)),
                "confidence_breakdown": decision.get("confidence_breakdown", {}),
                "reason": decision.get("reason"),
            },
        )

        # If AI decides not to trade, we're done
        if not decision["should_trade"]:
            return

        # AI decided to trade - get action details
        action = decision.get("action", {})
        if not action:
            return

        # Calculate desired quantity based on AI's size_fraction
        equity = self.portfolio.total_equity(last_prices)
        size_fraction = Decimal(str(action.get("size_fraction", 0.0)))
        symbol_to_trade = action.get("symbol", symbol)

        # Ensure we have history for the chosen symbol
        with self._lock:
            symbol_history = list(self.history.get(symbol_to_trade, []))

        if not symbol_history:
            self.logger.warning("fsd_no_history", extra={"symbol": symbol_to_trade})
            return

        current_price = symbol_history[-1].close
        available_capital_value = decision.get("available_capital")
        if available_capital_value is None:
            if self.fsd_config:
                available_capital_value = self.fsd_config.max_capital
            else:
                available_capital_value = float(equity)
        available_capital = Decimal(str(max(0.0, available_capital_value)))
        desired_notional = min(Decimal(str(equity)) * size_fraction, available_capital)
        desired_qty = desired_notional / current_price if current_price > 0 else Decimal("0")

        current_position = self.portfolio.position(symbol_to_trade)
        delta = desired_qty - current_position.quantity

        if abs(delta) < Decimal("1e-6"):
            return

        # Generate client order ID for idempotency
        client_order_id = self.idempotency_tracker.generate_client_order_id(symbol_to_trade, timestamp, delta)

        if self.idempotency_tracker.is_duplicate(client_order_id):
            self.logger.warning("fsd_duplicate_order_skipped", extra={"symbol": symbol_to_trade, "client_order_id": client_order_id})
            return

        # Risk check (FSD still respects max_capital constraint via portfolio)
        try:
            self.risk.check_pre_trade(symbol_to_trade, delta, current_price, Decimal(str(equity)), last_prices)
        except RiskViolation as err:
            self.logger.warning("fsd_risk_violation", extra={"symbol": symbol_to_trade, "reason": str(err)})
            return

        # Submit order
        order_side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        order = Order(
            symbol=symbol_to_trade,
            quantity=abs(delta),
            side=order_side,
            order_type=OrderType.MARKET,
            submit_time=timestamp,
            client_order_id=client_order_id,
        )

        self.fsd_engine.register_trade_intent(
            symbol_to_trade,
            timestamp=timestamp,
            decision=decision,
            target_notional=float(desired_notional),
            target_quantity=float(desired_qty),
        )

        self.idempotency_tracker.mark_submitted(client_order_id)
        order_id = self.broker.submit(order)

        self.logger.info(
            "fsd_order_submitted",
            extra={
                "symbol": symbol_to_trade,
                "order_id": order_id,
                "client_order_id": client_order_id,
                "qty": float(delta),
                "ai_confidence": float(decision.get("confidence", 0.0)),
            },
        )

    def _handle_fill(self, report: ExecutionReport) -> None:
        signed_qty = report.quantity if report.side == OrderSide.BUY else -report.quantity
        position_before = float(self.portfolio.position(report.symbol).quantity)
        realised = self.portfolio.apply_fill(report.symbol, signed_qty, report.price, Decimal("0"), report.timestamp)
        position_after = float(self.portfolio.position(report.symbol).quantity)
        with self._lock:
            self.last_prices[report.symbol] = report.price
        equity_now = self.portfolio.total_equity(self.last_prices)
        self.risk.register_trade(realised, Decimal("0"), report.timestamp, Decimal(str(equity_now)), self.last_prices)
        self._last_equity = Decimal(str(equity_now))
        self.equity_curve.append((report.timestamp, self._last_equity))
        self.trade_log.append(
            {
                "timestamp": report.timestamp,
                "symbol": report.symbol,
                "quantity": float(signed_qty),
                "price": float(report.price),
                "realised_pnl": float(realised),
            }
        )
        if len(self.trade_log) > 1000:
            del self.trade_log[: len(self.trade_log) - 1000]
        self.logger.info(
            "fill",
            extra={
                "symbol": report.symbol,
                "qty": float(signed_qty),
                "price": float(report.price),
                "equity": float(equity_now),
            },
        )

        # FSD mode: Record trade outcome for AI learning
        if self.mode == "fsd" and self.fsd_engine:
            self.fsd_engine.handle_fill(
                symbol=report.symbol,
                timestamp=report.timestamp,
                fill_price=float(report.price),
                realised_pnl=float(realised),
                signed_quantity=float(signed_qty),
                previous_position=position_before,
                new_position=position_after,
            )
            self.logger.info(
                "fsd_learning_update",
                extra={"symbol": report.symbol, "pnl": float(realised), "total_trades": len(self.fsd_engine.trade_history)},
            )

        # P0 Fix: Auto-save checkpoint after every fill for crash recovery
        if self.enable_checkpointing:
            try:
                save_checkpoint(self.portfolio, self.risk.state, self.checkpoint_dir)
                self.logger.debug("checkpoint_saved", extra={"checkpoint_dir": self.checkpoint_dir})
            except Exception as exc:
                self.logger.error("checkpoint_save_failed", extra={"error": str(exc)})

    def _should_reconcile(self, timestamp: datetime) -> bool:
        """P0 Fix: Check if it's time for periodic position reconciliation."""
        if self._last_reconciliation_time is None:
            return True
        current_ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        last_ts = self._last_reconciliation_time if self._last_reconciliation_time.tzinfo else self._last_reconciliation_time.replace(tzinfo=timezone.utc)
        if current_ts <= last_ts:
            return False
        elapsed = current_ts - last_ts
        return elapsed >= self._reconciliation_interval

    def _reconcile_positions(self, as_of: datetime) -> None:
        """
        P0 Fix: Compare internal portfolio positions with broker truth.

        Logs warnings for any mismatches but does not auto-correct (safety first).
        """
        try:
            broker_positions = self.broker.get_positions()
            with self._lock:
                internal_positions = {
                    sym: (float(pos.quantity), float(pos.average_price))
                    for sym, pos in self.portfolio.positions.items()
                }

            mismatches = []
            # Check internal vs broker
            for symbol, (internal_qty, _internal_price) in internal_positions.items():
                broker_qty, broker_price = broker_positions.get(symbol, (0.0, 0.0))
                if abs(internal_qty - broker_qty) > 0.001:  # Allow tiny floating point error
                    mismatches.append({
                        "symbol": symbol,
                        "internal_qty": internal_qty,
                        "broker_qty": broker_qty,
                        "delta": internal_qty - broker_qty,
                    })

            # Check broker positions not in internal
            for symbol, (broker_qty, _broker_price) in broker_positions.items():
                if symbol not in internal_positions and abs(broker_qty) > 0.001:
                    mismatches.append({
                        "symbol": symbol,
                        "internal_qty": 0.0,
                        "broker_qty": broker_qty,
                        "delta": -broker_qty,
                    })

            if mismatches:
                self.logger.warning(
                    "reconciliation_mismatch",
                    extra={
                        "mismatches": mismatches,
                        "count": len(mismatches),
                        "as_of": (as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)).isoformat(),
                    },
                )
                as_of_iso = (
                    as_of.astimezone(timezone.utc).isoformat()
                    if as_of.tzinfo
                    else as_of.replace(tzinfo=timezone.utc).isoformat()
                )
                annotated = []
                for entry in mismatches:
                    entry_with_ts = dict(entry)
                    entry_with_ts["as_of"] = as_of_iso
                    annotated.append(entry_with_ts)
                self._reconciliation_alerts.extend(annotated)
            else:
                self.logger.info(
                    "reconciliation_ok",
                    extra={
                        "positions": len(internal_positions),
                        "as_of": (as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)).isoformat(),
                    },
                )

            self._last_reconciliation_time = (
                as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
            )

        except Exception as exc:
            self.logger.error("reconciliation_failed", extra={"error": str(exc)})

    def snapshot(self) -> dict:
        with self._lock:
            positions = []
            for symbol, position in self.portfolio.positions.items():
                positions.append(
                    {
                        "symbol": symbol,
                        "quantity": float(position.quantity),
                        "avg_price": float(position.average_price),
                        "last_update": position.last_update_utc,
                    }
                )
            trades = list(self.trade_log[-100:])
            prices = {sym: float(price) for sym, price in self.last_prices.items()}

        equity_curve = list(self.equity_curve)

        risk_state = {
            "halted": self.risk.is_halted(),
            "halt_reason": self.risk.halt_reason(),
            "daily_pnl": float(self.risk.state.daily_pnl),
            "peak_equity": float(self.risk.state.peak_equity),
            "weekly_loss_pct": float(self._compute_weekly_loss_pct()),
        }

        # Add FSD stats if in FSD mode
        fsd_stats = {}
        if self.mode == "fsd" and self.fsd_engine:
            fsd_stats = {
                "mode": "fsd",
                "total_trades": len(self.fsd_engine.trade_history),
                "q_values_learned": len(self.fsd_engine.rl_agent.q_values),
                "exploration_rate": self.fsd_engine.rl_agent.exploration_rate,
                "win_rate": self._compute_fsd_win_rate(),
                "avg_pnl": self._compute_fsd_avg_pnl(),
                "experience_buffer": len(self.fsd_engine.rl_agent.experience_buffer),
                "last_trade_time": self.fsd_engine.last_trade_timestamp.isoformat() if self.fsd_engine.last_trade_timestamp else None,
            }
        else:
            fsd_stats = {"mode": self.mode}

        return {
            "positions": positions,
            "trades": trades,
            "prices": prices,
            "equity": float(self._last_equity),
            "cash": float(self.portfolio.cash),
            "risk": risk_state,
            "reconciliation_alerts": list(self._reconciliation_alerts[-10:]),  # Last 10 alerts
            "equity_curve": [(ts, float(eq)) for ts, eq in equity_curve],
            "fsd": fsd_stats,
        }

    def _compute_fsd_win_rate(self) -> float:
        """Calculate FSD win rate from trade history."""
        if not self.fsd_engine or not self.fsd_engine.trade_history:
            return 0.0
        winning_trades = sum(1 for trade in self.fsd_engine.trade_history if trade.pnl > 0)
        return winning_trades / len(self.fsd_engine.trade_history)

    def _compute_fsd_avg_pnl(self) -> float:
        """Calculate FSD average PnL from trade history."""
        if not self.fsd_engine or not self.fsd_engine.trade_history:
            return 0.0
        total_pnl = sum(trade.pnl for trade in self.fsd_engine.trade_history)
        return total_pnl / len(self.fsd_engine.trade_history)

    def apply_adaptive_config(self, new_config: BacktestConfig) -> None:
        """
        Allow adaptive controllers to adjust strategy/risk parameters at runtime.

        The broker connectivity layer is left untouched; this only refreshes
        strategy logic and risk limits while preserving current portfolio state.
        """
        with self._lock:
            self.config = new_config
            self.strategy_suite = default_strategy_suite(new_config.engine.strategy)
            # Preserve existing risk state but update limits/clock interval.
            self.risk = RiskEngine(
                new_config.engine.risk,
                self.portfolio,
                new_config.data.bar_interval,
                state=self.risk.state,
            )

    def _compute_weekly_loss_pct(self) -> Decimal:
        """Approximate weekly loss using the last five equity curve points."""
        if len(self.equity_curve) < 2:
            return Decimal("0")
        recent = self.equity_curve[-min(5, len(self.equity_curve)) :]
        start_equity = recent[0][1]
        end_equity = recent[-1][1]
        if start_equity == 0:
            return Decimal("0")
        return (end_equity - start_equity) / start_equity
