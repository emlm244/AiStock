from __future__ import annotations

import itertools
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from ..config import BrokerConfig, ContractSpec
from ..data import Bar  # For optional historical bars
from ..execution import ExecutionReport, Order, OrderSide, OrderType
from ..logging import configure_logger
from .base import BaseBroker

try:  # pragma: no cover - ibapi not available in test environment
    from ibapi.client import EClient  # type: ignore[assignment]
    from ibapi.contract import Contract  # type: ignore[assignment,no-redef]
    from ibapi.order import Order as IBOrder  # type: ignore[assignment,no-redef]
    from ibapi.wrapper import EWrapper  # type: ignore[assignment]

    _IBAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - handled gracefully at runtime

    class _DummyWrapper:  # pragma: no cover
        pass

    class _DummyClient:  # pragma: no cover
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class Contract:  # type: ignore[no-redef]  # pragma: no cover
        """Dummy Contract for type checking when ibapi not available."""

        symbol: str = ''
        secType: str = ''  # noqa: N815 - IBAPI convention
        exchange: str = ''
        currency: str = ''
        localSymbol: str = ''  # noqa: N815 - IBAPI convention
        multiplier: str = ''
        account: str = ''

    class IBOrder:  # type: ignore[no-redef]  # pragma: no cover
        """Dummy IBOrder for type checking when ibapi not available."""

        action: str = ''
        totalQuantity: float = 0.0  # noqa: N815 - IBAPI convention
        orderType: str = ''  # noqa: N815 - IBAPI convention
        lmtPrice: float = 0.0  # noqa: N815 - IBAPI convention
        auxPrice: float = 0.0  # noqa: N815 - IBAPI convention
        tif: str = ''
        transmit: bool = True

    EClient = _DummyClient  # type: ignore[misc,assignment]
    EWrapper = _DummyWrapper  # type: ignore[misc,assignment]
    _IBAPI_AVAILABLE = False

IBAPI_AVAILABLE = _IBAPI_AVAILABLE  # Export as constant


