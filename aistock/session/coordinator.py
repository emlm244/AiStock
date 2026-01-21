"""Trading session coordinator - lightweight orchestrator."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypedDict, cast

from ..calendar import is_trading_time, is_within_open_close_buffer
from ..capital_management import CompoundingStrategy, ProfitWithdrawalStrategy
from ..data import Bar
from ..execution import ExecutionReport, Order, OrderSide, OrderType
from ..idempotency import OrderIdempotencyTracker
from ..stop_control import StopController

if TYPE_CHECKING:
    from ..brokers.base import BaseBroker
    from ..config import BacktestConfig
    from ..edge_cases import EdgeCaseHandler
    from ..futures.rollover import RolloverManager
    from ..interfaces.decision import DecisionEngineProtocol
    from ..interfaces.portfolio import PortfolioProtocol
    from ..interfaces.risk import RiskEngineProtocol
    from ..professional import ProfessionalSafeguards
    from .analytics_reporter import AnalyticsReporter
    from .bar_processor import BarProcessor
    from .checkpointer import CheckpointManager
    from .reconciliation import PositionReconciler


@dataclass
class _AggregatedOHLCV:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class _ScheduledOrder:
    symbol: str
    quantity: Decimal
    side: OrderSide
    execute_at: datetime
    order_type: OrderType
    base_client_order_id: str
    slice_index: int
    total_slices: int
    volume: float = 0.0


class DecisionAction(TypedDict, total=False):
    size_fraction: float | int
    signal: int


class DecisionPayload(TypedDict, total=False):
    should_trade: bool
    action: DecisionAction
    confidence: float
    warnings: list[str]
    reason: str


class _BarAggregator:
    def __init__(self, bucket_seconds: int) -> None:
        self._bucket_seconds = max(1, bucket_seconds)
        self._current: _AggregatedOHLCV | None = None

    def update(
        self,
        timestamp: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> _AggregatedOHLCV | None:
        bucket_start = _floor_timestamp(timestamp, self._bucket_seconds)
        if self._current is None:
            self._current = _AggregatedOHLCV(bucket_start, open_, high, low, close, volume)
            return None

        if bucket_start != self._current.timestamp:
            completed = self._current
            self._current = _AggregatedOHLCV(bucket_start, open_, high, low, close, volume)
            return completed

        self._current.high = max(self._current.high, high)
        self._current.low = min(self._current.low, low)
        self._current.close = close
        self._current.volume += volume
        return None


def _floor_timestamp(timestamp: datetime, bucket_seconds: int) -> datetime:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    epoch_seconds = int(timestamp.timestamp())
    bucket_epoch = epoch_seconds - (epoch_seconds % bucket_seconds)
    return datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)


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
        rollover_manager: RolloverManager | None = None,
        safeguards: ProfessionalSafeguards | None = None,
        edge_case_handler: EdgeCaseHandler | None = None,
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
        self.rollover_manager = rollover_manager

        # Idempotency tracker
        self.idempotency = OrderIdempotencyTracker(storage_path=f'{checkpoint_dir}/submitted_orders.json')

        # Track order submissions (protected by lock for thread safety)
        self._order_submission_times: dict[int, datetime] = {}
        self._submission_lock = threading.Lock()  # Protects _order_submission_times
        self._scheduled_orders: list[_ScheduledOrder] = []
        self._scheduled_lock = threading.Lock()

        # State
        self._running = False
        self._stop_lock = threading.Lock()
        self._last_equity = Decimal(str(config.engine.initial_equity))
        self._last_withdrawal_check: datetime | None = None
        self._last_trading_date: date | None = None  # Track date for EOD reset
        self._last_rollover_check: datetime | None = None  # Track rollover alert checks

        self._safeguards = safeguards
        self._edge_case_handler = edge_case_handler

        # Market-data subscriptions (IBKR) + aggregation from 5s real-time bars.
        self._market_subscriptions: dict[str, int] = {}
        self._aggregators: dict[str, dict[str, _BarAggregator]] = {}
        self._stop_thread_started = False
        self._decision_timeframe = self._infer_decision_timeframe()
        self._timeframes = self._infer_timeframes()

        # Forced-exit tracking (max holding period enforcement)
        self._forced_exit_symbols: set[str] = set()
        self._forced_exit_lock = threading.Lock()

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
        self._stop_thread_started = False

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

        # Live market-data hookup (IBKR): subscribe to 5s bars and aggregate to configured timeframes.
        self._start_market_data()

    def stop(self) -> None:
        """Stop the trading session."""
        with self._stop_lock:
            if not self._running:
                return
            self._running = False

        self._stop_market_data()

        # Execute graceful shutdown if stop was requested (cancel orders, close positions)
        if self.stop_controller.is_stop_requested():
            last_prices = self.bar_processor.get_all_prices()
            shutdown_status = self.stop_controller.execute_graceful_shutdown(self.broker, self.portfolio, last_prices)
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

    def process_bar(self, bar: Bar, timeframe: str = '1m') -> None:
        """Process a bar through the pipeline."""
        if not self._running:
            return

        # Check for manual stop request
        if self.stop_controller.is_stop_requested():
            reason = self.stop_controller.get_stop_reason()
            self.logger.warning(f'Stop requested: {reason}')
            self._trigger_stop_async()
            return

        # Only the decision timeframe drives the main bar history + decision loop.
        is_decision_timeframe = timeframe == self._decision_timeframe

        # Check if new trading day - reset EOD flatten flag
        if is_decision_timeframe:
            current_date = bar.timestamp.date()
            if self._last_trading_date is None or current_date != self._last_trading_date:
                if self._last_trading_date is not None:
                    # New day detected, reset EOD flatten
                    self.stop_controller.reset_eod_flatten()
                    self.logger.info(f'New trading day detected: {current_date}, reset EOD flatten')
                self._last_trading_date = current_date

        # Check for end-of-day flatten
        if is_decision_timeframe and self.stop_controller.check_eod_flatten(bar.timestamp):
            self.logger.warning('End-of-day flatten triggered - stopping trading')
            self.stop_controller.request_stop('end_of_day_flatten')
            self._trigger_stop_async()
            return

        if is_decision_timeframe:
            processed = self.bar_processor.process_bar(
                bar.timestamp,
                bar.symbol,
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                bar.volume,
                timeframe=timeframe,
            )
            self._process_scheduled_orders(bar)
            self._enforce_max_holding_period(bar.timestamp, bar.symbol)
            self._evaluate_signal(bar.timestamp, bar.symbol)
            self._maybe_process_paper_fills(processed)
        else:
            self._forward_timeframe_bar(bar, timeframe)

    def _evaluate_signal(self, timestamp: datetime, symbol: str) -> None:
        """Evaluate trading signal."""
        # Check trading hours
        allow_extended_hours = self.config.data.allow_extended_hours
        if self.config.account_capabilities:
            allow_extended_hours = allow_extended_hours and self.config.account_capabilities.allow_extended_hours
        if self.config.data.enforce_trading_hours and not is_trading_time(
            timestamp,
            exchange=self.config.data.exchange,
            allow_extended_hours=allow_extended_hours,
        ):
            return
        if self._should_avoid_open_close(timestamp):
            return

        # Periodic reconciliation
        if self.reconciler.should_reconcile(timestamp):
            self.reconciler.reconcile(timestamp)

        # Periodic capital withdrawal check (once per day)
        if self._should_check_withdrawal(timestamp):
            self._check_and_withdraw_profits(timestamp)

        # Periodic rollover alert check (hourly)
        self._check_rollover_alerts(timestamp)

        # Get market data
        history = self.bar_processor.get_history(symbol)
        last_prices = self.bar_processor.get_all_prices()

        if not history:
            return

        # Get decision
        decision = cast(DecisionPayload, self.decision_engine.evaluate_opportunity(symbol, history, last_prices))

        if not decision.get('should_trade'):
            return
        if not self._apply_external_filters(symbol, history, timestamp, decision):
            return

        # Execute trade
        self._execute_trade(symbol, decision, history, last_prices, timestamp)

    def _forward_timeframe_bar(self, bar: Bar, timeframe: str) -> None:
        """Forward non-decision timeframe bars to the timeframe manager (if enabled)."""
        timeframe_manager = self.bar_processor.timeframe_manager
        if timeframe_manager is None:
            return
        timeframe_manager.add_bar(bar.symbol, timeframe, bar)

    def _maybe_process_paper_fills(self, bar: Bar) -> None:
        """Simulate fills for the paper broker (if present) using the current bar."""
        process_fn = getattr(self.broker, 'process_bar', None)
        if not callable(process_fn):
            return
        try:
            process_fn(bar, bar.timestamp)
        except Exception as exc:
            self.logger.error(f'Paper broker bar processing failed: {exc}')

    def _should_avoid_open_close(self, timestamp: datetime) -> bool:
        execution = self.config.execution
        return is_within_open_close_buffer(
            timestamp,
            execution.avoid_open_minutes,
            execution.avoid_close_minutes,
            exchange=self.config.data.exchange,
        )

    def _apply_external_filters(
        self,
        symbol: str,
        history: list[Bar],
        timestamp: datetime,
        decision: DecisionPayload,
    ) -> bool:
        apply_edge_cases = self._edge_case_handler and getattr(self.decision_engine, 'edge_case_handler', None) is None
        apply_safeguards = self._safeguards and getattr(self.decision_engine, 'safeguards', None) is None
        if not (apply_edge_cases or apply_safeguards):
            return True

        confidence_adjustment = 0.0
        size_multiplier = 1.0
        warnings: list[str] = []

        timeframe_manager = getattr(self.bar_processor, 'timeframe_manager', None)
        timeframe_divergence = False
        timeframe_data: dict[str, list[Bar]] | None = None
        if timeframe_manager is not None:
            if apply_safeguards:
                analysis = timeframe_manager.analyze_cross_timeframe(symbol)
                confidence_adjustment += analysis.confidence_adjustment
                timeframe_divergence = analysis.divergence_detected
            if apply_edge_cases:
                timeframes = getattr(timeframe_manager, 'timeframes', [])
                timeframe_data = {
                    tf: timeframe_manager.get_bars(symbol, tf, lookback=50) for tf in timeframes
                }

        if apply_edge_cases and self._edge_case_handler is not None:
            edge_result = self._edge_case_handler.check_edge_cases(
                symbol,
                history,
                timeframe_data=timeframe_data,
                current_time=timestamp,
            )
            if edge_result.action == 'block':
                self.logger.info(f'Edge case blocked trade: {edge_result.reason}')
                return False
            confidence_adjustment += edge_result.confidence_adjustment
            size_multiplier *= edge_result.position_size_multiplier
            if edge_result.is_edge_case:
                warnings.append(f'Edge case: {edge_result.reason}')

        if apply_safeguards and self._safeguards is not None:
            safeguard_result = self._safeguards.check_trading_allowed(
                symbol,
                history,
                current_time=timestamp,
                timeframe_divergence=timeframe_divergence,
            )
            if not safeguard_result.allowed:
                self.logger.info(f'Safeguards blocked trade: {safeguard_result.reason}')
                return False
            confidence_adjustment += safeguard_result.confidence_adjustment
            size_multiplier *= safeguard_result.position_size_multiplier
            warnings.extend(safeguard_result.warnings)

        if warnings:
            decision['warnings'] = warnings

        if confidence_adjustment:
            base_confidence = float(decision.get('confidence', 0.0))
            adjusted = max(0.0, min(1.0, base_confidence + confidence_adjustment))
            decision['confidence'] = adjusted
            min_conf = getattr(self.decision_engine, 'min_confidence_threshold', None)
            if isinstance(min_conf, (int, float)) and adjusted < float(min_conf):
                decision['should_trade'] = False
                decision['reason'] = (
                    f'external_confidence_too_low ({adjusted:.2f} < {float(min_conf):.2f})'
                )
                return False

        action = decision.get('action')
        if isinstance(action, dict) and size_multiplier != 1.0:
            size_fraction = float(action.get('size_fraction', 0.0))
            size_fraction = max(0.0, min(1.0, size_fraction * size_multiplier))
            action['size_fraction'] = size_fraction
            if size_fraction <= 0:
                decision['should_trade'] = False
                decision['reason'] = 'external_size_reduced_to_zero'
                return False

        return True

    def _get_max_capital_limit(self) -> Decimal | None:
        max_capital = getattr(self.decision_engine, 'max_capital', None)
        if max_capital is None:
            config = getattr(self.decision_engine, 'config', None)
            max_capital = getattr(config, 'max_capital', None) if config is not None else None
        if max_capital is None:
            return None
        try:
            value = Decimal(str(max_capital))
        except Exception:
            return None
        return value if value > 0 else None

    def _enforce_max_holding_period(self, timestamp: datetime, symbol: str) -> None:
        max_bars = int(getattr(self.risk.config, 'max_holding_period_bars', 0))
        if max_bars <= 0:
            return

        position = self.portfolio.position(symbol)
        if position.quantity == 0:
            with self._forced_exit_lock:
                self._forced_exit_symbols.discard(symbol)
            return

        entry_time = position.entry_time_utc
        if entry_time is None:
            return
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        bar_interval_seconds = int(getattr(self.config.data.bar_interval, 'total_seconds', lambda: 60)())
        if bar_interval_seconds <= 0:
            return

        bars_held = int((timestamp - entry_time).total_seconds() // bar_interval_seconds)
        if bars_held < max_bars:
            return

        with self._forced_exit_lock:
            if symbol in self._forced_exit_symbols:
                return

        last_prices = self.bar_processor.get_all_prices()
        current_price = last_prices.get(symbol)
        if current_price is None or current_price <= 0:
            return

        if self._submit_forced_exit(symbol, position.quantity, current_price, timestamp, last_prices):
            with self._forced_exit_lock:
                self._forced_exit_symbols.add(symbol)

    def _submit_forced_exit(
        self,
        symbol: str,
        quantity: Decimal,
        current_price: Decimal,
        timestamp: datetime,
        last_prices: dict[str, Decimal],
    ) -> bool:
        if quantity == 0:
            return False
        delta = -quantity
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        client_order_id = self.idempotency.generate_client_order_id(symbol, timestamp, delta)
        if self.idempotency.is_duplicate(client_order_id):
            self.logger.warning(f'Duplicate forced-exit order: {client_order_id}')
            return False

        try:
            equity = self.portfolio.total_equity(last_prices)
            self.risk.check_pre_trade(symbol, delta, current_price, Decimal(str(equity)), last_prices, timestamp)
        except Exception as exc:
            self.logger.warning(f'Forced exit blocked by risk: {exc}')
            return False

        order = Order(
            symbol=symbol,
            quantity=abs(delta),
            side=side,
            order_type=OrderType.MARKET,
            submit_time=timestamp,
            client_order_id=client_order_id,
        )

        try:
            order_id = self.broker.submit(order)
        except Exception as exc:
            self.logger.error(f'Forced exit order failed: {exc}')
            return False

        submission_time = datetime.now(timezone.utc)
        self.risk.record_order_submission(submission_time)
        self.idempotency.mark_submitted(client_order_id)
        with self._submission_lock:
            self._order_submission_times[order_id] = submission_time

        self.logger.warning(f'Forced exit submitted for {symbol} (max holding period)')
        return True

    @staticmethod
    def _estimate_spread_bps(bar: Bar) -> Decimal:
        if bar.close <= 0:
            return Decimal('0')
        spread = bar.high - bar.low
        return (spread / bar.close) * Decimal('10000')

    def _compute_limit_price(self, side: OrderSide, price: Decimal, bar: Bar) -> Decimal:
        execution = self.config.execution
        spread_bps = self._estimate_spread_bps(bar)
        offset_bps = max(Decimal(str(execution.limit_offset_bps)), spread_bps / Decimal('2'))
        offset = price * (offset_bps / Decimal('10000'))
        return price + offset if side == OrderSide.BUY else price - offset

    @staticmethod
    def _build_vwap_weights(history: list[Bar], slices: int) -> list[float]:
        if slices <= 1:
            return [1.0]
        if len(history) < slices:
            return [1.0 / slices] * slices
        volumes = [bar.volume for bar in history[-slices:]]
        total = sum(volumes)
        if total <= 0:
            return [1.0 / slices] * slices
        return [vol / total for vol in volumes]

    def _plan_execution_orders(
        self,
        symbol: str,
        delta: Decimal,
        timestamp: datetime,
        history: list[Bar],
        base_client_order_id: str,
    ) -> list[_ScheduledOrder]:
        execution = self.config.execution
        style = execution.execution_style.lower().strip()
        total_qty = abs(delta)
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL

        if style == 'adaptive':
            style = self._choose_execution_style(total_qty, history)

        if style == 'market':
            return [
                _ScheduledOrder(
                    symbol=symbol,
                    quantity=total_qty,
                    side=side,
                    execute_at=timestamp,
                    order_type=OrderType.MARKET,
                    base_client_order_id=base_client_order_id,
                    slice_index=1,
                    total_slices=1,
                )
            ]

        if style == 'twap':
            slices = max(1, execution.twap_slices)
            window_minutes = max(0, execution.twap_window_minutes)
            weights = [1.0 / slices] * slices
            return self._build_sliced_orders(
                symbol,
                total_qty,
                side,
                timestamp,
                window_minutes,
                weights,
                base_client_order_id,
            )

        if style == 'vwap':
            slices = max(1, execution.vwap_slices)
            window_minutes = max(0, execution.vwap_window_minutes)
            weights = self._build_vwap_weights(history, slices)
            return self._build_sliced_orders(
                symbol,
                total_qty,
                side,
                timestamp,
                window_minutes,
                weights,
                base_client_order_id,
            )

        return [
            _ScheduledOrder(
                symbol=symbol,
                quantity=total_qty,
                side=side,
                execute_at=timestamp,
                order_type=OrderType.LIMIT,
                base_client_order_id=base_client_order_id,
                slice_index=1,
                total_slices=1,
            )
        ]

    def _choose_execution_style(self, total_qty: Decimal, history: list[Bar]) -> str:
        if not history:
            return 'limit'
        sample = history[-20:]
        avg_volume = sum(bar.volume for bar in sample) / len(sample) if sample else 0
        if avg_volume <= 0:
            return 'limit'
        volume_ratio = float(total_qty) / avg_volume
        spread_bps = float(self._estimate_spread_bps(sample[-1]))
        if volume_ratio >= 0.05 or spread_bps >= 80.0:
            return 'twap'
        if volume_ratio >= 0.02 or spread_bps >= 30.0:
            return 'vwap'
        return 'limit'

    def _build_sliced_orders(
        self,
        symbol: str,
        total_qty: Decimal,
        side: OrderSide,
        start_time: datetime,
        window_minutes: int,
        weights: list[float],
        base_client_order_id: str,
    ) -> list[_ScheduledOrder]:
        slices = max(1, len(weights))
        if slices == 1:
            weights = [1.0]
        total_weight = sum(weights) or 1.0
        normalized = [w / total_weight for w in weights]
        total_seconds = max(0, window_minutes) * 60
        step = total_seconds / max(slices - 1, 1)

        scheduled: list[_ScheduledOrder] = []
        allocated = Decimal('0')
        for idx, weight in enumerate(normalized, start=1):
            if idx == slices:
                slice_qty = total_qty - allocated
            else:
                slice_qty = (total_qty * Decimal(str(weight))).quantize(Decimal('0.00001'))
            if slice_qty <= 0:
                continue
            allocated += slice_qty
            execute_at = start_time + timedelta(seconds=step * (idx - 1))
            scheduled.append(
                _ScheduledOrder(
                    symbol=symbol,
                    quantity=slice_qty,
                    side=side,
                    execute_at=execute_at,
                    order_type=OrderType.LIMIT,
                    base_client_order_id=base_client_order_id,
                    slice_index=idx,
                    total_slices=slices,
                )
            )
        return scheduled

    def _enqueue_scheduled_orders(self, orders: list[_ScheduledOrder]) -> None:
        if not orders:
            return
        with self._scheduled_lock:
            self._scheduled_orders.extend(orders)

    def _process_scheduled_orders(self, bar: Bar) -> None:
        due: list[_ScheduledOrder] = []
        with self._scheduled_lock:
            remaining: list[_ScheduledOrder] = []
            for scheduled in self._scheduled_orders:
                if scheduled.symbol == bar.symbol and scheduled.execute_at <= bar.timestamp:
                    due.append(scheduled)
                else:
                    remaining.append(scheduled)
            self._scheduled_orders = remaining

        if not due:
            return

        for scheduled in due:
            if self._should_avoid_open_close(bar.timestamp):
                self._enqueue_scheduled_orders([scheduled])
                continue
            self._submit_order_slice(scheduled, bar)

    def _submit_order_slice(self, scheduled: _ScheduledOrder, bar: Bar) -> None:
        last_prices = self.bar_processor.get_all_prices()
        equity = self.portfolio.total_equity(last_prices)
        current_price = bar.close
        delta = scheduled.quantity if scheduled.side == OrderSide.BUY else -scheduled.quantity

        slice_client_id = (
            f'{scheduled.base_client_order_id}-s{scheduled.slice_index}of{scheduled.total_slices}'
        )
        if self.idempotency.is_duplicate(slice_client_id):
            self.logger.warning(f'Duplicate order: {slice_client_id}')
            return

        try:
            self.risk.check_pre_trade(
                scheduled.symbol,
                delta,
                current_price,
                Decimal(str(equity)),
                last_prices,
                bar.timestamp,
            )
        except Exception as exc:
            self.logger.warning(f'Risk violation: {exc}')
            return

        order_type = scheduled.order_type
        limit_price = None
        if order_type == OrderType.LIMIT:
            limit_price = self._compute_limit_price(scheduled.side, current_price, bar)

        order = Order(
            symbol=scheduled.symbol,
            quantity=scheduled.quantity,
            side=scheduled.side,
            order_type=order_type,
            limit_price=limit_price,
            submit_time=bar.timestamp,
            client_order_id=slice_client_id,
        )

        order_id = self.broker.submit(order)
        submission_time = datetime.now(timezone.utc)
        self.risk.record_order_submission(submission_time)
        self.idempotency.mark_submitted(slice_client_id)

        with self._submission_lock:
            self._order_submission_times[order_id] = submission_time

        self.logger.info(
            f'Order submitted: {scheduled.symbol} {order_id} '
            f'({scheduled.slice_index}/{scheduled.total_slices})'
        )

    def _execute_trade(
        self,
        symbol: str,
        decision: DecisionPayload,
        history: list[Bar],
        last_prices: dict[str, Decimal],
        timestamp: datetime,
    ) -> None:
        """Execute a trade based on decision."""
        action = decision.get('action')
        if not action:
            return

        # Calculate quantity
        size_fraction = abs(Decimal(str(action.get('size_fraction', 0.0))))
        if size_fraction <= 0:
            return

        equity = self.portfolio.total_equity(last_prices)
        current_price = history[-1].close
        if current_price <= 0:
            return

        signal = int(action.get('signal', 0))
        if signal == 0:
            return

        equity_decimal = Decimal(str(equity))
        target_notional_base = equity_decimal * size_fraction
        max_capital = self._get_max_capital_limit()
        current_pos = self.portfolio.position(symbol)

        if max_capital is not None:
            target_notional_base = min(target_notional_base, max_capital)

            current_symbol_multiplier = getattr(current_pos, 'multiplier', Decimal('1'))
            current_symbol_exposure = abs(current_pos.quantity) * current_price * Decimal(str(current_symbol_multiplier))
            current_exposure = Decimal('0')
            snapshot_fn = getattr(self.portfolio, 'snapshot_positions', None)
            if callable(snapshot_fn):
                positions_snapshot = cast(dict[str, Any], snapshot_fn())
                for sym, pos in positions_snapshot.items():
                    price_value: Decimal | float | None = last_prices.get(sym)
                    if price_value is None:
                        price_value = pos.average_price
                    if price_value is None:
                        continue
                    price_dec = Decimal(str(price_value))
                    pos_multiplier = getattr(pos, 'multiplier', Decimal('1'))
                    current_exposure += abs(pos.quantity) * price_dec * Decimal(str(pos_multiplier))
            else:
                current_exposure = current_symbol_exposure

            exposure_without_symbol = current_exposure - current_symbol_exposure
            remaining_capital = max_capital - exposure_without_symbol
            if remaining_capital < Decimal('0'):
                remaining_capital = Decimal('0')

            exposure_headroom = remaining_capital
            if (signal < 0 and current_pos.quantity > 0) or (signal > 0 and current_pos.quantity < 0):
                exposure_headroom += current_symbol_exposure

            exposure_headroom = max(Decimal('0'), exposure_headroom)
            if exposure_headroom <= Decimal('0') and target_notional_base > Decimal('0'):
                self.logger.info(
                    'fsd_capital_limit_reached',
                    extra={
                        'symbol': symbol,
                        'max_capital': float(max_capital),
                        'current_exposure': float(current_exposure),
                        'headroom': float(exposure_headroom),
                    },
                )
                return

            allowed_notional = (
                min(target_notional_base, exposure_headroom) if target_notional_base > Decimal('0') else Decimal('0')
            )
            direction = Decimal('1') if signal > 0 else Decimal('-1')
            target_notional = allowed_notional * direction
        else:
            direction = Decimal('1') if signal > 0 else Decimal('-1')
            target_notional = target_notional_base * direction

        desired_qty = target_notional / current_price if current_price != 0 else Decimal('0')
        delta = desired_qty
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

        try:
            self.decision_engine.register_trade_intent(
                symbol,
                timestamp,
                cast(dict[str, Any], decision),
                float(target_notional),
                float(desired_qty),
            )
            scheduled_orders = self._plan_execution_orders(
                symbol=symbol,
                delta=delta,
                timestamp=timestamp,
                history=history,
                base_client_order_id=client_order_id,
            )
            self._enqueue_scheduled_orders(scheduled_orders)
            if scheduled_orders:
                self.idempotency.mark_submitted(client_order_id)
                self.logger.info(f'Planned {len(scheduled_orders)} order slice(s) for {symbol}')
                self._process_scheduled_orders(history[-1])

        except Exception as exc:
            self.logger.error(f'Order submission failed: {exc}')

    def _handle_fill(self, report: ExecutionReport) -> None:
        """Handle order fill (CALLBACK - runs on IBKR thread, not main thread).

        This method is called from broker callbacks and must be thread-safe.
        All shared state accesses are protected by appropriate locks.
        """
        signed_qty = report.quantity if report.side == OrderSide.BUY else -report.quantity
        pos_before = float(self.portfolio.position(report.symbol).quantity)

        # Look up contract multiplier (defaults to 1 for equities)
        multiplier = Decimal('1')
        if self.config.broker and self.config.broker.contracts:
            spec = self.config.broker.contracts.get(report.symbol)
            if spec and spec.multiplier:
                multiplier = Decimal(str(spec.multiplier))

        # Apply to portfolio with multiplier for correct futures P&L
        realized = self.portfolio.apply_fill(
            report.symbol,
            signed_qty,
            report.price,
            Decimal('0'),
            report.timestamp,
            multiplier=multiplier,
        )

        pos_after = float(self.portfolio.position(report.symbol).quantity)

        if pos_after == 0:
            with self._forced_exit_lock:
                self._forced_exit_symbols.discard(report.symbol)

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

    def _infer_decision_timeframe(self) -> str:
        """Infer the main decision timeframe from `config.data.bar_interval`."""
        try:
            from ..timeframes import SECONDS_TO_TIMEFRAME
        except Exception:
            return '1m'

        seconds = int(getattr(self.config.data.bar_interval, 'total_seconds', lambda: 60)())
        return SECONDS_TO_TIMEFRAME.get(seconds, '1m')

    def _infer_timeframes(self) -> list[str]:
        """Infer configured timeframes from the optional timeframe manager."""
        tfm = getattr(self.bar_processor, 'timeframe_manager', None)
        timeframes_obj = getattr(tfm, 'timeframes', None)
        if isinstance(timeframes_obj, Sequence) and not isinstance(timeframes_obj, (str, bytes)):
            timeframes = [str(tf) for tf in cast(Sequence[object], timeframes_obj)]
        else:
            timeframes = []
        if self._decision_timeframe not in timeframes:
            timeframes.insert(0, self._decision_timeframe)
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for tf in timeframes:
            tf_norm = str(tf).lower().strip()
            if not tf_norm or tf_norm in seen:
                continue
            seen.add(tf_norm)
            deduped.append(tf_norm)
        return deduped or [self._decision_timeframe]

    def _start_market_data(self) -> None:
        """Subscribe to live market data (IBKR) and aggregate 5s bars into configured timeframes."""
        broker_config = self.config.broker
        backend = getattr(broker_config, 'backend', '').lower() if broker_config else ''
        if backend != 'ibkr':
            return

        subscribe_fn = getattr(self.broker, 'subscribe_realtime_bars', None)
        if not callable(subscribe_fn):
            return

        try:
            from ..timeframes import TIMEFRAME_TO_SECONDS
        except Exception:
            return

        # Prepare per-symbol aggregators.
        for symbol in self.symbols:
            self._aggregators[symbol] = {}
            for timeframe in self._timeframes:
                seconds = TIMEFRAME_TO_SECONDS.get(timeframe)
                if not seconds:
                    continue
                self._aggregators[symbol][timeframe] = _BarAggregator(seconds)

        for symbol in self.symbols:
            if symbol in self._market_subscriptions:
                continue
            try:
                req_id_obj = subscribe_fn(symbol, self._on_realtime_bar, bar_size=5)
            except NotImplementedError:
                self.logger.info('Broker does not support real-time bars')
                return
            except Exception as exc:
                self.logger.warning(f'Real-time subscription failed for {symbol}: {exc}')
                continue
            if not isinstance(req_id_obj, int):
                self.logger.warning(f'Real-time subscription returned non-int req_id for {symbol}: {req_id_obj!r}')
                continue
            req_id = req_id_obj
            self._market_subscriptions[symbol] = req_id
            self.logger.info(f'Subscribed to real-time bars: {symbol} (req_id={req_id})')

    def _stop_market_data(self) -> None:
        unsubscribe_fn = getattr(self.broker, 'unsubscribe', None)
        if callable(unsubscribe_fn):
            for req_id in list(self._market_subscriptions.values()):
                try:
                    unsubscribe_fn(req_id)
                except Exception:
                    continue
        self._market_subscriptions.clear()
        self._aggregators.clear()

    def _trigger_stop_async(self) -> None:
        """Start a single background thread that calls stop() to perform a graceful shutdown.

        If a stop thread is already running, this is a no-op; otherwise it launches a daemon
        thread named 'TradingCoordinatorStop' that invokes stop().
        """
        with self._stop_lock:
            if self._stop_thread_started:
                return
            self._stop_thread_started = True
        threading.Thread(target=self.stop, daemon=True, name='TradingCoordinatorStop').start()

    def _on_realtime_bar(
        self,
        timestamp: datetime,
        symbol: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Handle a single realtime tick by updating latest price and aggregating into timeframe buckets.

        If a completed bucket is produced for a timeframe, a Bar is constructed and routed to
        process_bar when it matches the decision timeframe or to the timeframe manager otherwise.
        """
        # Keep last prices fresh even between decision bars.
        with suppress(Exception):
            self.bar_processor.update_price(symbol, Decimal(str(close)))

        symbol_aggregators = self._aggregators.get(symbol)
        if not symbol_aggregators:
            return

        for timeframe, aggregator in symbol_aggregators.items():
            completed = aggregator.update(timestamp, open_, high, low, close, volume)
            if completed is None:
                continue

            bar = Bar(
                symbol=symbol,
                timestamp=completed.timestamp,
                open=Decimal(str(completed.open)),
                high=Decimal(str(completed.high)),
                low=Decimal(str(completed.low)),
                close=Decimal(str(completed.close)),
                volume=int(completed.volume),
            )

            if timeframe == self._decision_timeframe:
                self.process_bar(bar, timeframe=timeframe)
            else:
                self._forward_timeframe_bar(bar, timeframe)

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
                adjust_fn = getattr(self.risk, 'adjust_for_withdrawal', None)
                if callable(adjust_fn):
                    adjust_fn(withdrawn)
                self.logger.info(f'Withdrew ${float(withdrawn):.2f} in profits')
                # Record in analytics
                equity = self.portfolio.total_equity(last_prices)
                self._last_equity = Decimal(str(equity))
                self.analytics.record_equity(current_time, self._last_equity)

            self._last_withdrawal_check = current_time

        except Exception as exc:
            self.logger.error(f'Capital withdrawal check failed: {exc}')

    def _check_rollover_alerts(self, timestamp: datetime) -> None:
        """Check for futures contract rollover alerts (hourly)."""
        if self.rollover_manager is None:
            return

        # Check once per hour
        if self._last_rollover_check:
            hours_since = (timestamp - self._last_rollover_check).total_seconds() / 3600
            if hours_since < 1.0:
                return

        self._last_rollover_check = timestamp

        # Get futures contracts from broker config
        if not self.config.broker or not self.config.broker.contracts:
            return

        # Build FuturesContractSpec dict from config
        try:
            from ..futures.contracts import FuturesContractSpec

            futures_contracts: dict[str, FuturesContractSpec] = {}
            for symbol, spec in self.config.broker.contracts.items():
                if spec.sec_type != 'FUT':
                    continue

                futures_spec = FuturesContractSpec(
                    symbol=spec.symbol,
                    sec_type=spec.sec_type,
                    exchange=spec.exchange,
                    currency=spec.currency,
                    local_symbol=spec.local_symbol,
                    multiplier=spec.multiplier,
                    expiration_date=spec.expiration_date,
                    con_id=spec.con_id,
                    underlying=spec.underlying,
                )
                futures_contracts[symbol] = futures_spec

            if not futures_contracts:
                return

            # Check for rollover alerts
            alerts = self.rollover_manager.check_rollover_needed(futures_contracts)
            for alert in alerts:
                urgency = alert.get('urgency', 'warning')
                days = alert.get('days_to_expiry', 0)
                symbol = alert.get('symbol', '')
                recommendation = alert.get('recommendation', '')

                if urgency == 'critical':
                    self.logger.warning(f'CRITICAL: Futures contract {symbol} expires in {days} days! {recommendation}')
                else:
                    self.logger.info(f'Rollover alert: {symbol} expires in {days} days - {recommendation}')

        except Exception as exc:
            self.logger.error(f'Rollover alert check failed: {exc}')

    def snapshot(self) -> dict[str, Any]:
        """Get current session state."""
        last_prices = self.bar_processor.get_all_prices()

        trade_log = self.portfolio.get_trade_log_snapshot(limit=1000)
        trades = [entry for entry in trade_log if entry.get('type') == 'TRADE']

        fsd_total_trades = getattr(self.decision_engine, 'session_trades', len(trades))
        fsd_payload = {
            'total_trades': int(fsd_total_trades) if isinstance(fsd_total_trades, (int, float)) else len(trades)
        }

        positions: list[dict[str, object]] = []
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
            'trades': trades,
            'fsd': fsd_payload,
        }
