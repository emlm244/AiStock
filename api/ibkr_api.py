# api/ibkr_api.py

import sys
import threading
import time
import queue
import re
import pandas as pd
from datetime import datetime, timezone # Import timezone
import json # Import json
import pytz # Import pytz

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails # Import ContractDetails
from ibapi.execution import Execution, ExecutionFilter
from ibapi.order import Order
from ibapi.commission_report import CommissionReport

# Circuit breaker and retry imports
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from api.circuit_breaker_wrapper import with_circuit_breaker

# Ensure config is importable
try:
    from config.credentials import IBKR
    from config.settings import Settings
except ImportError:
    print("CRITICAL: Cannot import config/credentials.py or config/settings.py. Ensure they exist.")
    sys.exit(1)

from utils.logger import setup_logger
from contract_utils import create_contract # Use updated contract utils

# Define order final states recognized by IB API
ORDER_FINAL_STATES = {
    "ApiCancelled", "Cancelled", "Filled", "Inactive", "PendingCancel",
    "PendingSubmit", # Treat as potentially final if rejected
}
# States considered 'Active' or potentially active by the bot logic
ORDER_ACTIVE_STATES = {"PreSubmitted", "Submitted", "ApiPending"}


class IBKRApi(EWrapper, EClient):
    # Pass settings directly, managers assigned after initialization
    def __init__(self, trading_bot, settings):
        EClient.__init__(self, self)
        self.trading_bot = trading_bot # Reference to main bot for callbacks
        self.settings = settings
        # Managers are assigned *after* initialization by TradingBot
        self.order_manager = None
        self.portfolio_manager = None

        # Setup loggers
        self.logger = setup_logger('IBKRApi', 'logs/app.log', level=self.settings.LOG_LEVEL)
        self.error_logger = setup_logger('IBKRApiError', 'logs/error_logs/errors.log', level='ERROR')

        # Timezone setup
        try:
            tws_tz_str = getattr(settings, 'TWS_TIMEZONE', settings.TIMEZONE)
            self.tws_local_tz = pytz.timezone(tws_tz_str)
            self.logger.info(f"Using TWS/Gateway timezone for timestamp conversion: {tws_tz_str}")
        except pytz.UnknownTimeZoneError:
            self.logger.error(f"Unknown TWS timezone '{tws_tz_str}'. Using UTC as fallback.")
            self.tws_local_tz = pytz.utc
        except Exception as e:
            self.logger.error(f"Error setting TWS timezone: {e}. Using UTC.")
            self.tws_local_tz = pytz.utc


        self.connected = False
        self.connection_status = "Disconnected"
        self.account_id = IBKR.get('ACCOUNT_ID', None)
        if not self.account_id or self.account_id == 'YOUR_ACCOUNT_ID':
            self.error_logger.critical("IBKR Account ID not found or not set in credentials.py!")
            raise ValueError("IBKR Account ID missing or not configured in credentials")

        self.api_lock = threading.Lock()
        self.live_ticks_queue = queue.Queue()

        self._next_valid_order_id = None
        self._order_id_lock = threading.Lock()
        self.order_id_request_time = None

        self.reconnecting = False
        self.connect_thread = None
        self.api_thread = None
        self.api_ready = threading.Event()

        self.unsubscribed_symbols = set()
        self.active_market_data_reqs = {}
        self.active_hist_data_reqs = {}
        self.active_contract_detail_reqs = {}
        self.req_id_counter = int(time.time() % 100000)

        self.contract_details_cache = {}
        self.contract_details_received = threading.Event()
        self._pending_detail_reqs = set()

        self.account_summary_received = threading.Event()
        self.positions_received = threading.Event()
        self.open_orders_received = threading.Event()
        self.account_details = {}
        self.broker_positions = {}
        self.broker_open_orders = {}

    # --- Connection / Disconnection ---
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=16),
        retry=retry_if_exception_type((ConnectionError, OSError)),
        reraise=True
    )
    def connect_app(self):
        if self.connected or self.reconnecting:
            self.logger.warning("Connection attempt ignored: Already connected or reconnecting.")
            return

        host = IBKR.get('TWS_HOST', '127.0.0.1')
        port = IBKR.get('TWS_PORT', 7497)
        client_id = IBKR.get('CLIENT_ID', 1)

        self.logger.info(f"Attempting to connect to TWS @ {host}:{port} with ClientID {client_id}...")
        self.connection_status = "Connecting"
        self._clear_connection_state()

        try:
            self.connect_thread = threading.Thread(target=self._execute_connect, args=(host, port, client_id), daemon=True)
            self.connect_thread.start()
        except Exception as e:
            self.error_logger.error(f"Exception during connection initiation: {e}", exc_info=True)
            self.connection_status = "Failed Initial Connect"
            self.schedule_reconnect()

    def _clear_connection_state(self):
        self.connected = False
        self.reconnecting = False
        self._next_valid_order_id = None
        self.account_summary_received.clear()
        self.positions_received.clear()
        self.open_orders_received.clear()
        self.contract_details_received.clear()
        self.api_ready.clear()
        self._pending_detail_reqs.clear()
        self.account_details.clear()
        self.broker_positions.clear()
        self.broker_open_orders.clear()


    def _execute_connect(self, host, port, client_id):
        try:
            if self.isConnected():
                 self.logger.warning("Already connected before _execute_connect call? Disconnecting first.")
                 self.disconnect()
                 time.sleep(1)

            self.connect(host, port, client_id)
            time.sleep(3)

            if not self.isConnected():
                 self.logger.error("Connection attempt failed. isConnected() returned False after connect call.")
                 self.connection_status = "Connection Failed"
                 raise ConnectionError("Failed to establish connection.")

            self.logger.info("Successfully initiated connection to TWS/Gateway.")
            self.connected = True
            self.reconnecting = False
            self.connection_status = "Connected"

            if self.api_thread is None or not self.api_thread.is_alive():
                self.api_thread = threading.Thread(target=self.run_loop, name="IBKRApiMsgLoop", daemon=True)
                self.api_thread.start()
                self.logger.info("API message loop started.")
            else:
                 self.logger.warning("API message loop thread detected as already running.")

            self.request_next_order_id()
            self.initial_data_requests()

            initial_data_ok = self._wait_for_initial_data(timeout=60)

            if not initial_data_ok:
                 self.error_logger.critical("Failed to get critical initial data (OrderID/Account Summary) after connection. Bot cannot proceed safely.")
                 self.disconnect_app()
                 if self.trading_bot: self.trading_bot.stop("Initial Data Failed")
                 return
            else:
                 self.logger.info("Initial data received, API ready.")
                 self.api_ready.set() # Signal readiness

        except ConnectionRefusedError:
            self.error_logger.error("Connection Refused. Is TWS/Gateway running and API configured correctly?")
            self.connection_status = "Connection Refused"
            self.schedule_reconnect()
        except ConnectionError as e:
            self.error_logger.error(f"Connection Error: {e}")
            self.connection_status = "Connection Error"
            self.schedule_reconnect()
        except Exception as e:
            self.error_logger.critical(f"CRITICAL Exception during TWS connection or startup: {e}", exc_info=True)
            self.connection_status = "Connection Error"
            if self.isConnected(): self.disconnect()
            self.schedule_reconnect()

    def run_loop(self):
        self.logger.info("API message processing loop starting.")
        try:
            while self.isConnected():
                self.run()
                time.sleep(0.01)
            self.logger.info("Exited API message loop (isConnected() is False).")
        except Exception as e:
            self.error_logger.critical(f"Exception in API run_loop: {e}", exc_info=True)
            self.connected = False
            self.connection_status = "Loop Error"
            self.api_ready.clear() # Clear readiness on loop error
        finally:
             self.logger.info("API message processing loop finished.")


    def disconnect_app(self):
        if not self.isConnected():
            self.logger.info("Disconnect attempt ignored: Not connected.")
            self.connected = False
            self.connection_status = "Disconnected"
            self.reconnecting = False
            self.api_ready.clear()
            return

        self.logger.info("Disconnecting from TWS/Gateway...")
        was_connected = self.connected
        self.connected = False
        self.connection_status = "Disconnecting"
        self.api_ready.clear()

        try:
            self.disconnect()
            time.sleep(1)
            if was_connected:
                self.logger.info("Successfully disconnected from TWS/Gateway.")
        except Exception as e:
            self.error_logger.error(f"Exception during disconnection: {e}", exc_info=True)
        finally:
            self.connection_status = "Disconnected"
            self.reconnecting = False


    def schedule_reconnect(self, delay=None):
        with self.api_lock:
            if self.reconnecting or self.connected:
                status = "connected" if self.connected else "reconnecting"
                self.logger.debug(f"Reconnect scheduling skipped: Already {status}.")
                return

            effective_delay = delay if delay is not None else self.settings.RECONNECT_DELAY_SECONDS
            self.reconnecting = True
            self.connection_status = f"Reconnecting in {effective_delay}s"
            self.logger.info(f"Scheduling reconnection attempt in {effective_delay} seconds...")

            timer = threading.Timer(effective_delay, self._attempt_reconnect)
            timer.daemon = True
            timer.start()

    def _attempt_reconnect(self):
        with self.api_lock:
            if not self.reconnecting:
                 self.logger.info("Reconnect attempt cancelled or already reconnected.")
                 return
            self.reconnecting = False

        self.logger.info("Attempting scheduled reconnect...")
        self.connect_app()


    # --- Initial Data Requests & Waiting ---
    def initial_data_requests(self):
         if not self.isConnected(): return
         try:
             self.reqMarketDataType(1)
             self.logger.info("Requested Market Data Type: Live (1)")
         except Exception as e:
              self.error_logger.error(f"Failed to set Market Data Type: {e}")
         self.request_account_and_positions()


    def request_account_and_positions(self):
         if not self.isConnected():
             self.logger.warning("Cannot request account data: API not connected.")
             return
         self.logger.info("Requesting Account Summary, Positions, and Open Orders...")
         self.account_summary_received.clear(); self.positions_received.clear(); self.open_orders_received.clear()
         self.account_details.clear(); self.broker_positions.clear(); self.broker_open_orders.clear()

         req_id_summary = self.get_next_req_id()
         tags = "TotalCashValue,NetLiquidation,AvailableFunds,BuyingPower,RealizedPnL,UnrealizedPnL"
         self.reqAccountSummary(req_id_summary, "All", tags)
         self.logger.info(f"Requested Account Summary (ReqId: {req_id_summary}, Tags: {tags})")
         self.reqPositions()
         self.logger.info("Requested Current Positions.")
         self.reqOpenOrders()
         self.logger.info("Requested Open Orders.")


    def _wait_for_initial_data(self, timeout=60):
         self.logger.info(f"Waiting up to {timeout}s for initial critical data (NextOrderID, Account Summary)...")
         start_time = time.time()
         critical_data_ok = True

         while self._next_valid_order_id is None and time.time() - start_time < timeout:
             if not self.isConnected():
                 self.error_logger.error("Connection lost while waiting for NextValidId.")
                 return False
             time.sleep(0.5)
         if self._next_valid_order_id is None:
             self.error_logger.critical("Failed to receive NextValidId within timeout.")
             critical_data_ok = False
         else: self.logger.info(f"NextValidId received: {self._next_valid_order_id}")

         summary_timeout = max(0.1, timeout - (time.time() - start_time))
         summary_received = self.account_summary_received.wait(timeout=summary_timeout)
         if not summary_received:
             self.error_logger.warning(f"Timeout ({summary_timeout:.1f}s) waiting for Account Summary End signal.")
             if 'NetLiquidation' not in self.account_details or 'TotalCashValue' not in self.account_details:
                  self.error_logger.error("Essential account values (NetLiquidation/TotalCashValue) missing after timeout.")
                  critical_data_ok = False
         else: self.logger.info("Account Summary End received.")

         if not critical_data_ok: return False

         pos_timeout = max(0.1, timeout - (time.time() - start_time))
         pos_received = self.positions_received.wait(timeout=pos_timeout)
         if not pos_received: self.logger.warning(f"Timeout ({pos_timeout:.1f}s) waiting for Positions End signal.")
         else: self.logger.info("Positions End received.")

         ord_timeout = max(0.1, timeout - (time.time() - start_time))
         ord_received = self.open_orders_received.wait(timeout=ord_timeout)
         if not ord_received: self.logger.warning(f"Timeout ({ord_timeout:.1f}s) waiting for Open Orders End signal.")
         else: self.logger.info("Open Orders End received.")

         return True

    # --- Contract Details ---
    def request_contract_details(self, symbol):
         if not self.isConnected():
             self.logger.warning(f"Cannot request contract details for {symbol}: API not connected.")
             return False
         contract = create_contract(symbol)
         if not contract:
              self.error_logger.error(f"Cannot request details: Failed to create contract for {symbol}")
              return False

         with self.api_lock:
             req_id = self.get_next_req_id()
             self.active_contract_detail_reqs[req_id] = symbol
             self._pending_detail_reqs.add(symbol)
             self.contract_details_received.clear()

             self.logger.info(f"Requesting Contract Details for {symbol} (ReqId: {req_id})")
             try:
                 self.reqContractDetails(req_id, contract)
                 return True
             except Exception as e:
                  self.error_logger.error(f"Exception during reqContractDetails for {symbol} (ReqId: {req_id}): {e}", exc_info=True)
                  if req_id in self.active_contract_detail_reqs: del self.active_contract_detail_reqs[req_id]
                  if symbol in self._pending_detail_reqs: self._pending_detail_reqs.remove(symbol)
                  return False

    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        super().contractDetails(reqId, contractDetails)
        symbol = self.active_contract_detail_reqs.get(reqId)
        if symbol:
            self.logger.info(f"Received Contract Details for: {symbol} (ReqId: {reqId}) - MinTick: {contractDetails.minTick}, Market Name: {contractDetails.marketName}")
            with self.api_lock:
                self.contract_details_cache[symbol] = contractDetails
        else:
            self.logger.warning(f"Received contract details for unknown ReqId: {reqId}")

    def contractDetailsEnd(self, reqId: int):
        super().contractDetailsEnd(reqId)
        symbol = None
        with self.api_lock:
            symbol = self.active_contract_detail_reqs.pop(reqId, None)
            if symbol and symbol in self._pending_detail_reqs:
                 self._pending_detail_reqs.remove(symbol)

        if symbol:
            self.logger.info(f"Contract Details End for {symbol} (ReqId: {reqId}).")
            with self.api_lock:
                if not self._pending_detail_reqs:
                     self.contract_details_received.set()
                     self.logger.info("All pending contract details requests completed.")
        else:
             self.logger.warning(f"Received contractDetailsEnd for unknown or already ended ReqId: {reqId}")


    # --- Request ID and Order ID Management ---
    def get_next_req_id(self):
        with self.api_lock:
            req_id = self.req_id_counter
            self.req_id_counter += 1
            return req_id

    def request_next_order_id(self):
        self.order_id_request_time = time.time()
        self.logger.info("Relying on automatic NextValidId transmission from TWS on connect.")

    def get_next_order_id(self):
        with self._order_id_lock:
             max_wait = 30
             start_wait = time.time()
             while self._next_valid_order_id is None:
                 wait_time = time.time() - start_wait
                 if wait_time > max_wait:
                     self.error_logger.critical(f"FATAL: Waited {max_wait}s but NextValidId not available. Cannot place orders.")
                     self.schedule_reconnect()
                     raise TimeoutError("Failed to get next valid order ID from IBKR.")
                 if not self.isConnected():
                      self.error_logger.error("Connection lost while waiting for nextValidId.")
                      raise ConnectionError("Connection lost while waiting for nextValidId.")
                 if int(wait_time) > 0 and int(wait_time) % 5 == 0:
                     self.logger.warning(f"Waiting for nextValidId... (waited {wait_time:.0f}s)")
                 self._order_id_lock.release()
                 time.sleep(0.2)
                 self._order_id_lock.acquire()

             order_id = self._next_valid_order_id
             self._next_valid_order_id += 1
             return order_id

    # --- EWrapper Callbacks ---

    def _parse_ibkr_timestamp(self, ibkr_time_str):
         try:
             if isinstance(ibkr_time_str, (int, float)):
                 return datetime.fromtimestamp(int(ibkr_time_str), tz=pytz.utc)

             match = re.match(r'(\d{8})\s+(\d{2}:\d{2}:\d{2})\s*(\w+)?$', str(ibkr_time_str).strip())
             if match:
                  date_str, time_str, _ = match.groups() # Ignore timezone abbrev
                  dt_naive = datetime.strptime(f"{date_str} {time_str}", '%Y%m%d %H:%M:%S')
                  dt_local = self.tws_local_tz.localize(dt_naive, is_dst=None)
                  return dt_local.astimezone(pytz.utc)
             elif len(str(ibkr_time_str)) == 8:
                  dt_naive = datetime.strptime(str(ibkr_time_str), '%Y%m%d')
                  dt_local = self.tws_local_tz.localize(dt_naive, is_dst=None)
                  return dt_local.astimezone(pytz.utc)

             self.logger.warning(f"Could not parse IBKR timestamp format: '{ibkr_time_str}'")
             return datetime.now(pytz.utc)
         except Exception as e:
             self.error_logger.error(f"Error parsing IBKR timestamp '{ibkr_time_str}': {e}")
             return datetime.now(pytz.utc)


    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        with self._order_id_lock:
             if self._next_valid_order_id is None or orderId > self._next_valid_order_id:
                self._next_valid_order_id = orderId
                self.logger.info(f"Received nextValidId: {orderId}")


    def connectionClosed(self):
        super().connectionClosed()
        self.logger.error("IBKR Connection Closed (detected by connectionClosed callback).")
        was_connected = self.connected
        self.connected = False
        self.connection_status = "Connection Closed"
        self.api_ready.clear()
        if not self.reconnecting and was_connected:
             self.schedule_reconnect(delay=1)

    # ---> CORRECTED error Method (4-argument version) <---
    def error(self, reqId: int, errorCode: int, errorString: str):
        """Handles errors reported by TWS. (Matches older API signature)"""
        super().error(reqId, errorCode, errorString) # Call parent method

        # ---> MODIFIED info_codes set <---
        # Ignore informational messages unless debugging
        # Codes from https://interactivebrokers.github.io/tws-api/message_codes.html
        info_codes = {
            2100, 2103, 2104, 2105, 2106, 2107, 2108, 2109, 2110, 2119, 2137, 2150,
            2157, 2158, 2168, 2169, 2170, 2171, 2172, 2173, 2174, 2175, 2176, 2177,
            2178, 2179, 2180, 2181, 2182, 326, # Original set
            # Add common data farm status codes:
            2103, 2104, 2105, 2106, 2157, 2158
        }
        # ---> END MODIFIED info_codes set <---

        if errorCode in info_codes and self.settings.LOG_LEVEL != 'DEBUG':
            # self.logger.debug(f"IBKR Info ({errorCode}): {errorString}")
            return

        # Determine symbol context if possible
        symbol_context = "N/A"
        if reqId in self.active_market_data_reqs: symbol_context = f"MktData:{self.active_market_data_reqs[reqId]}"
        elif reqId in self.active_hist_data_reqs: symbol_context = f"HistData:{self.active_hist_data_reqs[reqId]}"
        elif reqId in self.active_contract_detail_reqs: symbol_context = f"ContDet:{self.active_contract_detail_reqs[reqId]}"
        elif reqId == -1: symbol_context = "System"
        else:
            if self.order_manager:
                 order_data = self.order_manager.get_order_details(reqId)
                 if order_data: symbol_context = f"Order:{order_data['contract'].symbol}"

        # Log message WITHOUT advanced reject info
        log_msg = f"IBKR Error - Code:{errorCode}, ReqId:{reqId}, Context:{symbol_context}, Msg: {errorString}"

        # --- Error Classification and Handling ---
        connection_errors = {1100, 1101, 1102, 501, 502, 503, 504, 506, 507, 509, 522, 10147, 10148, 10197, 10224, 10225, 1300, 2110}
        order_errors = list(range(100, 450)) + [512, 513, 514, 515, 516, 517, 520]
        data_subscription_errors = {10090, 10091, 10167, 354, 162, 321, 322, 300}
        pacing_violations = {100, 103}
        critical_errors = {104, 320, 321, 505}

        if errorCode in connection_errors:
            self.error_logger.error(log_msg)
            self.connection_status = f"Connection Error ({errorCode})"
            self.connected = False
            self.api_ready.clear()
            if not self.reconnecting: self.schedule_reconnect()
        elif errorCode in data_subscription_errors:
            self.error_logger.error(log_msg)
            symbol = None
            if reqId in self.active_market_data_reqs: symbol = self.active_market_data_reqs[reqId]
            elif reqId in self.active_hist_data_reqs: symbol = self.active_hist_data_reqs[reqId]

            if symbol:
                if errorCode in {10090, 10091, 10167, 354, 300}:
                     self.logger.warning(f"Marking {symbol} as unsubscribed due to error {errorCode}.")
                     with self.api_lock: self.unsubscribed_symbols.add(symbol)
                     self.cancel_requests_for_symbol(symbol)
                elif errorCode == 162:
                     self.logger.error(f"Historical data request failed for {symbol} (ReqId: {reqId}).")
                     if self.trading_bot and reqId in self.trading_bot.historical_data_req_ids:
                          self.trading_bot.finalize_historical_data(symbol)
                     with self.api_lock: self.active_hist_data_reqs.pop(reqId, None)

        elif errorCode in order_errors or "order reject" in errorString.lower():
             self.error_logger.warning(log_msg)
             if "margin" in errorString.lower() or "insufficient" in errorString.lower():
                  self.error_logger.critical(f"Potential Margin Issue for OrderID {reqId}: {errorString}")
                  if self.trading_bot and self.trading_bot.risk_manager:
                       self.trading_bot.risk_manager.force_halt(f"Potential Margin Issue (Order {reqId})")

        elif errorCode in pacing_violations:
            self.error_logger.warning(log_msg + " - Pacing Violation: Consider reducing request frequency.")
        elif errorCode in critical_errors:
             self.error_logger.critical(log_msg + " - Critical API Error Encountered.")
             if errorCode == 104:
                  self.error_logger.critical("Duplicate Order ID detected! Requesting open orders for reconciliation.")
                  self.reqOpenOrders()
        else:
            # Log other non-info errors as warnings by default
            self.error_logger.warning(log_msg + " - Unclassified Error Code.")


    def cancel_requests_for_symbol(self, symbol):
         self.logger.info(f"Cancelling active data requests for unsubscribed symbol: {symbol}")
         req_ids_to_cancel = []
         with self.api_lock:
             req_ids_to_cancel.extend([k for k, v in self.active_market_data_reqs.items() if v == symbol])
         for req_id in req_ids_to_cancel:
              self.cancelMktData(req_id)


    # Account Data Callbacks
    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str):
        super().accountSummary(reqId, account, tag, value, currency)
        if account == self.account_id:
             self.account_details[tag] = {'value': value, 'currency': currency}

    def accountSummaryEnd(self, reqId: int):
        super().accountSummaryEnd(reqId)
        self.logger.info(f"Account Summary End (ReqId: {reqId}).")
        if self.portfolio_manager:
            self.portfolio_manager.reconcile_broker_values(self.account_details)
        else:
            self.logger.warning("Portfolio Manager not assigned, cannot reconcile account values.")
        self.account_summary_received.set()


    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        super().position(account, contract, position, avgCost)
        if account == self.account_id:
             symbol = f"{contract.symbol}/{contract.currency}" if contract.secType in ["CASH", "CRYPTO"] else contract.symbol
             self.broker_positions[symbol] = {'position': position, 'averageCost': avgCost, 'contract': contract}

    def positionEnd(self):
        super().positionEnd()
        self.logger.info("Position data end received.")
        if self.portfolio_manager:
            self.portfolio_manager.reconcile_positions(self.broker_positions)
        else:
            self.logger.warning("Portfolio Manager not assigned, cannot reconcile positions.")
        self.positions_received.set()


    # Order Status and Execution Callbacks
    def orderStatus(self, orderId: int, status: str, filled: float, remaining: float, avgFillPrice: float, permId: int, parentId: int, lastFillPrice: float, clientId: int, whyHeld: str, mktCapPrice: float):
        super().orderStatus(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        if self.order_manager:
            self.order_manager.update_order_status(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        else:
            self.logger.warning(f"Received orderStatus for {orderId} but Order Manager not assigned.")

    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState):
        super().openOrder(orderId, contract, order, orderState)
        self.broker_open_orders[orderId] = {'order': order, 'orderState': orderState, 'contract': contract}
        self.logger.debug(f"Received open order: ID={orderId}, Status={orderState.status}, Symbol={contract.symbol}")

    def openOrderEnd(self):
        super().openOrderEnd()
        self.logger.info("Open Order data end received.")
        if self.order_manager:
            self.order_manager.reconcile_orders(self.broker_open_orders)
        else:
            self.logger.warning("Order Manager not assigned, cannot reconcile open orders.")
        self.open_orders_received.set()

    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        super().execDetails(reqId, contract, execution)
        if self.order_manager:
             exec_time_utc = self._parse_ibkr_timestamp(execution.time)
             self.order_manager.handle_execution(execution, contract, exec_time_utc)
        else:
            self.logger.warning(f"Received execDetails for OrderID {execution.orderId} but Order Manager not assigned.")

    def execDetailsEnd(self, reqId: int):
        super().execDetailsEnd(reqId)
        self.logger.debug(f"Execution Details End received (ReqId: {reqId}).")


    def commissionReport(self, commissionReport: CommissionReport):
        super().commissionReport(commissionReport)
        self.logger.info(f"Commission Report - ExecID:{commissionReport.execId}, Comm:{commissionReport.commission} {commissionReport.currency}, RealizedPnL:{commissionReport.realizedPNL}")
        try:
            if self.portfolio_manager:
                report_time = datetime.now(pytz.utc)
                try:
                    parts = commissionReport.execId.split('.')
                    if len(parts) > 1 and len(parts[1]) == 8:
                         date_str = parts[1]
                         naive_dt = datetime.now().replace(year=int(date_str[0:4]), month=int(date_str[4:6]), day=int(date_str[6:8]))
                         report_time = self.tws_local_tz.localize(naive_dt).astimezone(pytz.utc)
                except Exception: pass

                self.portfolio_manager.add_commission(
                    exec_id=commissionReport.execId, commission=commissionReport.commission,
                    currency=commissionReport.currency, timestamp=report_time
                )
            else:
                self.logger.warning("Portfolio Manager not assigned, cannot record commission.")
        except Exception as e:
            self.error_logger.error(f"Error processing commission report in PM: {e}", exc_info=True)


    # Market Data Callbacks
    def tickPrice(self, reqId: int, tickType: int, price: float, attrib):
        super().tickPrice(reqId, tickType, price, attrib)
        symbol = None
        with self.api_lock:
             symbol = self.active_market_data_reqs.get(reqId)

        if symbol:
            if symbol in self.unsubscribed_symbols or price <= 0: return
            tick_time_utc = datetime.now(pytz.utc)

            if tickType == 4: # Last price
                self.live_ticks_queue.put((symbol, tickType, price, None, tick_time_utc))
                if self.portfolio_manager:
                     self.portfolio_manager.update_latest_price(symbol, price, tick_time_utc)
            elif tickType in [1, 2, 9]: # Bid, Ask, Close
                 if self.portfolio_manager:
                     update_price = price if tickType == 9 else None
                     if update_price:
                         self.portfolio_manager.update_latest_price(symbol, update_price, tick_time_utc)


    def tickSize(self, reqId: int, tickType: int, size: int):
        super().tickSize(reqId, tickType, float(size))
        effective_size = float(size)

        symbol = None
        with self.api_lock:
            symbol = self.active_market_data_reqs.get(reqId)

        if symbol:
            if symbol in self.unsubscribed_symbols or effective_size < 0: return
            tick_time_utc = datetime.now(pytz.utc)

            if tickType == 5: # Last size
                 self.live_ticks_queue.put((symbol, tickType, None, effective_size, tick_time_utc))


    def historicalData(self, reqId: int, bar):
        super().historicalData(reqId, bar)
        symbol = None
        with self.api_lock:
             symbol = self.active_hist_data_reqs.get(reqId)

        if symbol and self.trading_bot:
            self.trading_bot.process_historical_bar(symbol, bar)
        elif symbol:
             self.logger.warning(f"Received historicalData for {symbol} but TradingBot reference is missing.")
        else:
            self.logger.warning(f"Received historicalData for unknown ReqId: {reqId}")


    def historicalDataEnd(self, reqId: int, start: str, end: str):
        super().historicalDataEnd(reqId, start, end)
        symbol = None
        with self.api_lock:
            symbol = self.active_hist_data_reqs.pop(reqId, None)

        if symbol is not None and self.trading_bot:
            self.logger.info(f"Historical data finished for {symbol} (ReqId: {reqId}) from {start} to {end}")
            self.trading_bot.finalize_historical_data(symbol)
        elif symbol:
             self.logger.warning(f"Received historicalDataEnd for {symbol} but TradingBot reference is missing.")
        else:
             self.logger.warning(f"Received historicalDataEnd for unknown or already ended ReqId: {reqId}")


    # --- API Actions ---
    def subscribe_market_data(self, symbol, req_id=None):
        with self.api_lock:
            if symbol in self.unsubscribed_symbols:
                self.logger.warning(f"Skipping subscription for {symbol}; previously marked unsubscribed.")
                return False
            contract = create_contract(symbol, self)
            if not contract:
                self.error_logger.error(f"Cannot subscribe: Failed to create contract for {symbol}")
                return False
            if req_id is None: req_id = self.get_next_req_id()
            existing_reqs = [k for k, v in self.active_market_data_reqs.items() if v == symbol]
            if existing_reqs:
                 self.logger.debug(f"{symbol} already subscribed with ReqId(s) {existing_reqs}. Skipping new subscription request {req_id}.")
                 return True
            self.active_market_data_reqs[req_id] = symbol
            self.logger.info(f"Subscribing to market data for {symbol} (ReqId: {req_id})")

        generic_tick_list = getattr(self.settings, "IBKR_GENERIC_TICKS", "")
        snapshot = False; regulatory_snapshot = False
        try:
            if not self.isConnected(): raise ConnectionError("API not connected")
            self.reqMktData(req_id, contract, generic_tick_list, snapshot, regulatory_snapshot, [])
            return True
        except Exception as e:
             self.error_logger.error(f"Exception during reqMktData for {symbol} (ReqId: {req_id}): {e}", exc_info=True)
             with self.api_lock: self.active_market_data_reqs.pop(req_id, None)
             return False

    @with_circuit_breaker(failure_threshold=5, recovery_timeout=60.0)
    def placeOrder(self, orderId, contract, order):
        if not self.isConnected():
            self.error_logger.error(f"Cannot place order {orderId}: API not connected.")
            raise ConnectionError("API not connected")
        try:
            if not isinstance(order.totalQuantity, (int, float)) or order.totalQuantity <= 0:
                 self.error_logger.error(f"Order {orderId} has invalid quantity: {order.totalQuantity}")
                 return False
            time.sleep(0.05)
            self.logger.info(f"Placing Order -> ID:{orderId}, Symbol:{contract.symbol}, Action:{order.action}, Type:{order.orderType}, Qty:{order.totalQuantity}, LmtPx:{order.lmtPrice}, AuxPx:{order.auxPrice}, ParentId:{order.parentId}")
            super().placeOrder(orderId, contract, order)
            return True
        except Exception as e:
            self.error_logger.error(f"Exception in placeOrder (ID: {orderId}, Symbol: {contract.symbol}): {e}", exc_info=True)
            raise  # Re-raise to trigger circuit breaker


    def cancelOrder(self, orderId, manualCancelTime=""):
         if not self.isConnected():
             self.error_logger.error(f"Cannot cancel order {orderId}: API not connected.")
             return False
         try:
             self.logger.info(f"Requesting Cancellation -> ID: {orderId}")
             super().cancelOrder(orderId, manualCancelTime)
             return True
         except Exception as e:
              self.error_logger.error(f"Exception in cancelOrder (ID: {orderId}): {e}", exc_info=True)
              return False

    def cancelMktData(self, reqId):
         symbol = "Unknown"
         with self.api_lock:
              symbol = self.active_market_data_reqs.get(reqId, 'Unknown')

         if not self.isConnected():
              self.error_logger.warning(f"Cannot cancel Mkt Data Req {reqId} ({symbol}): API not connected.")
              with self.api_lock: self.active_market_data_reqs.pop(reqId, None)
              return False
         try:
             self.logger.info(f"Cancelling Market Data Subscription -> ReqId: {reqId}, Symbol: {symbol}")
             super().cancelMktData(reqId)
             with self.api_lock: self.active_market_data_reqs.pop(reqId, None)
             return True
         except Exception as e:
              self.error_logger.error(f"Exception cancelling Mkt Data Req {reqId} ({symbol}): {e}", exc_info=True)
              with self.api_lock: self.active_market_data_reqs.pop(reqId, None)
              return False

    # --- Utility ---
    def is_connected(self):
         client_connected = False
         try: client_connected = super().isConnected()
         except Exception: client_connected = False

         if not client_connected and self.connected:
              self.logger.warning("Internal 'connected' flag was True, but EClient.isConnected() is False. Updating internal state.")
              self.connected = False
              self.connection_status = "Disconnected (Implicit)"
              self.api_ready.clear()
         elif client_connected and not self.connected:
              self.logger.warning("Internal 'connected' flag was False, but EClient.isConnected() is True. Correcting internal state.")
              self.connected = True
              self.connection_status = "Connected (Implicit)"

         return self.connected and client_connected