class IBKRBroker(BaseBroker, EWrapper, EClient):  # type: ignore[misc]  # pragma: no cover - requires IB connection
    """
    Thin adapter around Interactive Brokers' API.
    """

    def __init__(self, config: BrokerConfig):
        if not IBAPI_AVAILABLE:
            raise RuntimeError('ibapi is not installed. Install it via `pip install ibapi`.')

        BaseBroker.__init__(self)
        EWrapper.__init__(self)
        EClient.__init__(self, self)

        self._config = config
        self._logger = configure_logger('IBKRBroker', structured=True)

        self._thread: threading.Thread | None = None
        self._connected = threading.Event()
        self._next_order_id_ready = threading.Event()
        self._next_order_id = 1
        self._order_lock = threading.Lock()  # Protects _next_order_id and _order_symbol
        self._req_id_seq = itertools.count(start=1000)
        self._market_handlers: dict[
            int, tuple[str, Callable[[datetime, str, float, float, float, float, float], None]]
        ] = {}
        self._market_lock = threading.Lock()  # Protects _market_handlers
        self._order_symbol: dict[int, str] = {}

        # P1-1 Fix: Track subscription details for re-subscription after reconnect
        self._active_subscriptions: dict[
            str, tuple[Callable[[datetime, str, float, float, float, float, float], None], int]
        ] = {}  # symbol -> (handler, bar_size)

        # P0 Fix: Position reconciliation state
        self._positions: dict[str, tuple[float, float]] = {}  # symbol -> (quantity, avg_price)
        self._positions_lock = threading.Lock()  # Protect position updates
        self._positions_ready = threading.Event()

        # P1 Enhancement: Auto-reconnect with heartbeat
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._last_heartbeat: datetime | None = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_backoff_base = 2.0  # Exponential backoff

        # Historical data buffers (per request)
        self._hist_buffers: dict[int, list[Bar]] = {}
        self._hist_ready: dict[int, threading.Event] = {}
        self._hist_symbol: dict[int, str] = {}

    # --- Lifecycle -----------------------------------------------------
    def start(self) -> None:
        """
        P1 Enhancement: Start with heartbeat monitoring and auto-reconnect.
        """
        if self.isConnected():
            return
        self._connect_with_retry()
        # P1: Start heartbeat monitor
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_monitor, daemon=True, name='IBKRHeartbeat')
        self._heartbeat_thread.start()

    def stop(self) -> None:
        """
        P1 Enhancement: Stop with heartbeat cleanup.
        """
        # P1: Stop heartbeat first
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
            self._heartbeat_thread = None

        if self.isConnected():
            self._logger.info('Disconnecting IBKR')
            self.disconnect()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._connected.clear()

    def _connect_with_retry(self) -> None:
        """
        P1 Enhancement: Connect with exponential backoff retry.
        P1-1 Fix: Re-subscribes to bars after successful reconnection.
        """
        import time

        for attempt in range(self._max_reconnect_attempts):
            try:
                self._logger.info(
                    'Connecting to IBKR',
                    extra={'host': self._config.ib_host, 'port': self._config.ib_port, 'attempt': attempt + 1},
                )
                self.connect(self._config.ib_host, self._config.ib_port, self._config.ib_client_id)
                self._thread = threading.Thread(target=self.run, daemon=True, name='IBKRClientLoop')
                self._thread.start()

                if self._connected.wait(timeout=10):
                    self.reqIds(-1)  # trigger nextValidId callback
                    self._reconnect_attempts = 0  # Reset on success
                    self._last_heartbeat = datetime.now(timezone.utc)
                    self._logger.info('IBKR connected successfully')

                    # P1-1 Fix: Re-subscribe to all active bar subscriptions
                    self._resubscribe_all()

                    return

                # Timeout - retry with backoff
                backoff = self._reconnect_backoff_base**attempt
                self._logger.warning(
                    'Connection timeout, retrying',
                    extra={'attempt': attempt + 1, 'backoff_sec': backoff},
                )
                time.sleep(backoff)

            except Exception as exc:
                backoff = self._reconnect_backoff_base**attempt
                self._logger.error(
                    'Connection failed',
                    extra={'attempt': attempt + 1, 'error': str(exc), 'backoff_sec': backoff},
                )
                time.sleep(backoff)

        raise ConnectionError(f'Failed to connect after {self._max_reconnect_attempts} attempts')

    def _resubscribe_all(self) -> None:
        """
        P1-1 Fix: Re-subscribe to all active bar subscriptions after reconnection.

        Called automatically after successful reconnection to restore data streams.
        """
        if not self._active_subscriptions:
            return  # No subscriptions to restore

        self._logger.info(
            'resubscribing_after_reconnect',
            extra={'subscription_count': len(self._active_subscriptions)},
        )

        # Clear old handlers (old request IDs are invalid after reconnect) - thread-safe
        with self._market_lock:
            self._market_handlers.clear()

        # Re-subscribe to each symbol with stored handler and bar_size
        for symbol, (handler, bar_size) in list(self._active_subscriptions.items()):
            try:
                contract = self._build_contract(symbol)
                req_id = next(self._req_id_seq)

                # Thread-safe handler registration
                with self._market_lock:
                    self._market_handlers[req_id] = (symbol, handler)

                self.reqRealTimeBars(req_id, contract, bar_size, 'TRADES', True, [])
                self._logger.info(
                    'resubscribed_realtime_bars',
                    extra={'symbol': symbol, 'bar_size': bar_size, 'req_id': req_id},
                )
            except Exception as exc:
                self._logger.error(
                    'resubscription_failed',
                    extra={'symbol': symbol, 'error': str(exc)},
                )

    def _heartbeat_monitor(self) -> None:
        """
        P1 Enhancement: Monitor connection health and auto-reconnect.
        P1-1 Fix: Reconnection now restores bar subscriptions.
        P1 Enhancement: More conservative timeouts per IBKR recommendations.

        Checks connection every 60 seconds. If no activity for 120 seconds, reconnects.
        """
        import time

        while not self._heartbeat_stop.is_set():
            time.sleep(60)  # P1 Fix: Check every 60 seconds (less aggressive)

            if not self.isConnected():
                self._logger.warning('Heartbeat: Connection lost, attempting reconnect')
                try:
                    self._connect_with_retry()  # P1-1: Now includes re-subscription
                except Exception as exc:
                    self._logger.error('Heartbeat: Reconnect failed', extra={'error': str(exc)})

            # Check if we've received any activity recently
            if self._last_heartbeat:
                elapsed = (datetime.now(timezone.utc) - self._last_heartbeat).total_seconds()
                if elapsed > 120:  # P1 Fix: No activity for 120 seconds (more conservative)
                    self._logger.warning(
                        'Heartbeat: No activity detected, forcing reconnect',
                        extra={'elapsed_sec': elapsed},
                    )
                    try:
                        self.disconnect()
                        self._connect_with_retry()  # P1-1: Now includes re-subscription
                    except Exception as exc:
                        self._logger.error('Heartbeat: Force reconnect failed', extra={'error': str(exc)})

    # --- Order interface -----------------------------------------------
    def submit(self, order: Order) -> int:
        self._ensure_connected()
        if not self._next_order_id_ready.wait(timeout=5):
            raise TimeoutError('Order id not received from IBKR.')
        with self._order_lock:
            order_id = self._next_order_id
            self._next_order_id += 1
            # Store order symbol mapping while holding lock
            self._order_symbol[order_id] = order.symbol
        contract = self._build_contract(order.symbol)
        ib_order = self._build_order(order)
        self.placeOrder(order_id, contract, ib_order)
        return order_id

    def cancel(self, order_id: int) -> bool:
        self._ensure_connected()
        self.cancelOrder(order_id)
        return True

    def cancel_all_orders(self) -> int:
        """Cancel all pending orders using IBKR's global cancel.

        Returns:
            Number of orders cancelled (approximate, based on tracked orders)
        """
        self._ensure_connected()
        # Get count before cancelling
        with self._order_lock:
            num_orders = len(self._order_symbol)
            # Clear tracking dict since all orders will be cancelled
            self._order_symbol.clear()

        # Use IBKR's global cancel function
        self.reqGlobalCancel()
        self._logger.info('global_cancel_requested', extra={'tracked_orders': num_orders})
        return num_orders

    # --- Market data subscription --------------------------------------
    def subscribe_realtime_bars(
        self,
        symbol: str,
        handler: Callable[[datetime, str, float, float, float, float, float], None],
        bar_size: int = 5,
    ) -> int:
        """
        Subscribe to real-time bars (seconds resolution).

        P1-1 Fix: Stores subscription details for re-subscription after reconnect.
        """
        self._ensure_connected()
        contract = self._build_contract(symbol)
        req_id = next(self._req_id_seq)

        # Thread-safe handler registration
        with self._market_lock:
            self._market_handlers[req_id] = (symbol, handler)

        # P1-1 Fix: Store subscription details for reconnection
        self._active_subscriptions[symbol] = (handler, bar_size)

        self.reqRealTimeBars(req_id, contract, bar_size, 'TRADES', True, [])
        self._logger.info('subscribed_realtime_bars', extra={'symbol': symbol, 'bar_size': bar_size, 'req_id': req_id})
        return req_id

    def unsubscribe(self, req_id: int) -> None:
        """Unsubscribe from real-time bars."""
        # P1-1 Fix: Remove from active subscriptions (thread-safe)
        with self._market_lock:
            entry = self._market_handlers.get(req_id)
            if entry:
                symbol = entry[0]
                self._active_subscriptions.pop(symbol, None)
            self._market_handlers.pop(req_id, None)

        self.cancelRealTimeBars(req_id)

    # --- IBAPI Callbacks ------------------------------------------------
    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802,N803 - IBKR API callback name
        self._logger.info('Managed accounts', extra={'accounts': accountsList})

    def nextValidId(self, orderId: int) -> None:  # noqa: N802,N803 - IBKR API callback name
        self._next_order_id = orderId
        self._next_order_id_ready.set()
        self._connected.set()
        self._last_heartbeat = datetime.now(timezone.utc)  # P1: Update heartbeat

    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = '') -> None:
        payload = {
            'ibkr_req_id': reqId,
            'ibkr_error_code': errorCode,
            'ibkr_error_text': errorString,
        }
        if advancedOrderRejectJson:
            payload['ibkr_details'] = advancedOrderRejectJson
        self._logger.error('ib_error', extra=payload)

    def connectionClosed(self) -> None:  # noqa: N802 - IBKR API callback name
        self._logger.warning('IBKR connection closed')
        self._connected.clear()

    def orderStatus(
        self,
        orderId: int,
        status: str,
        filled: float,
        remaining: float,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:  # noqa: N802 - IBKR API callback name
        self._logger.info(
            'order_status',
            extra={
                'order_id': orderId,
                'status': status,
                'filled': filled,
                'remaining': remaining,
                'avg_fill': avgFillPrice,
            },
        )
        if status.lower() in {'filled', 'cancelled', 'inactive'}:
            with self._order_lock:
                self._order_symbol.pop(orderId, None)

    def execDetails(self, reqId: int, contract: Any, execution: Any) -> None:  # noqa: N802 - IBKR API callback name
        action = execution.side.upper()
        side = OrderSide.BUY if action in {'BOT', 'BUY'} else OrderSide.SELL

        # Get symbol from order tracking (thread-safe)
        with self._order_lock:
            symbol = self._order_symbol.get(execution.orderId, contract.symbol or contract.localSymbol or '')

        report = ExecutionReport(
            order_id=execution.orderId,
            symbol=symbol,
            quantity=Decimal(str(execution.shares)) if hasattr(execution, 'shares') else Decimal(str(execution.cumQty)),
            price=Decimal(str(execution.price)),
            side=side,
            timestamp=datetime.fromtimestamp(execution.time, tz=timezone.utc)
            if isinstance(execution.time, (int, float))
            else datetime.now(timezone.utc),
        )
        self._on_fill(report)

    def realtimeBar(
        self,
        reqId: int,
        time: int,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        wap: float,
        count: int,
    ) -> None:  # noqa: N802 - IBKR API callback name
        # P2-2: Log heartbeat for observability
        now = datetime.now(timezone.utc)
        self._last_heartbeat = now
        self._logger.debug('heartbeat', extra={'timestamp': now.isoformat(), 'req_id': reqId})

        # Thread-safe handler lookup
        with self._market_lock:
            entry = self._market_handlers.get(reqId)

        if entry:
            symbol, handler = entry
            handler(datetime.fromtimestamp(time, tz=timezone.utc), symbol, open_, high, low, close, volume)

    # Historical data callbacks
    def historicalData(self, reqId: int, bar: Any) -> None:  # noqa: N802 - IBKR API callback name
        """Collect historical bar into buffer."""
        if reqId not in self._hist_buffers:
            return
        ts = self._parse_historical_timestamp(getattr(bar, 'date', None))
        symbol = self._hist_symbol.get(reqId, '') or self._get_symbol_from_req(reqId) or ''
        b = Bar(
            symbol=symbol,
            timestamp=ts,
            open=Decimal(str(bar.open)),
            high=Decimal(str(bar.high)),
            low=Decimal(str(bar.low)),
            close=Decimal(str(bar.close)),
            volume=int(bar.volume),
        )
        self._hist_buffers[reqId].append(b)

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:  # noqa: N802 - IBKR API callback name
        """Signal historical data completion."""
        ev = self._hist_ready.get(reqId)
        if ev:
            ev.set()

    def position(self, account: str, contract: Any, position: float, avgCost: float) -> None:  # noqa: N803 - IBKR API callback signature
        """P0 Fix: Callback when IBKR sends position data (thread-safe)."""
        symbol = contract.symbol or contract.localSymbol or ''
        with self._positions_lock:
            self._positions[symbol] = (position, avgCost)
        self._logger.info(
            'position_update',
            extra={'symbol': symbol, 'quantity': position, 'avg_cost': avgCost},
        )

    def positionEnd(self) -> None:  # noqa: N802 - IBKR API callback name
        """P0 Fix: Called when all positions have been delivered."""
        self._positions_ready.set()
        self._logger.info('positions_received', extra={'count': len(self._positions)})

    def reconcile_positions(self, portfolio: Any, timeout: float = 10.0) -> bool:
        """
        P0-5 Fix: Reconcile portfolio positions with IBKR broker (blocking).

        Requests all positions from IBKR, waits for them to arrive, then compares
        with local portfolio to detect discrepancies.

        Args:
            portfolio: Portfolio object to reconcile against
            timeout: Maximum seconds to wait for position data

        Returns:
            True if reconciliation succeeded, False if timed out
        """
        self._logger.info('reconciling_positions_with_broker')

        # Clear previous position data
        with self._positions_lock:
            self._positions.clear()
        self._positions_ready.clear()

        # Request positions from IBKR
        self.reqPositions()

        # Wait for positions to arrive (blocking with timeout)
        if not self._positions_ready.wait(timeout):
            self._logger.error('position_reconciliation_timeout', extra={'timeout_seconds': timeout})
            return False

        # Take snapshot of positions for comparison (thread-safe)
        with self._positions_lock:
            positions_snapshot = dict(self._positions)

        # Compare broker positions with portfolio
        discrepancies: list[str] = []

        # Check positions in broker
        for symbol, (broker_qty, broker_avg_price) in positions_snapshot.items():
            portfolio_qty = portfolio.get_position(symbol)

            if abs(portfolio_qty) < 0.01:  # No portfolio position
                if abs(broker_qty) > 0.01:
                    discrepancies.append(
                        f'Missing in portfolio: {symbol} (broker qty={broker_qty}, avg_price={broker_avg_price})'
                    )
            elif abs(float(portfolio_qty) - broker_qty) > 0.01:  # Quantity mismatch
                discrepancies.append(f'Quantity mismatch: {symbol} (portfolio={portfolio_qty}, broker={broker_qty})')

        # Check positions in portfolio but not in broker
        portfolio_positions = portfolio.snapshot_positions()
        for symbol, position in portfolio_positions.items():
            if symbol not in positions_snapshot and abs(float(position.quantity)) > 0.01:
                discrepancies.append(f'Extra in portfolio: {symbol} (qty={position.quantity}, not in broker)')

        # Log results
        if discrepancies:
            self._logger.warning(
                'position_discrepancies_detected', extra={'count': len(discrepancies), 'discrepancies': discrepancies}
            )
            for disc in discrepancies:
                self._logger.warning('position_discrepancy', extra={'detail': disc})
        else:
            self._logger.info('positions_reconciled_successfully', extra={'position_count': len(positions_snapshot)})

        return True

    # --- Helpers -------------------------------------------------------
    def _ensure_connected(self) -> None:
        if not self.isConnected():
            raise RuntimeError('IBKR broker is not connected. Call start() first.')

    def _build_contract(self, symbol: str) -> Contract:
        contract = Contract()
        spec = self._get_contract_spec(symbol)
        contract.symbol = spec.symbol
        contract.secType = spec.sec_type
        contract.exchange = spec.exchange
        contract.currency = spec.currency
        if spec.local_symbol:
            contract.localSymbol = spec.local_symbol
        if spec.multiplier:
            contract.multiplier = str(spec.multiplier)
        if self._config.ib_account:
            contract.account = self._config.ib_account
        return contract

    @staticmethod
    def _build_order(order: Order) -> IBOrder:
        ib_order = IBOrder()
        ib_order.action = 'BUY' if order.side == OrderSide.BUY else 'SELL'
        ib_order.totalQuantity = float(order.quantity)
        if order.order_type == OrderType.MARKET:
            ib_order.orderType = 'MKT'
        elif order.order_type == OrderType.LIMIT:
            ib_order.orderType = 'LMT'
            ib_order.lmtPrice = float(order.limit_price or 0)
        elif order.order_type == OrderType.STOP:
            ib_order.orderType = 'STP'
            ib_order.auxPrice = float(order.stop_price or 0)
        else:
            raise ValueError(f'Unsupported order type: {order.order_type}')
        ib_order.tif = order.time_in_force.upper()
        ib_order.transmit = True
        return ib_order

    def _get_symbol_from_req(self, req_id: int) -> str:
        # For simple setups, the request id encodes the order; for a production
        # system you would maintain a reqId->symbol mapping. Here we default to
        # a placeholder.
        # Thread-safe access to market handlers
        with self._market_lock:
            entry = self._market_handlers.get(req_id)
        return entry[0] if entry else ''

    def _get_contract_spec(self, symbol: str) -> ContractSpec:
        spec = self._config.contracts.get(symbol)
        if spec:
            return spec
        return ContractSpec(
            symbol=symbol,
            sec_type=self._config.ib_sec_type,
            exchange=self._config.ib_exchange,
            currency=self._config.ib_currency,
        )

    def get_positions(self) -> dict[str, tuple[float, float]]:
        """
        P0 Fix: Retrieve current positions from IBKR for reconciliation (thread-safe).

        Returns:
            Dict mapping symbol -> (quantity, average_price)
        """
        self._ensure_connected()
        with self._positions_lock:
            self._positions.clear()
        self._positions_ready.clear()
        self.reqPositions()  # Request position updates
        if not self._positions_ready.wait(timeout=10):
            self._logger.warning('position_request_timeout')
            return {}
        with self._positions_lock:
            return dict(self._positions)

    # --- Historical Data (Optional) -----------------------------------
    def fetch_historical_bars(self, symbol: str, duration: str = '2 D', bar_size: str = '1 min') -> list[Bar]:
        """
        Fetch recent historical bars from IBKR (utility helper; not used by default).

        Args:
            symbol: Ticker symbol
            duration: IBKR duration string (e.g., '2 D', '1 W')
            bar_size: IBKR bar size (e.g., '1 min', '5 mins')

        Returns:
            List of Bar objects in chronological order
        """
        self._ensure_connected()
        contract = self._build_contract(symbol)
        req_id = next(self._req_id_seq)
        self._hist_buffers[req_id] = []
        self._hist_ready[req_id] = threading.Event()
        self._hist_symbol[req_id] = symbol
        what_to_show = 'TRADES'
        use_rth = 1  # Regular trading hours
        format_date = 2  # yyyymmdd{space}{hh:mm:dd}
        end_dt = ''  # now
        self.reqHistoricalData(
            req_id, contract, end_dt, duration, bar_size, what_to_show, use_rth, format_date, False, []
        )
        # Wait up to 20s
        self._hist_ready[req_id].wait(timeout=20)
        data = self._hist_buffers.get(req_id, [])
        # Clean up
        self._hist_ready.pop(req_id, None)
        self._hist_buffers.pop(req_id, None)
        self._hist_symbol.pop(req_id, None)
        # Sort by timestamp just in case
        return sorted(data, key=lambda b: b.timestamp)

    @staticmethod
    def _parse_historical_timestamp(raw: Any) -> datetime:
        """Parse IBKR historical bar timestamps for `historicalData`."""
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)

        if not isinstance(raw, str):
            return datetime.now(timezone.utc)

        text = raw.strip()
        if not text:
            return datetime.now(timezone.utc)

        if text.isdigit():
            # IBKR may send either epoch seconds or yyyymmdd for daily bars.
            if len(text) > 8:
                return datetime.fromtimestamp(int(text), tz=timezone.utc)
            if len(text) == 8:
                return datetime.strptime(text, '%Y%m%d').replace(tzinfo=timezone.utc)

        for fmt in ('%Y%m%d %H:%M:%S', '%Y%m%d  %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        try:
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            return datetime.now(timezone.utc)

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
