from __future__ import annotations

import itertools
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from ..config import BrokerConfig, ContractSpec
from ..execution import ExecutionReport, Order, OrderSide, OrderType
from ..logging import configure_logger
from .base import BaseBroker

try:  # pragma: no cover - ibapi not available in test environment
    from ibapi.client import EClient
    from ibapi.contract import Contract
    from ibapi.order import Order as IBOrder
    from ibapi.wrapper import EWrapper
except ImportError:  # pragma: no cover - handled gracefully at runtime
    class _DummyWrapper:  # pragma: no cover
        pass

    class _DummyClient:  # pragma: no cover
        def __init__(self, *args, **kwargs):
            pass

    EClient = _DummyClient  # type: ignore
    EWrapper = _DummyWrapper  # type: ignore
    IBAPI_AVAILABLE = False
else:
    IBAPI_AVAILABLE = True


class IBKRBroker(BaseBroker, EWrapper, EClient):  # pragma: no cover - requires IB connection
    """
    Thin adapter around Interactive Brokers' API.
    """

    def __init__(self, config: BrokerConfig):
        if not IBAPI_AVAILABLE:
            raise RuntimeError("ibapi is not installed. Install it via `pip install ibapi`.")

        BaseBroker.__init__(self)
        EWrapper.__init__(self)
        EClient.__init__(self, self)

        self._config = config
        self._logger = configure_logger("IBKRBroker", structured=True)

        self._thread: threading.Thread | None = None
        self._connected = threading.Event()
        self._next_order_id_ready = threading.Event()
        self._next_order_id = 1
        self._order_lock = threading.Lock()
        self._req_id_seq = itertools.count(start=1000)
        self._market_handlers: dict[int, tuple[str, Callable[[datetime, str, float, float, float, float, float], None]]] = {}
        self._order_symbol: dict[int, str] = {}

        # P0 Fix: Position reconciliation state
        self._positions: dict[str, tuple[float, float]] = {}  # symbol -> (quantity, avg_price)
        self._positions_ready = threading.Event()

        # P1 Enhancement: Auto-reconnect with heartbeat
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._last_heartbeat: datetime | None = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_backoff_base = 2.0  # Exponential backoff

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
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_monitor, daemon=True, name="IBKRHeartbeat")
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
            self._logger.info("Disconnecting IBKR")
            self.disconnect()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._connected.clear()

    def _connect_with_retry(self) -> None:
        """
        P1 Enhancement: Connect with exponential backoff retry.
        """
        import time

        for attempt in range(self._max_reconnect_attempts):
            try:
                self._logger.info(
                    "Connecting to IBKR",
                    extra={"host": self._config.ib_host, "port": self._config.ib_port, "attempt": attempt + 1},
                )
                self.connect(self._config.ib_host, self._config.ib_port, self._config.ib_client_id)
                self._thread = threading.Thread(target=self.run, daemon=True, name="IBKRClientLoop")
                self._thread.start()

                if self._connected.wait(timeout=10):
                    self.reqIds(-1)  # trigger nextValidId callback
                    self._reconnect_attempts = 0  # Reset on success
                    self._last_heartbeat = datetime.now(timezone.utc)
                    self._logger.info("IBKR connected successfully")
                    return

                # Timeout - retry with backoff
                backoff = self._reconnect_backoff_base ** attempt
                self._logger.warning(
                    "Connection timeout, retrying",
                    extra={"attempt": attempt + 1, "backoff_sec": backoff},
                )
                time.sleep(backoff)

            except Exception as exc:
                backoff = self._reconnect_backoff_base ** attempt
                self._logger.error(
                    "Connection failed",
                    extra={"attempt": attempt + 1, "error": str(exc), "backoff_sec": backoff},
                )
                time.sleep(backoff)

        raise ConnectionError(f"Failed to connect after {self._max_reconnect_attempts} attempts")

    def _heartbeat_monitor(self) -> None:
        """
        P1 Enhancement: Monitor connection health and auto-reconnect.

        Checks connection every 30 seconds. If no activity for 60 seconds, reconnects.
        """
        import time

        while not self._heartbeat_stop.is_set():
            time.sleep(30)  # Check every 30 seconds

            if not self.isConnected():
                self._logger.warning("Heartbeat: Connection lost, attempting reconnect")
                try:
                    self._connect_with_retry()
                except Exception as exc:
                    self._logger.error("Heartbeat: Reconnect failed", extra={"error": str(exc)})

            # Check if we've received any activity recently
            if self._last_heartbeat:
                elapsed = (datetime.now(timezone.utc) - self._last_heartbeat).total_seconds()
                if elapsed > 60:  # No activity for 60 seconds
                    self._logger.warning(
                        "Heartbeat: No activity detected, forcing reconnect",
                        extra={"elapsed_sec": elapsed},
                    )
                    try:
                        self.disconnect()
                        self._connect_with_retry()
                    except Exception as exc:
                        self._logger.error("Heartbeat: Force reconnect failed", extra={"error": str(exc)})

    # --- Order interface -----------------------------------------------
    def submit(self, order: Order) -> int:
        self._ensure_connected()
        if not self._next_order_id_ready.wait(timeout=5):
            raise TimeoutError("Order id not received from IBKR.")
        with self._order_lock:
            order_id = self._next_order_id
            self._next_order_id += 1
        contract = self._build_contract(order.symbol)
        ib_order = self._build_order(order)
        self.placeOrder(order_id, contract, ib_order)
        self._order_symbol[order_id] = order.symbol
        return order_id

    def cancel(self, order_id: int) -> bool:
        self._ensure_connected()
        self.cancelOrder(order_id)
        return True

    # --- Market data subscription --------------------------------------
    def subscribe_realtime_bars(
        self,
        symbol: str,
        handler: Callable[[datetime, str, float, float, float, float, float], None],
        bar_size: int = 5,
    ) -> int:
        """
        Subscribe to real-time bars (seconds resolution).
        """
        self._ensure_connected()
        contract = self._build_contract(symbol)
        req_id = next(self._req_id_seq)
        self._market_handlers[req_id] = (symbol, handler)
        self.reqRealTimeBars(req_id, contract, bar_size, "TRADES", True, [])
        return req_id

    def unsubscribe(self, req_id: int) -> None:
        self.cancelRealTimeBars(req_id)
        self._market_handlers.pop(req_id, None)

    # --- IBAPI Callbacks ------------------------------------------------
    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802 - IBKR API callback name
        self._logger.info("Managed accounts", extra={"accounts": accountsList})

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IBKR API callback name
        self._next_order_id = orderId
        self._next_order_id_ready.set()
        self._connected.set()
        self._last_heartbeat = datetime.now(timezone.utc)  # P1: Update heartbeat

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        payload = {
            "ibkr_req_id": reqId,
            "ibkr_error_code": errorCode,
            "ibkr_error_text": errorString,
        }
        if advancedOrderRejectJson:
            payload["ibkr_details"] = advancedOrderRejectJson
        self._logger.error("ib_error", extra=payload)

    def connectionClosed(self):  # noqa: N802 - IBKR API callback name
        self._logger.warning("IBKR connection closed")
        self._connected.clear()

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):  # noqa: N802 - IBKR API callback name
        self._logger.info(
            "order_status",
            extra={
                "order_id": orderId,
                "status": status,
                "filled": filled,
                "remaining": remaining,
                "avg_fill": avgFillPrice,
            },
        )
        if status.lower() in {"filled", "cancelled", "inactive"}:
            self._order_symbol.pop(orderId, None)

    def execDetails(self, reqId, contract, execution):  # noqa: N802 - IBKR API callback name
        action = execution.side.upper()
        side = OrderSide.BUY if action in {"BOT", "BUY"} else OrderSide.SELL
        report = ExecutionReport(
            order_id=execution.orderId,
            symbol=self._order_symbol.get(execution.orderId, contract.symbol or contract.localSymbol or ""),
            quantity=Decimal(str(execution.shares)) if hasattr(execution, "shares") else Decimal(str(execution.cumQty)),
            price=Decimal(str(execution.price)),
            side=side,
            timestamp=datetime.fromtimestamp(execution.time, tz=timezone.utc) if isinstance(execution.time, (int, float)) else datetime.now(timezone.utc),
        )
        self._on_fill(report)

    def realtimeBar(self, reqId, time, open_, high, low, close, volume, wap, count):  # noqa: N802 - IBKR API callback name
        self._last_heartbeat = datetime.now(timezone.utc)  # P1: Update heartbeat
        entry = self._market_handlers.get(reqId)
        if entry:
            symbol, handler = entry
            handler(datetime.fromtimestamp(time, tz=timezone.utc), symbol, open_, high, low, close, volume)

    def position(self, account: str, contract, position: float, avgCost: float):  # noqa: N803 - IBKR API callback signature
        """P0 Fix: Callback when IBKR sends position data."""
        symbol = contract.symbol or contract.localSymbol or ""
        self._positions[symbol] = (position, avgCost)
        self._logger.info(
            "position_update",
            extra={"symbol": symbol, "quantity": position, "avg_cost": avgCost},
        )

    def positionEnd(self):  # noqa: N802 - IBKR API callback name
        """P0 Fix: Called when all positions have been delivered."""
        self._positions_ready.set()
        self._logger.info("positions_received", extra={"count": len(self._positions)})

    # --- Helpers -------------------------------------------------------
    def _ensure_connected(self) -> None:
        if not self.isConnected():
            raise RuntimeError("IBKR broker is not connected. Call start() first.")

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
        ib_order.action = "BUY" if order.side == OrderSide.BUY else "SELL"
        ib_order.totalQuantity = float(order.quantity)
        if order.order_type == OrderType.MARKET:
            ib_order.orderType = "MKT"
        elif order.order_type == OrderType.LIMIT:
            ib_order.orderType = "LMT"
            ib_order.lmtPrice = float(order.limit_price or 0)
        elif order.order_type == OrderType.STOP:
            ib_order.orderType = "STP"
            ib_order.auxPrice = float(order.stop_price or 0)
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")
        ib_order.tif = order.time_in_force.upper()
        ib_order.transmit = True
        return ib_order

    def _get_symbol_from_req(self, req_id: int) -> str:
        # For simple setups, the request id encodes the order; for a production
        # system you would maintain a reqId->symbol mapping. Here we default to
        # a placeholder.
        entry = self._market_handlers.get(req_id)
        return entry[0] if entry else ""

    def _get_contract_spec(self, symbol: str) -> ContractSpec:
        spec = self._config.contracts.get(symbol)
        if spec:
            return spec
        return ContractSpec(symbol=symbol, sec_type=self._config.ib_sec_type, exchange=self._config.ib_exchange, currency=self._config.ib_currency)

    def get_positions(self) -> dict[str, tuple[float, float]]:
        """
        P0 Fix: Retrieve current positions from IBKR for reconciliation.

        Returns:
            Dict mapping symbol -> (quantity, average_price)
        """
        self._ensure_connected()
        self._positions.clear()
        self._positions_ready.clear()
        self.reqPositions()  # Request position updates
        if not self._positions_ready.wait(timeout=10):
            self._logger.warning("position_request_timeout")
            return {}
        return dict(self._positions)
