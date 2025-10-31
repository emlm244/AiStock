from __future__ import annotations

import os
import queue
import threading
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any

from .brokers.base import BaseBroker
from .brokers.ibkr import IBKRBroker
from .brokers.paper import PaperBroker
from .calendar import is_trading_time
from .config import BacktestConfig
from .data import Bar
from .edge_cases import EdgeCaseHandler
from .execution import ExecutionReport, Order, OrderSide, OrderType
from .fsd import FSDConfig, FSDEngine
from .idempotency import OrderIdempotencyTracker
from .logging import configure_logger
from .patterns import PatternDetector
from .persistence import load_checkpoint, save_checkpoint
from .portfolio import Portfolio
from .professional import ProfessionalSafeguards
from .risk import RiskEngine, RiskViolation
from .timeframes import TimeframeManager
from .universe import UniverseSelectionResult, UniverseSelector


class LiveTradingSession:
    """
    Orchestrates live or paper trading using the shared strategy/risk pipeline.

    PROFESSIONAL ENHANCEMENTS:
    - Multi-timeframe analysis
    - Candlestick pattern recognition
    - Professional trading safeguards
    """

    def __init__(
        self,
        config: BacktestConfig,
        fsd_config: FSDConfig | None = None,
        checkpoint_dir: str = 'state',
        enable_checkpointing: bool = True,
        restore_from_checkpoint: bool = False,
        minimum_balance: float = 0.0,
        minimum_balance_enabled: bool = True,
        timeframes: list[str] | None = None,
        enable_professional_features: bool = True,
        safeguard_config: dict[str, Any] | None = None,
        risk_limit_overrides: dict[str, float] | None = None,
    ) -> None:
        self.config = config
        self.fsd_config = fsd_config
        self.universe_selection: UniverseSelectionResult | None = None

        self._safeguard_config = safeguard_config or {}
        self._risk_limit_overrides = risk_limit_overrides or {}

        # P2-4 Fix: Validate configurations on startup
        self.config.validate()
        if self.fsd_config:
            self.fsd_config.validate()

        # NEW: Minimum balance protection
        self.minimum_balance = Decimal(str(minimum_balance))
        self.minimum_balance_enabled = minimum_balance_enabled

        if config.data.symbols:
            resolved_symbols = list(config.data.symbols)
        else:
            if not config.universe:
                raise ValueError(
                    'Live session requires DataSource.symbols or a UniverseConfig for automatic selection.'
                )
            selector = UniverseSelector(config.data, config.engine.data_quality)
            selection = selector.select(config.universe)
            if not selection.symbols:
                raise ValueError('Universe selector did not return any tradable symbols.')
            resolved_symbols = selection.symbols
            self.universe_selection = selection

        self.symbols = resolved_symbols
        self.logger = configure_logger('LiveSession', structured=True)
        self.checkpoint_dir = checkpoint_dir
        self.enable_checkpointing = enable_checkpointing

        if self.universe_selection:
            self.logger.info(
                'universe_selected',
                extra={
                    'symbols': self.universe_selection.symbols,
                    'scores': self.universe_selection.scores,
                },
            )

        # P0 Fix: Restore from checkpoint if requested
        if restore_from_checkpoint:
            try:
                self.portfolio, risk_state = load_checkpoint(checkpoint_dir)
                self.risk = RiskEngine(
                    config.engine.risk,
                    self.portfolio,
                    config.data.bar_interval,
                    state=risk_state,
                    minimum_balance=self.minimum_balance,
                    minimum_balance_enabled=self.minimum_balance_enabled,
                )
                self.logger.info(
                    'restored_from_checkpoint',
                    extra={
                        'cash': float(self.portfolio.get_cash()),
                        'positions': self.portfolio.position_count(),
                        'checkpoint_dir': checkpoint_dir,
                    },
                )
            except FileNotFoundError as exc:
                self.logger.warning('checkpoint_not_found', extra={'error': str(exc)})
                self.portfolio = Portfolio(cash=Decimal(str(config.engine.initial_equity)))
                self.risk = RiskEngine(
                    config.engine.risk,
                    self.portfolio,
                    config.data.bar_interval,
                    minimum_balance=self.minimum_balance,
                    minimum_balance_enabled=self.minimum_balance_enabled,
                )
        else:
            self.portfolio = Portfolio(cash=Decimal(str(config.engine.initial_equity)))
            self.risk = RiskEngine(
                config.engine.risk,
                self.portfolio,
                config.data.bar_interval,
                minimum_balance=self.minimum_balance,
                minimum_balance_enabled=self.minimum_balance_enabled,
            )

        self._apply_risk_overrides()

        self.history: dict[str, list[Bar]] = defaultdict(list)
        self.last_prices: dict[str, Decimal] = {}
        self._lock = threading.Lock()
        self.trade_log: list[dict[str, object]] = []
        self.equity_curve: list[tuple[datetime, Decimal]] = []
        self._last_equity = Decimal(str(config.engine.initial_equity))

        # P0 Fix: Order idempotency tracker
        self.idempotency_tracker = OrderIdempotencyTracker(storage_path=f'{checkpoint_dir}/submitted_orders.json')

        # Enhancement: Track order submission times for fill reconciliation
        self._order_submission_times: dict[int, datetime] = {}  # order_id -> submission_time

        # P0 Fix: Reconciliation state
        self._last_reconciliation_time: datetime | None = None
        self._reconciliation_interval = timedelta(hours=1)  # Reconcile hourly

        if not config.broker:
            raise ValueError('Broker configuration is required')
        backend = config.broker.backend.lower()
        if backend == 'paper':
            broker: BaseBroker = PaperBroker(config.execution)
        elif backend == 'ibkr':
            broker = IBKRBroker(config.broker)
        else:
            raise ValueError(f'Unknown broker backend: {config.broker.backend}')

        self.broker = broker
        self.broker.set_fill_handler(self._handle_fill)

        self._subscriptions: dict[str, int] = {}
        self._running = False
        self._reconciliation_alerts: list[dict[str, object]] = []

        # PROFESSIONAL MODULES: Initialize if enabled
        self.timeframes = timeframes or ['1m']
        self.enable_professional_features = enable_professional_features

        # P0-2a Fix: EDGE CASE HANDLER IS MANDATORY (safety-critical)
        # Always initialize edge case handler regardless of professional features setting
        self.edge_case_handler = EdgeCaseHandler()
        self.logger.info('edge_case_handler_initialized', extra={'mandatory': True})

        # Create professional modules (optional enhancements)
        self.timeframe_manager: TimeframeManager | None = None
        self.pattern_detector: PatternDetector | None = None
        self.safeguards: ProfessionalSafeguards | None = None

        if enable_professional_features:
            # Multi-timeframe manager
            self.timeframe_manager = TimeframeManager(
                symbols=self.symbols,
                timeframes=self.timeframes,
                max_bars_per_timeframe=500,
            )
            self.logger.info(
                'timeframe_manager_initialized',
                extra={'symbols': len(self.symbols), 'timeframes': self.timeframes},
            )

            # Pattern detector
            self.pattern_detector = PatternDetector(body_threshold=0.3, wick_ratio=2.0)
            self.logger.info('pattern_detector_initialized')

            safeguard_params = {
                'max_trades_per_hour': int(self._safeguard_config.get('max_trades_per_hour', 20)),
                'max_trades_per_day': int(self._safeguard_config.get('max_trades_per_day', 100)),
                'chase_threshold_pct': float(self._safeguard_config.get('chase_threshold_pct', 5.0)),
                'news_volume_multiplier': float(self._safeguard_config.get('news_volume_multiplier', 5.0)),
                'end_of_day_minutes': int(self._safeguard_config.get('end_of_day_minutes', 30)),
            }
            self.safeguards = ProfessionalSafeguards(**safeguard_params)
            self.logger.info('professional_safeguards_initialized', extra=safeguard_params)

        # Initialize FSD engine (FSD-only system) with professional modules
        self.fsd_engine: FSDEngine
        self.fsd_session_stats: dict[str, object] = {}
        if not self.fsd_config:
            raise ValueError('fsd_config is required for FSD session')
        self.fsd_engine = FSDEngine(
            self.fsd_config,
            self.portfolio,
            timeframe_manager=self.timeframe_manager,
            pattern_detector=self.pattern_detector,
            safeguards=self.safeguards,
            edge_case_handler=self.edge_case_handler,
        )
        self.logger.info(
            'fsd_mode_initialized',
            extra={
                'max_capital': self.fsd_config.max_capital,
                'max_timeframe_seconds': self.fsd_config.max_timeframe_seconds,
                'professional_features': enable_professional_features,
            },
        )
        # Prepare persistent path for FSD brain (Q-values, performance)
        self.fsd_state_path = f'{checkpoint_dir}/fsd_state.json'

        # P0-4 Fix: Background checkpoint worker (prevents checkpoint race conditions)
        self._checkpoint_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=10)
        self._checkpoint_worker_running = True
        self._checkpoint_worker = threading.Thread(
            target=self._checkpoint_worker_loop,
            daemon=True,
            name='CheckpointWorker'
        )
        self._checkpoint_worker.start()
        self.logger.info('checkpoint_worker_started')

    def _apply_risk_overrides(self) -> None:
        """Apply user-provided risk limit overrides to the risk engine config."""
        if not self._risk_limit_overrides:
            return

        overrides = self._risk_limit_overrides
        updated: dict[str, float] = {}

        value = overrides.get('max_daily_loss_pct')
        if value is not None:
            val = max(0.0001, min(float(value), 1.0))
            self.risk.config.max_daily_loss_pct = val
            updated['max_daily_loss_pct'] = val

        value = overrides.get('max_drawdown_pct')
        if value is not None:
            val = max(0.0001, min(float(value), 1.0))
            self.risk.config.max_drawdown_pct = val
            updated['max_drawdown_pct'] = val

        if updated:
            self.logger.info('risk_limits_overridden', extra=updated)

    def _checkpoint_worker_loop(self) -> None:
        """
        P0-4 Fix: Background worker that processes checkpoint save requests.

        Runs in separate thread to avoid blocking trading pipeline.
        """
        while self._checkpoint_worker_running:
            try:
                # Block waiting for checkpoint request (1 sec timeout for shutdown check)
                checkpoint_data = self._checkpoint_queue.get(timeout=1.0)

                # None signal means shutdown
                if checkpoint_data is None:
                    break

                # Save checkpoint atomically
                try:
                    save_checkpoint(self.portfolio, self.risk.state, self.checkpoint_dir)
                    self.logger.debug('checkpoint_saved_async', extra={'checkpoint_dir': self.checkpoint_dir})
                except Exception as exc:
                    self.logger.error('checkpoint_save_failed_async', extra={'error': str(exc)})

                # Mark task done
                self._checkpoint_queue.task_done()

            except queue.Empty:
                # Timeout - check if still running
                continue
            except Exception as exc:
                self.logger.error('checkpoint_worker_error', extra={'error': str(exc)})

        self.logger.info('checkpoint_worker_stopped')

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self.broker.start()
        self._running = True

        # Start FSD session
        self.fsd_session_stats = self.fsd_engine.start_session()
        self.logger.info('fsd_session_started', extra=self.fsd_session_stats)
        # Attempt to restore prior learned state
        try:
            loaded = self.fsd_engine.load_state(
                getattr(self, 'fsd_state_path', f'{self.checkpoint_dir}/fsd_state.json')
            )
            if loaded:
                self.logger.info(
                    'fsd_state_loaded',
                    extra={
                        'path': getattr(self, 'fsd_state_path', f'{self.checkpoint_dir}/fsd_state.json'),
                        'q_values': len(self.fsd_engine.rl_agent.q_values),
                    },
                )
            else:
                self.logger.info(
                    'fsd_state_not_found',
                    extra={'path': getattr(self, 'fsd_state_path', f'{self.checkpoint_dir}/fsd_state.json')},
                )
        except Exception as exc:
            self.logger.warning('fsd_state_load_failed', extra={'error': str(exc)})

        # P2-1 Fix: Prune stale symbol confidence for symbols no longer in universe
        symbols_pruned = []
        for symbol in list(self.fsd_engine.symbol_performance.keys()):
            if symbol not in self.symbols:
                symbols_pruned.append(symbol)
                del self.fsd_engine.symbol_performance[symbol]

        if symbols_pruned:
            self.logger.info(
                'fsd_stale_symbols_pruned',
                extra={
                    'symbols_pruned': symbols_pruned,
                    'count': len(symbols_pruned),
                    'reason': 'not_in_current_universe',
                },
            )

        if isinstance(self.broker, IBKRBroker):  # subscribe to real-time bars
            from .timeframes import TIMEFRAME_TO_SECONDS

            for symbol in self.symbols:
                # PROFESSIONAL: 10-day historical warmup for each timeframe
                if hasattr(self.broker, 'fetch_historical_bars'):
                    for timeframe in self.timeframes:
                        try:
                            # Map timeframe to IBKR bar size
                            bar_size_seconds = TIMEFRAME_TO_SECONDS.get(timeframe, 60)

                            # Map seconds to IBKR bar size string
                            if bar_size_seconds < 60:
                                bar_size_str = f'{bar_size_seconds} secs'
                            elif bar_size_seconds == 60:
                                bar_size_str = '1 min'
                            elif bar_size_seconds < 3600:
                                bar_size_str = f'{bar_size_seconds // 60} mins'
                            elif bar_size_seconds == 3600:
                                bar_size_str = '1 hour'
                            elif bar_size_seconds == 86400:
                                bar_size_str = '1 day'
                            else:
                                bar_size_str = '1 min'  # Default

                            warmup_bars = self.broker.fetch_historical_bars(
                                symbol, duration='10 D', bar_size=bar_size_str
                            )

                            # MEDIUM FIX: Deduplicate warmup bars to avoid bias on restart
                            # Store in main history (for 1m) and timeframe manager (all timeframes)
                            if timeframe == '1m':
                                with self._lock:
                                    # Only extend if history is empty to avoid duplication on restart
                                    if not self.history[symbol]:
                                        self.history[symbol].extend(warmup_bars)
                                    else:
                                        # History exists - merge new warmup without duplicates
                                        existing_timestamps = {bar.timestamp for bar in self.history[symbol]}
                                        new_bars = [bar for bar in warmup_bars if bar.timestamp not in existing_timestamps]
                                        if new_bars:
                                            self.history[symbol].extend(new_bars)
                                            self.logger.info(
                                                'warmup_bars_merged',
                                                extra={'symbol': symbol, 'new_bars': len(new_bars), 'existing_bars': len(self.history[symbol])},
                                            )

                            # Feed to timeframe manager
                            if self.timeframe_manager:
                                for bar in warmup_bars:
                                    self.timeframe_manager.add_bar(symbol, timeframe, bar)

                            self.logger.info(
                                'historical_warmup_complete',
                                extra={'symbol': symbol, 'timeframe': timeframe, 'bars': len(warmup_bars)},
                            )
                        except Exception as exc:
                            self.logger.warning(
                                'historical_warmup_failed',
                                extra={'symbol': symbol, 'timeframe': timeframe, 'error': str(exc)},
                            )

                # PROFESSIONAL: Subscribe to real-time bars for each timeframe
                for timeframe in self.timeframes:
                    try:
                        bar_size_seconds = TIMEFRAME_TO_SECONDS.get(timeframe, 60)

                        # Create a handler that includes the timeframe
                        def make_handler(tf: str):
                            def handler(
                                ts: datetime, sym: str, o: float, h: float, low_price: float, c: float, v: float
                            ):
                                self._on_bar(ts, sym, o, h, low_price, c, v, timeframe=tf)

                            return handler

                        req_id = self.broker.subscribe_realtime_bars(
                            symbol, make_handler(timeframe), bar_size=bar_size_seconds
                        )
                        self._subscriptions[f'{symbol}_{timeframe}'] = req_id

                        self.logger.info(
                            'realtime_subscription_active',
                            extra={'symbol': symbol, 'timeframe': timeframe, 'req_id': req_id},
                        )
                    except Exception as exc:
                        self.logger.warning(
                            'realtime_subscription_failed',
                            extra={'symbol': symbol, 'timeframe': timeframe, 'error': str(exc)},
                        )
        else:
            self.logger.info('Paper broker active - feed bars manually via process_bar().')

    def stop(self) -> None:
        if not self._running:
            return

        # Enhancement: Report orphaned orders (submitted but never filled)
        if self._order_submission_times:
            orphaned_orders = list(self._order_submission_times.keys())
            self.logger.warning(
                'orphaned_orders_detected',
                extra={
                    'count': len(orphaned_orders),
                    'order_ids': orphaned_orders[:10],  # Log first 10
                    'note': 'orders_submitted_but_never_filled',
                },
            )
            self._order_submission_times.clear()

        # Persist learned brain for next session and end FSD session
        # (FSD-only system)
        try:
            os.makedirs(self.checkpoint_dir, exist_ok=True)
            self.fsd_engine.save_state(getattr(self, 'fsd_state_path', f'{self.checkpoint_dir}/fsd_state.json'))
            self.logger.info(
                'fsd_state_saved',
                extra={
                    'path': getattr(self, 'fsd_state_path', f'{self.checkpoint_dir}/fsd_state.json'),
                    'q_values': len(self.fsd_engine.rl_agent.q_values),
                },
            )
        except Exception as exc:
            self.logger.error('fsd_state_save_failed', extra={'error': str(exc)})

        end_stats = self.fsd_engine.end_session()
        self.logger.info('fsd_session_ended', extra=end_stats)

        # P0-4 Fix: Graceful checkpoint worker shutdown
        self.logger.info('stopping_checkpoint_worker')
        self._checkpoint_worker_running = False
        try:
            # Send shutdown signal (None)
            self._checkpoint_queue.put(None, timeout=2.0)
        except queue.Full:
            self.logger.warning('checkpoint_queue_full_on_shutdown')

        # P1 Enhancement: Wait for pending checkpoints with monitoring
        queue_size_before = self._checkpoint_queue.qsize()
        if queue_size_before > 0:
            self.logger.info('waiting_for_checkpoints', extra={'pending': queue_size_before})

        try:
            # Note: queue.join() blocks until all items processed (no timeout supported)
            # Worker thread timeout (below) provides the actual timeout mechanism
            self._checkpoint_queue.join()
            self.logger.info('checkpoint_queue_drained')
        except Exception as exc:
            self.logger.warning('checkpoint_queue_join_failed', extra={'error': str(exc)})

        # Wait for worker thread to finish (with timeout)
        if self._checkpoint_worker.is_alive():
            self._checkpoint_worker.join(timeout=3.0)
            if self._checkpoint_worker.is_alive():
                self.logger.warning('checkpoint_worker_did_not_stop_cleanly')

        # Final checkpoint save (blocking, to ensure state is persisted)
        if self.enable_checkpointing:
            try:
                save_checkpoint(self.portfolio, self.risk.state, self.checkpoint_dir)
                self.logger.info('final_checkpoint_saved')
            except Exception as exc:
                self.logger.error('final_checkpoint_failed', extra={'error': str(exc)})

        # Enhancement: Generate analytics reports on shutdown
        try:
            from .analytics import (
                export_drawdown_csv,
                export_symbol_performance_csv,
                generate_capital_sizing_report,
            )

            # Per-symbol performance CSV
            if self.trade_log and self.symbols:
                export_symbol_performance_csv(
                    self.trade_log, self.symbols, f'{self.checkpoint_dir}/symbol_performance.csv'
                )
                self.logger.info('analytics_exported', extra={'report': 'symbol_performance.csv'})

            # Drawdown analysis CSV
            if self.equity_curve:
                export_drawdown_csv(self.equity_curve, f'{self.checkpoint_dir}/drawdown_analysis.csv')
                self.logger.info('analytics_exported', extra={'report': 'drawdown_analysis.csv'})

            # Capital sizing guidance
            current_equity = self.portfolio.total_equity(self.last_prices)
            sizing_report = generate_capital_sizing_report(
                current_capital=Decimal(str(current_equity)),
                target_monthly_return_pct=10.0,  # User can adjust
                avg_monthly_return_pct=None,  # Will use conservative 1.5%
            )
            self.logger.info('capital_sizing_guidance', extra=sizing_report)

        except Exception as exc:
            self.logger.warning('analytics_export_failed', extra={'error': str(exc)})

        for symbol, req_id in list(self._subscriptions.items()):
            self.broker.unsubscribe(req_id)
            self._subscriptions.pop(symbol, None)
        self.broker.stop()
        self._running = False

    # ------------------------------------------------------------------
    def process_bar(self, bar: Bar) -> None:
        """Allows external feeds (e.g. simulation) to push bars in paper mode."""
        self._on_bar(
            bar.timestamp, bar.symbol, float(bar.open), float(bar.high), float(bar.low), float(bar.close), bar.volume
        )
        if isinstance(self.broker, PaperBroker):
            self.broker.process_bar(bar, bar.timestamp)

    # ------------------------------------------------------------------
    def _on_bar(
        self,
        timestamp: datetime,
        symbol: str,
        open_: float,
        high: float,
        low_price: float,
        close: float,
        volume: float,
        timeframe: str = '1m',
    ) -> None:
        bar = Bar(
            symbol=symbol,
            timestamp=timestamp,
            open=Decimal(str(open_)),
            high=Decimal(str(high)),
            low=Decimal(str(low_price)),
            close=Decimal(str(close)),
            volume=int(volume),
        )
        with self._lock:
            # Add to main history (for backward compatibility)
            history = self.history[symbol]
            history.append(bar)
            if len(history) > self.config.data.warmup_bars * 5:
                # keep memory bounded
                del history[: len(history) - self.config.data.warmup_bars * 5]
            self.last_prices[symbol] = bar.close

            # PROFESSIONAL: Feed to timeframe manager
            if self.timeframe_manager:
                self.timeframe_manager.add_bar(symbol, timeframe, bar)

        self._evaluate_signal(timestamp, symbol)

    def _evaluate_signal(self, timestamp: datetime, symbol: str) -> None:
        # P0 Fix: Skip signal evaluation outside trading hours
        if self.config.data.enforce_trading_hours and not is_trading_time(
            timestamp,
            exchange=self.config.data.exchange,
            allow_extended_hours=self.config.data.allow_extended_hours,
        ):
            self.logger.debug(
                'skip_non_trading_hour',
                extra={'timestamp': timestamp.isoformat(), 'symbol': symbol},
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

        # Always route to FSD engine (FSD-only system)
        self._evaluate_fsd_signal(timestamp, symbol, history, last_prices)
        return

    def _evaluate_fsd_signal(
        self, timestamp: datetime, symbol: str, history: list[Bar], last_prices: dict[str, Decimal]
    ) -> None:
        """FSD mode decision pipeline with crash protection."""
        # Protect FSD decision evaluation from crashes
        try:
            decision = self.fsd_engine.evaluate_opportunity(symbol, history, last_prices)
        except Exception as decision_error:
            # Log error and skip this bar - don't crash the session
            self.logger.error(
                'fsd_decision_error',
                extra={
                    'symbol': symbol,
                    'error': str(decision_error),
                    'error_type': type(decision_error).__name__,
                },
                exc_info=True,
            )
            return  # Skip this bar, continue session

        # Log AI decision with confidence breakdown
        self.logger.info(
            'fsd_decision',
            extra={
                'symbol': symbol,
                'should_trade': decision['should_trade'],
                'confidence': float(decision.get('confidence', 0.0)),
                'confidence_breakdown': decision.get('confidence_breakdown', {}),
                'reason': decision.get('reason'),
            },
        )

        # If AI decides not to trade, we're done
        if not decision['should_trade']:
            return

        # AI decided to trade - get action details
        action = decision.get('action', {})
        if not action:
            return

        # Calculate desired quantity based on AI's size_fraction and signal
        equity = self.portfolio.total_equity(last_prices)
        symbol_to_trade = action.get('symbol', symbol)

        trade_signal = int(action.get('signal', 0))
        if trade_signal == 0:
            return

        size_fraction_raw = Decimal(str(action.get('size_fraction', 0.0)))
        size_fraction = abs(size_fraction_raw)
        if size_fraction <= Decimal('0'):
            return

        with self._lock:
            symbol_history = list(self.history.get(symbol_to_trade, []))

        if not symbol_history:
            self.logger.warning('fsd_no_history', extra={'symbol': symbol_to_trade})
            return

        current_price = symbol_history[-1].close
        if current_price <= 0:
            self.logger.warning('fsd_invalid_price', extra={'symbol': symbol_to_trade, 'price': float(current_price)})
            return

        equity_decimal = Decimal(str(equity))
        max_capital = Decimal(str(self.fsd_config.max_capital)) if self.fsd_config else equity_decimal
        target_notional_base = equity_decimal * size_fraction
        if self.fsd_config:
            target_notional_base = min(target_notional_base, max_capital)

        current_position = self.portfolio.position(symbol_to_trade)
        current_symbol_exposure = abs(current_position.quantity) * current_price

        current_exposure = Decimal('0')
        positions_snapshot = self.portfolio.snapshot_positions()
        for sym, pos in positions_snapshot.items():
            price_value: Decimal | float | None = last_prices.get(sym)
            if price_value is None:
                price_value = pos.average_price
            if price_value is None:
                continue
            price_dec = Decimal(str(price_value))
            current_exposure += abs(pos.quantity) * price_dec

        exposure_without_symbol = current_exposure - current_symbol_exposure
        remaining_capital = max_capital - exposure_without_symbol
        if remaining_capital < Decimal('0'):
            remaining_capital = Decimal('0')

        exposure_headroom = remaining_capital
        if trade_signal < 0 and current_position.quantity > 0:
            exposure_headroom += current_symbol_exposure
        elif trade_signal > 0 and current_position.quantity < 0:
            exposure_headroom += current_symbol_exposure

        exposure_headroom = max(Decimal('0'), exposure_headroom)

        if exposure_headroom <= Decimal('0') and target_notional_base > Decimal('0'):
            self.logger.info(
                'fsd_capital_limit_reached',
                extra={
                    'symbol': symbol_to_trade,
                    'max_capital': float(max_capital),
                    'current_exposure': float(current_exposure),
                    'headroom': float(exposure_headroom),
                },
            )
            return

        allowed_notional = (
            min(target_notional_base, exposure_headroom) if target_notional_base > Decimal('0') else Decimal('0')
        )
        direction = Decimal('1') if trade_signal > 0 else Decimal('-1')
        target_notional = allowed_notional * direction
        desired_qty = target_notional / current_price

        current_delta = current_position.quantity
        delta = desired_qty - current_delta

        if abs(delta) < Decimal('1e-6'):
            return

        # IBKR supports fractional shares for 99.98% of stocks
        # Requirements: minimum $1.00 notional OR 0.00001 shares (whichever is greater)
        # Paper broker: Round to whole shares
        supports_fractional = isinstance(self.broker, IBKRBroker)

        if supports_fractional:
            # IBKR fractional share support (default for most stocks)
            trade_notional = abs(delta) * current_price

            # Enforce IBKR minimum: $1.00 notional
            if trade_notional < Decimal('1.00'):
                self.logger.info(
                    'fsd_order_too_small',
                    extra={
                        'symbol': symbol_to_trade,
                        'desired_qty': float(delta),
                        'notional_usd': float(trade_notional),
                        'reason': 'below_minimum_dollar_value',
                        'minimum_usd': 1.00,
                    },
                )
                return

            # Enforce IBKR minimum fractional size: 0.00001 shares
            if abs(delta) < Decimal('0.00001'):
                self.logger.info(
                    'fsd_order_too_small',
                    extra={
                        'symbol': symbol_to_trade,
                        'desired_qty': float(delta),
                        'reason': 'below_minimum_fractional_size',
                        'minimum_shares': 0.00001,
                    },
                )
                return

            # Fallback for edge case: If stock doesn't support fractional (0.02% of stocks)
            # Round up to 1 share, but only if notional stays reasonable
            if abs(delta) < Decimal('1'):
                rounded_up = Decimal('1') if delta > 0 else Decimal('-1')
                rounded_notional = abs(rounded_up) * current_price

                # Safety check: Don't let small fractional become huge whole share trade
                # Example: 0.02 shares of $500 stock = $10 fractional, but 1 share = $500 (50x increase!)
                notional_increase_ratio = rounded_notional / trade_notional if trade_notional > 0 else Decimal('0')
                if notional_increase_ratio > Decimal('10'):  # Max 10x increase
                    self.logger.warning(
                        'fsd_fractional_fallback_rejected',
                        extra={
                            'symbol': symbol_to_trade,
                            'desired_qty': float(delta),
                            'would_round_to': float(rounded_up),
                            'fractional_notional_usd': float(trade_notional),
                            'rounded_notional_usd': float(rounded_notional),
                            'increase_ratio': float(notional_increase_ratio),
                            'reason': 'rounding_would_increase_notional_too_much',
                        },
                    )
                    return

            # Allow fractional order (IBKR will handle it)
            # No rounding needed - IBKR accepts fractional

        else:
            # Paper broker: Round to whole shares (most simulators don't support fractional)
            delta_rounded = delta.quantize(Decimal('1'), rounding=ROUND_DOWN)

            # Skip if rounded quantity is less than 1 share
            if abs(delta_rounded) < Decimal('1'):
                self.logger.info(
                    'fsd_order_too_small',
                    extra={
                        'symbol': symbol_to_trade,
                        'desired_qty': float(delta),
                        'rounded_qty': float(delta_rounded),
                        'reason': 'paper_broker_requires_whole_shares',
                    },
                )
                return

            # Log rounding if significant (>1% difference)
            rounding_impact_pct = abs((delta - delta_rounded) / delta * 100) if delta != 0 else Decimal('0')
            if rounding_impact_pct > Decimal('1'):
                self.logger.info(
                    'fsd_order_rounded',
                    extra={
                        'symbol': symbol_to_trade,
                        'desired_qty': float(delta),
                        'rounded_qty': float(delta_rounded),
                        'impact_pct': float(rounding_impact_pct),
                    },
                )

            # Use rounded delta for paper broker
            delta = delta_rounded

        # Generate client order ID for idempotency
        client_order_id = self.idempotency_tracker.generate_client_order_id(symbol_to_trade, timestamp, delta)

        if self.idempotency_tracker.is_duplicate(client_order_id):
            self.logger.warning(
                'fsd_duplicate_order_skipped', extra={'symbol': symbol_to_trade, 'client_order_id': client_order_id}
            )
            return

        try:
            self.risk.check_pre_trade(symbol_to_trade, delta, current_price, equity_decimal, last_prices)
        except RiskViolation as err:
            self.logger.warning(
                'fsd_risk_violation',
                extra={'symbol': symbol_to_trade, 'reason': str(err)},
            )
            return
        except Exception as risk_error:
            self.logger.error(
                'fsd_risk_check_error',
                extra={
                    'symbol': symbol_to_trade,
                    'error': str(risk_error),
                    'error_type': type(risk_error).__name__,
                },
                exc_info=True,
            )
            return  # Skip this trade, continue session

        try:
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
                target_notional=float(target_notional),
                target_quantity=float(desired_qty),
            )

            # Record for rate limiting after successful risk check
            with suppress(Exception):
                self.risk.record_order_submission(timestamp)

            self.idempotency_tracker.mark_submitted(client_order_id)
            order_id = self.broker.submit(order)

            # Track submission time for reconciliation/warnings
            self._order_submission_times[order_id] = timestamp
        except Exception as submit_error:
            self.logger.error(
                'fsd_order_submission_error',
                extra={
                    'symbol': symbol_to_trade,
                    'error': str(submit_error),
                    'error_type': type(submit_error).__name__,
                },
                exc_info=True,
            )
            return  # Skip this trade, continue session

        self.logger.info(
            'fsd_order_submitted',
            extra={
                'symbol': symbol_to_trade,
                'order_id': order_id,
                'client_order_id': client_order_id,
                'qty': float(delta),
                'ai_confidence': float(decision.get('confidence', 0.0)),
            },
        )

    def _handle_fill(self, report: ExecutionReport) -> None:
        signed_qty = report.quantity if report.side == OrderSide.BUY else -report.quantity
        position_before = float(self.portfolio.position(report.symbol).quantity)
        realised = self.portfolio.apply_fill(report.symbol, signed_qty, report.price, Decimal('0'), report.timestamp)
        position_after = float(self.portfolio.position(report.symbol).quantity)
        with self._lock:
            self.last_prices[report.symbol] = report.price
        equity_now = self.portfolio.total_equity(self.last_prices)
        self.risk.register_trade(realised, Decimal('0'), report.timestamp, Decimal(str(equity_now)), self.last_prices)
        self._last_equity = Decimal(str(equity_now))
        self.equity_curve.append((report.timestamp, self._last_equity))
        self.trade_log.append(
            {
                'timestamp': report.timestamp,
                'symbol': report.symbol,
                'quantity': float(signed_qty),
                'price': float(report.price),
                'realised_pnl': float(realised),
            }
        )
        if len(self.trade_log) > 1000:
            del self.trade_log[: len(self.trade_log) - 1000]

        # Drop tracked submission record (used for orphan detection)
        if report.order_id in self._order_submission_times:
            self._order_submission_times.pop(report.order_id, None)

        self.logger.info(
            'fill',
            extra={
                'order_id': report.order_id,
                'symbol': report.symbol,
                'qty': float(signed_qty),
                'price': float(report.price),
                'equity': float(equity_now),
            },
        )

        # CRITICAL-2 Fix: FSD learning with error recovery - ALWAYS attempt learning
        try:
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
                'fsd_learning_update',
                extra={'symbol': report.symbol, 'pnl': float(realised), 'total_trades': len(self.fsd_engine.trade_history)},
            )
        except Exception as learning_error:
            # CRITICAL-2: Never let learning errors prevent trade recording
            self.logger.error(
                'fsd_learning_error',
                extra={
                    'symbol': report.symbol,
                    'error': str(learning_error),
                    'error_type': type(learning_error).__name__,
                    'pnl': float(realised),
                },
                exc_info=True,
            )
            # Continue execution - trade is still valid, learning just failed for this update

        # P0-4 Fix: Schedule non-blocking checkpoint save (async via background worker)
        if self.enable_checkpointing:
            try:
                # Put checkpoint request in queue (non-blocking if queue not full)
                self._checkpoint_queue.put_nowait({})  # Empty dict is signal to save
            except queue.Full:
                # Queue full - checkpoint already pending, skip this one
                self.logger.warning('checkpoint_queue_full', extra={'checkpoint_dir': self.checkpoint_dir})
            except Exception as exc:
                self.logger.error('checkpoint_schedule_failed', extra={'error': str(exc)})

    def _should_reconcile(self, timestamp: datetime) -> bool:
        """P0 Fix: Check if it's time for periodic position reconciliation."""
        if self._last_reconciliation_time is None:
            return True
        current_ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        last_ts = (
            self._last_reconciliation_time
            if self._last_reconciliation_time.tzinfo
            else self._last_reconciliation_time.replace(tzinfo=timezone.utc)
        )
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
            # Normalize timestamp once
            as_of_utc = as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
            as_of_iso = as_of_utc.isoformat()

            broker_positions = self.broker.get_positions()
            positions_snapshot = self.portfolio.snapshot_positions()
            internal_positions = {
                sym: (float(pos.quantity), float(pos.average_price))
                for sym, pos in positions_snapshot.items()
            }

            mismatches = []
            # Check internal vs broker
            for symbol, (internal_qty, _) in internal_positions.items():
                broker_qty, _ = broker_positions.get(symbol, (0.0, 0.0))
                if abs(internal_qty - broker_qty) > 0.001:
                    mismatches.append(
                        {
                            'symbol': symbol,
                            'internal_qty': internal_qty,
                            'broker_qty': broker_qty,
                            'delta': internal_qty - broker_qty,
                        }
                    )

            # Check portfolio positions missing on broker
            for symbol, pos in positions_snapshot.items():
                if symbol not in broker_positions:
                    qty = float(pos.quantity)
                    if abs(qty) > 0.001:
                        mismatches.append(
                            {'symbol': symbol, 'internal_qty': qty, 'broker_qty': 0.0, 'delta': qty}
                        )

            # Check broker positions not in internal
            for symbol, (broker_qty, _) in broker_positions.items():
                if symbol not in internal_positions and abs(broker_qty) > 0.001:
                    mismatches.append(
                        {'symbol': symbol, 'internal_qty': 0.0, 'broker_qty': broker_qty, 'delta': -broker_qty}
                    )

            if mismatches:
                # P0-5 Enhancement: Check for large mismatches (>= 10% indicates serious problem)
                critical_mismatches = []
                for mismatch in mismatches:
                    broker_qty = mismatch['broker_qty']
                    delta = abs(mismatch['delta'])
                    # Calculate percentage difference (relative to broker truth)
                    if broker_qty != 0:
                        pct_diff = (delta / abs(broker_qty)) * 100
                    else:
                        # If broker has 0 but internal has non-zero, that's 100% difference
                        pct_diff = 100.0 if delta > 0 else 0.0

                    if pct_diff >= 10.0:  # >= 10% difference is critical
                        critical_mismatches.append({**mismatch, 'pct_diff': pct_diff})

                if critical_mismatches:
                    # CRITICAL: Large position mismatch - halt trading
                    self.logger.error(
                        'reconciliation_critical_mismatch',
                        extra={
                            'critical_mismatches': critical_mismatches,
                            'count': len(critical_mismatches),
                            'as_of': as_of_iso,
                            'action': 'halting_trading',
                        },
                    )
                    # Halt trading - this indicates data corruption or serious broker sync issue
                    self.risk.halt(
                        f'Critical position mismatch detected: {len(critical_mismatches)} positions with >=10% difference'
                    )
                else:
                    # Minor mismatches - log warning but continue trading
                    self.logger.warning(
                        'reconciliation_mismatch',
                        extra={'mismatches': mismatches, 'count': len(mismatches), 'as_of': as_of_iso},
                    )

                self._reconciliation_alerts.extend([{**m, 'as_of': as_of_iso} for m in mismatches])
            else:
                self.logger.info('reconciliation_ok', extra={'positions': len(internal_positions), 'as_of': as_of_iso})

            self._last_reconciliation_time = as_of_utc

        except Exception as exc:
            self.logger.error('reconciliation_failed', extra={'error': str(exc)})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            portfolio_positions = self.portfolio.snapshot_positions()
            positions = []
            for symbol, position in portfolio_positions.items():
                positions.append(
                    {
                        'symbol': symbol,
                        'quantity': float(position.quantity),
                        'avg_price': float(position.average_price),
                        'last_update': position.last_update_utc,
                    }
                )
            trades = list(self.trade_log[-100:])
            prices = {sym: float(price) for sym, price in self.last_prices.items()}

        equity_curve = list(self.equity_curve)

        risk_state = {
            'halted': self.risk.is_halted(),
            'halt_reason': self.risk.halt_reason(),
            'daily_pnl': float(self.risk.state.daily_pnl),
            'peak_equity': float(self.risk.state.peak_equity),
            'weekly_loss_pct': float(self._compute_weekly_loss_pct()),
        }

        # Add FSD stats (FSD-only system)
        fsd_stats = {}
        if self.fsd_engine:
            fsd_stats = {
                'mode': 'fsd',
                'total_trades': len(self.fsd_engine.trade_history),
                'q_values_learned': len(self.fsd_engine.rl_agent.q_values),
                'exploration_rate': self.fsd_engine.rl_agent.exploration_rate,
                'win_rate': self._compute_fsd_win_rate(),
                'avg_pnl': self._compute_fsd_avg_pnl(),
                'experience_buffer': len(self.fsd_engine.rl_agent.experience_buffer),
                'last_trade_time': self.fsd_engine.last_trade_timestamp.isoformat()
                if self.fsd_engine.last_trade_timestamp
                else None,
            }
        else:
            fsd_stats = {'mode': 'fsd'}

        return {
            'positions': positions,
            'trades': trades,
            'prices': prices,
            'equity': float(self._last_equity),
            'cash': float(self.portfolio.get_cash()),
            'risk': risk_state,
            'reconciliation_alerts': list(self._reconciliation_alerts[-10:]),  # Last 10 alerts
            'equity_curve': [(ts, float(eq)) for ts, eq in equity_curve],
            'fsd': fsd_stats,
        }

    def _compute_fsd_win_rate(self) -> float:
        """Calculate FSD win rate from trade history."""
        if not self.fsd_engine or not getattr(self.fsd_engine, 'trade_history', None):
            return 0.0

        def _pnl(trade: dict[str, Any] | object) -> float:
            if isinstance(trade, dict):
                return float(trade.get('pnl', 0.0))
            try:
                return float(getattr(trade, 'pnl', 0.0))
            except (AttributeError, TypeError):
                return 0.0

        history = list(self.fsd_engine.trade_history)
        if not history:
            return 0.0
        winning_trades = sum(1 for t in history if _pnl(t) > 0)
        return winning_trades / len(history)

    def _compute_fsd_avg_pnl(self) -> float:
        """Calculate FSD average PnL from trade history."""
        if not self.fsd_engine or not getattr(self.fsd_engine, 'trade_history', None):
            return 0.0

        def _pnl(trade: dict[str, Any] | object) -> float:
            if isinstance(trade, dict):
                return float(trade.get('pnl', 0.0))
            try:
                return float(getattr(trade, 'pnl', 0.0))
            except (AttributeError, TypeError):
                return 0.0

        history = list(self.fsd_engine.trade_history)
        if not history:
            return 0.0
        total_pnl = sum(_pnl(t) for t in history)
        return total_pnl / len(history)

    def apply_adaptive_config(self, new_config: BacktestConfig) -> None:
        """
        Allow adaptive controllers to adjust strategy/risk parameters at runtime.

        The broker connectivity layer is left untouched; this only refreshes
        strategy logic and risk limits while preserving current portfolio state.
        """
        with self._lock:
            self.config = new_config
            # Preserve existing risk state but update limits/clock interval.
            # NEW: Preserve minimum balance settings
            self.risk = RiskEngine(
                new_config.engine.risk,
                self.portfolio,
                new_config.data.bar_interval,
                state=self.risk.state,
                minimum_balance=self.minimum_balance,
                minimum_balance_enabled=self.minimum_balance_enabled,
            )

    def _compute_weekly_loss_pct(self) -> Decimal:
        """Approximate weekly loss using the last five equity curve points."""
        if len(self.equity_curve) < 2:
            return Decimal('0')
        recent = self.equity_curve[-min(5, len(self.equity_curve)) :]
        start_equity = recent[0][1]
        end_equity = recent[-1][1]
        if start_equity == 0:
            return Decimal('0')
        return (end_equity - start_equity) / start_equity
