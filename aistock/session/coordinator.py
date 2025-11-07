"""Trading session coordinator - lightweight orchestrator."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ..calendar import is_trading_time
from ..capital_management import CompoundingStrategy, ProfitWithdrawalStrategy
from ..data import Bar
from ..execution import ExecutionReport, Order, OrderSide, OrderType
from ..idempotency import OrderIdempotencyTracker
from ..stop_control import StopController

if TYPE_CHECKING:
    from ..brokers.base import BaseBroker
    from ..config import BacktestConfig
    from ..interfaces.decision import DecisionEngineProtocol
    from ..interfaces.portfolio import PortfolioProtocol
    from ..interfaces.risk import RiskEngineProtocol
    from .analytics_reporter import AnalyticsReporter
    from .bar_processor import BarProcessor
    from .checkpointer import CheckpointManager
    from .reconciliation import PositionReconciler


class TradingCoordinator:
    """Lightweight coordinator for trading sessions.

    Responsibilities:
    - Orchestrate components (NOT do their work)
    - Route bars through pipeline
    - Handle fills
    - Coordinate startup/shutdown

    Does NOT:
    - Process bars directly
    - Manage checkpoints
    - Reconcile positions
    - Generate analytics
    """

    def __init__(
        self,
        config: BacktestConfig,
        portfolio: PortfolioProtocol,
        risk_engine: RiskEngineProtocol,
        decision_engine: DecisionEngineProtocol,
        broker: BaseBroker,
        bar_processor: BarProcessor,
        reconciler: PositionReconciler,
        checkpointer: CheckpointManager,
        analytics: AnalyticsReporter,
        capital_manager: ProfitWithdrawalStrategy | CompoundingStrategy,
        stop_controller: StopController,
        symbols: list[str],
        checkpoint_dir: str = 'state',
    ):
        self.config = config
        self.portfolio = portfolio
        self.risk = risk_engine
        self.decision_engine = decision_engine
        self.broker = broker
        self.bar_processor = bar_processor
        self.reconciler = reconciler
        self.checkpointer = checkpointer
        self.analytics = analytics
        self.capital_manager = capital_manager
        self.stop_controller = stop_controller
        self.symbols = symbols
        self.checkpoint_dir = checkpoint_dir

        # Idempotency tracker
        self.idempotency = OrderIdempotencyTracker(storage_path=f'{checkpoint_dir}/submitted_orders.json')

        # Track order submissions (protected by lock for thread safety)
        self._order_submission_times: dict[int, datetime] = {}
        self._submission_lock = threading.Lock()  # Protects _order_submission_times

        # State
        self._running = False
        self._last_equity = Decimal(str(config.engine.initial_equity))
        self._last_withdrawal_check: datetime | None = None
        self._last_trading_date: datetime | None = None  # Track date for EOD reset

        # Setup analytics
        analytics.set_symbols(symbols)

        self.logger = logging.getLogger(__name__)

    def start(self) -> None:
        """Start the trading session."""
        if self._running:
            return

        self.broker.set_fill_handler(self._handle_fill)
        self.broker.start()
        self._running = True

        # Start decision engine
        session_stats = self.decision_engine.start_session()
        self.logger.info(f'Decision engine started: {session_stats}')

        # Load learned state
        try:
            loaded = self.decision_engine.load_state(f'{self.checkpoint_dir}/fsd_state.json')
            if loaded:
                self.logger.info('Loaded decision engine state')
        except Exception as exc:
            self.logger.warning(f'Could not load state: {exc}')

    def stop(self) -> None:
        """Stop the trading session."""
        if not self._running:
            return

        # Execute graceful shutdown if stop was requested (cancel orders, close positions)
        if self.stop_controller.is_stop_requested():
            last_prices = self.bar_processor.get_all_prices()
            shutdown_status = self.stop_controller.execute_graceful_shutdown(
                self.broker, self.portfolio, last_prices
            )
            self.logger.warning(f'Graceful shutdown executed: {shutdown_status}')

        # Report orphaned orders
        with self._submission_lock:
            if self._order_submission_times:
                self.logger.warning(f'Orphaned orders: {len(self._order_submission_times)}')

        # Save decision engine state
        try:
            self.decision_engine.save_state(f'{self.checkpoint_dir}/fsd_state.json')
            self.logger.info('Saved decision engine state')
        except Exception as exc:
            self.logger.error(f'Could not save state: {exc}')

        # End session
        end_stats = self.decision_engine.end_session()
        self.logger.info(f'Decision engine ended: {end_stats}')

        # Stop broker FIRST (prevents fills from arriving during shutdown)
        self.broker.stop()

        # Shutdown checkpoint worker (now safe - no more fills can arrive)
        self.checkpointer.shutdown()

        # Generate analytics
        last_prices = self.bar_processor.get_all_prices()
        self.analytics.generate_reports(last_prices)

        self._running = False

    def process_bar(self, bar: Bar) -> None:
        """Process a bar through the pipeline."""
        # Check for manual stop request
        if self.stop_controller.is_stop_requested():
            reason = self.stop_controller.get_stop_reason()
            self.logger.warning(f'Stop requested: {reason}')
            # Initiate graceful shutdown (stop() will handle the full sequence)
            return

        # Check if new trading day - reset EOD flatten flag
        current_date = bar.timestamp.date()
        if self._last_trading_date is None or current_date != self._last_trading_date:
            if self._last_trading_date is not None:
                # New day detected, reset EOD flatten
                self.stop_controller.reset_eod_flatten()
                self.logger.info(f'New trading day detected: {current_date}, reset EOD flatten')
            self._last_trading_date = current_date

        # Check for end-of-day flatten
        if self.stop_controller.check_eod_flatten(bar.timestamp):
            self.logger.warning('End-of-day flatten triggered - stopping trading')
            self.stop_controller.request_stop('end_of_day_flatten')
            return

        # Process bar
        self.bar_processor.process_bar(
            bar.timestamp,
            bar.symbol,
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
            bar.volume,
        )

        # Evaluate signal
        self._evaluate_signal(bar.timestamp, bar.symbol)

    def _evaluate_signal(self, timestamp: datetime, symbol: str) -> None:
        """Evaluate trading signal."""
        # Check trading hours
        if self.config.data.enforce_trading_hours and not is_trading_time(
            timestamp,
            exchange=self.config.data.exchange,
            allow_extended_hours=self.config.data.allow_extended_hours,
        ):
            return

        # Periodic reconciliation
        if self.reconciler.should_reconcile(timestamp):
            self.reconciler.reconcile(timestamp)

        # Periodic capital withdrawal check (once per day)
        if self._should_check_withdrawal(timestamp):
            self._check_and_withdraw_profits(timestamp)

        # Get market data
        history = self.bar_processor.get_history(symbol)
        last_prices = self.bar_processor.get_all_prices()

        if not history:
            return

        # Get decision
        decision = self.decision_engine.evaluate_opportunity(symbol, history, last_prices)

        if not decision.get('should_trade'):
            return

        # Execute trade
        self._execute_trade(symbol, decision, history, last_prices, timestamp)

    def _execute_trade(
        self,
        symbol: str,
        decision: dict[str, Any],
        history: list[Bar],
        last_prices: dict[str, Decimal],
        timestamp: datetime,
    ) -> None:
        """Execute a trade based on decision."""
        action = decision.get('action', {})
        if not action:
            return

        # Calculate quantity
        size_fraction = Decimal(str(action.get('size_fraction', 0.0)))
        if size_fraction <= 0:
            return

        equity = self.portfolio.total_equity(last_prices)
        current_price = history[-1].close
        target_notional = Decimal(str(equity)) * size_fraction

        signal = int(action.get('signal', 0))
        if signal == 0:
            return

        desired_qty = target_notional / current_price
        current_pos = self.portfolio.position(symbol)
        delta = desired_qty if signal > 0 else -desired_qty
        delta -= current_pos.quantity

        if abs(delta) < Decimal('0.00001'):
            return

        # Generate idempotent order ID
        client_order_id = self.idempotency.generate_client_order_id(symbol, timestamp, delta)

        if self.idempotency.is_duplicate(client_order_id):
            self.logger.warning(f'Duplicate order: {client_order_id}')
            return

        # Risk check
        try:
            self.risk.check_pre_trade(symbol, delta, current_price, Decimal(str(equity)), last_prices, timestamp)
        except Exception as exc:
            self.logger.warning(f'Risk violation: {exc}')
            return

        # Submit order
        try:
            order = Order(
                symbol=symbol,
                quantity=abs(delta),
                side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                order_type=OrderType.MARKET,
                submit_time=timestamp,
                client_order_id=client_order_id,
            )

            self.decision_engine.register_trade_intent(
                symbol,
                timestamp,
                decision,
                float(target_notional),
                float(desired_qty),
            )

            # Submit to broker first (source of truth)
            order_id = self.broker.submit(order)

            # Record submission with wall-clock time (not bar time)
            submission_time = datetime.now(timezone.utc)
            self.risk.record_order_submission(submission_time)
            self.idempotency.mark_submitted(client_order_id)

            # Thread-safe tracking of order submission times
            with self._submission_lock:
                self._order_submission_times[order_id] = submission_time

            self.logger.info(f'Order submitted: {symbol} {order_id}')
            self.logger.debug(f'Bar time: {timestamp}, submission time: {submission_time}')

        except Exception as exc:
            self.logger.error(f'Order submission failed: {exc}')

    def _handle_fill(self, report: ExecutionReport) -> None:
        """Handle order fill (CALLBACK - runs on IBKR thread, not main thread).

        This method is called from broker callbacks and must be thread-safe.
        All shared state accesses are protected by appropriate locks.
        """
        signed_qty = report.quantity if report.side == OrderSide.BUY else -report.quantity
        pos_before = float(self.portfolio.position(report.symbol).quantity)

        # Apply to portfolio
        realized = self.portfolio.apply_fill(
            report.symbol,
            signed_qty,
            report.price,
            Decimal('0'),
            report.timestamp,
        )

        pos_after = float(self.portfolio.position(report.symbol).quantity)

        # Update prices - use bar_processor's thread-safe method
        self.bar_processor.update_price(report.symbol, report.price)
        last_prices = self.bar_processor.get_all_prices()

        # Risk tracking
        equity = self.portfolio.total_equity(last_prices)
        self.risk.register_trade(realized, Decimal('0'), report.timestamp, Decimal(str(equity)), last_prices)

        # Analytics
        self._last_equity = Decimal(str(equity))
        self.analytics.record_equity(report.timestamp, self._last_equity)
        self.analytics.record_trade(
            report.timestamp,
            report.symbol,
            float(signed_qty),
            float(report.price),
            float(realized),
        )

        # Decision engine learning
        try:
            self.decision_engine.handle_fill(
                report.symbol,
                report.timestamp,
                float(report.price),
                float(realized),
                float(signed_qty),
                pos_before,
                pos_after,
            )
        except Exception as exc:
            self.logger.error(f'Learning error: {exc}')

        # Async checkpoint
        self.checkpointer.save_async()

        # Remove from tracking (thread-safe)
        with self._submission_lock:
            if report.order_id in self._order_submission_times:
                del self._order_submission_times[report.order_id]

        self.logger.info(f'Fill: {report.symbol} {float(signed_qty)} @ {float(report.price)}')

    def _should_check_withdrawal(self, current_time: datetime) -> bool:
        """Check if we should perform a capital withdrawal check.

        Checks once per day to avoid excessive processing.
        """
        if self._last_withdrawal_check is None:
            return True

        # Check if at least 12 hours have passed since last check
        hours_since_last = (current_time - self._last_withdrawal_check).total_seconds() / 3600
        return hours_since_last >= 12.0

    def _check_and_withdraw_profits(self, current_time: datetime) -> None:
        """Check and withdraw profits if configured."""
        try:
            last_prices = self.bar_processor.get_all_prices()
            withdrawn = self.capital_manager.check_and_withdraw(self.portfolio, last_prices)

            if withdrawn > 0:
                self.logger.info(f'Withdrew ${float(withdrawn):.2f} in profits')
                # Record in analytics
                equity = self.portfolio.total_equity(last_prices)
                self._last_equity = Decimal(str(equity))
                self.analytics.record_equity(current_time, self._last_equity)

            self._last_withdrawal_check = current_time

        except Exception as exc:
            self.logger.error(f'Capital withdrawal check failed: {exc}')

    def snapshot(self) -> dict[str, Any]:
        """Get current session state."""
        last_prices = self.bar_processor.get_all_prices()

        positions = []
        for symbol, pos in self.portfolio.snapshot_positions().items():
            positions.append(
                {
                    'symbol': symbol,
                    'quantity': float(pos.quantity),
                    'avg_price': float(pos.average_price),
                    'last_update': pos.last_update_utc,
                }
            )

        return {
            'positions': positions,
            'equity': float(self._last_equity),
            'cash': float(self.portfolio.get_cash()),
            'prices': {s: float(p) for s, p in last_prices.items()},
            'reconciliation_alerts': self.reconciler.get_alerts(),
        }
