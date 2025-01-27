import sys
import threading
import time
import queue
import re
import pandas as pd
from datetime import datetime

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.execution import Execution
from ibapi.order import Order

from config.credentials import IBKR
from utils.logger import setup_logger

from contract_utils import create_contract


class IBKRApi(EWrapper, EClient):
    def __init__(self, trading_bot):
        EClient.__init__(self, self)
        EWrapper.__init__(self)

        self.logger = setup_logger(__name__, 'logs/app.log', level=trading_bot.settings.LOG_LEVEL)
        self.connected = False
        self.account_id = IBKR['ACCOUNT_ID']
        self.lock = threading.Lock()
        self.executions = {}
        self.trading_bot = trading_bot
        self.request_retries = {}
        self.max_retries = 3
        self.retry_delay = 5

        # Queue for real-time ticks
        self.live_ticks_queue = queue.Queue()

        # Order ID management
        self._next_valid_order_id = None
        self._order_id_lock = threading.Lock()

        # Reconnect guard
        self.reconnecting = False

        # 10091 unsubscribed symbols
        self.unsubscribed_symbols = set()

        # Delayed data usage
        self.using_delayed_data = False

        # Snapshot quotes usage
        self.use_snapshot_quotes = False
        self.remaining_snapshots = None
        self.snapshot_requests = {}

        # Real-time sources
        self.real_time_sources = []

        # Map from reqId -> symbol
        self.trading_bot.market_data_req_ids = {}

    def connect_app(self):
        """Connect to IBKR's TWS or Gateway."""
        self.logger.info("Attempting to connect to TWS...")
        self.connect(IBKR['TWS_HOST'], IBKR['TWS_PORT'], IBKR['CLIENT_ID'])
        self.connected = True
        self.reconnecting = False

        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()

        # Default market data type (1 = live)
        self.reqMarketDataType(1)

        if self.use_snapshot_quotes:
            self.fetch_snapshot_quota()

        self.reqAccountUpdatesMulti(9002, self.account_id, "Core", True)
        self.logger.info("Subscribed to real-time account updates with model code 'Core'.")
        time.sleep(1)
        self.logger.info("Connected to IBKR TWS")

        # Auto-subscribe to market data
        self.subscribe_based_on_mode()

    def disconnect_app(self):
        self.disconnect()
        self.connected = False
        self.logger.info("Disconnected from IBKR TWS")

    def subscribe_based_on_mode(self):
        mode = self.trading_bot.settings.TRADING_MODE
        instruments = self.trading_bot.settings.TRADE_INSTRUMENTS
        for symbol in instruments:
            self.subscribe_market_data(symbol, snapshot=self.use_snapshot_quotes)

    def fetch_snapshot_quota(self):
        """Fetch the remaining snapshot quota via reqAccountSummary."""
        self.logger.info("Requesting snapshot quota details from IBKR...")
        self.reqAccountSummary(9001, "All", "AvailableSnapshots")

    def accountSummary(self, reqId, account, tag, value, currency):
        super().accountSummary(reqId, account, tag, value, currency)
        if tag == "AvailableSnapshots":
            try:
                self.remaining_snapshots = int(value)
                self.logger.info(f"Fetched snapshot quota: {self.remaining_snapshots}")
                if self.trading_bot:
                    self.trading_bot.update_snapshot_quota(self.remaining_snapshots)
            except ValueError:
                self.logger.error(f"Could not parse AvailableSnapshots value: {value}")
        else:
            self.logger.debug(f"Account Summary - {tag}: {value} {currency}")

    def accountSummaryEnd(self, reqId):
        super().accountSummaryEnd(reqId)
        if reqId == 9001:
            self.logger.info("Snapshot quota retrieval completed.")

    def accountUpdateMulti(self, reqId, account, modelCode, key, value, currency):
        """Handle real-time account updates (older TWS/ibapi signature)."""
        super().accountUpdateMulti(reqId, account, modelCode, key, value, currency)
        if key == "TotalCashValue" and currency == "USD":
            try:
                with self.trading_bot.lock:
                    self.trading_bot.settings.TOTAL_CAPITAL = float(value)
                    self.trading_bot.logger.debug(
                        f"Updated TOTAL_CAPITAL to {value} USD based on account update."
                    )
            except ValueError:
                self.trading_bot.logger.error(f"Invalid TotalCashValue: {value}")

    def get_next_order_id(self):
        with self._order_id_lock:
            while self._next_valid_order_id is None:
                self.logger.warning("Waiting for nextValidId from IBKR...")
                time.sleep(0.5)
            order_id = self._next_valid_order_id
            self._next_valid_order_id += 1
            return order_id

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        symbol = self.trading_bot.market_data_req_ids.get(reqId, "Unknown Symbol")

        # Info messages
        if errorCode in [2104, 2106, 2158]:
            self.logger.info(f"IBKR status message: {errorString}")
            return

        # Specific "10091" subscription error
        if errorCode == 10091:
            self.logger.error(
                f"IBKR Subscription Error (10091): Symbol {symbol} requires additional "
                f"market data subscription. Skipping further requests."
            )
            if symbol != "Unknown Symbol":
                self.unsubscribed_symbols.add(symbol)
                if self.trading_bot:
                    self.trading_bot.logger.warning(
                        f"Symbol {symbol} unsubscribed due to insufficient market data subscription."
                    )
            return

        self.logger.error(f"Error {errorCode} for request {reqId}: {errorString}")

        # Connectivity or data errors
        transient_errors = [1100, 1101, 1102, 504]
        if errorCode in transient_errors:
            self.logger.warning("Transient/connectivity error detected. Attempting to reconnect.")
            self.schedule_reconnect()
        elif errorCode in [162, 200, 300]:
            self.retry_request(reqId)
        elif errorCode == 202:
            self.logger.warning(f"Order cancellation/rejection for request {reqId}.")
        else:
            self.logger.error(f"Unhandled error code {errorCode}: {errorString}")

    def schedule_reconnect(self, delay=5):
        if not self.reconnecting:
            self.reconnecting = True
            if self.connected:
                self.disconnect_app()
            self.logger.info(f"Attempting to reconnect in {delay} seconds...")
            threading.Timer(delay, self.connect_app).start()

    def retry_request(self, reqId):
        symbol = self.trading_bot.market_data_req_ids.get(reqId)
        retries = self.request_retries.get(reqId, 0)
        if retries < self.max_retries:
            self.request_retries[reqId] = retries + 1
            self.logger.info(f"Retrying request {reqId} for {symbol} (Retry {retries + 1})")
            threading.Timer(self.retry_delay, self.resend_request, args=(reqId,)).start()
        else:
            self.logger.error(f"Max retries reached for request {reqId} ({symbol}).")

    def resend_request(self, reqId):
        symbol = self.trading_bot.market_data_req_ids.get(reqId)
        if symbol:
            if symbol in self.unsubscribed_symbols:
                self.logger.warning(f"Symbol {symbol} unsubscribed (10091). Not resending.")
                return
            self.logger.info(f"Resending request {reqId} for {symbol}")
            self.subscribe_market_data(symbol, req_id=reqId)
        else:
            self.logger.error(f"No symbol found for reqId {reqId} during resend")

    def nextValidId(self, orderId):
        super().nextValidId(orderId)
        with self._order_id_lock:
            if self._next_valid_order_id is None or orderId > self._next_valid_order_id:
                self._next_valid_order_id = orderId
        self.logger.info(f"Next valid order ID set to: {orderId}")

    def subscribe_market_data(self, symbol, req_id=None, snapshot=None):
        if symbol in self.unsubscribed_symbols:
            self.logger.warning(f"Skipping subscription for {symbol}; unsubscribed (10091).")
            return

        contract = create_contract(symbol)
        if req_id is None:
            req_id = self.trading_bot.req_id_counter
            self.trading_bot.req_id_counter += 1

        snapshot_flag = snapshot if snapshot is not None else self.use_snapshot_quotes

        if snapshot_flag and self.remaining_snapshots is not None and self.remaining_snapshots <= 0:
            self.logger.info("Snapshots exhausted. Switching to next data source.")
            snapshot_flag = False
            self.use_snapshot_quotes = False

        self.snapshot_requests[req_id] = snapshot_flag

        self.logger.info(
            f"Subscribing to market data for {symbol} reqId={req_id}, snapshot={snapshot_flag}"
        )
        self.reqMktData(
            reqId=req_id,
            contract=contract,
            genericTickList="",
            snapshot=snapshot_flag,
            regulatorySnapshot=False,
            mktDataOptions=[]
        )
        self.trading_bot.market_data_req_ids[req_id] = symbol

    def historicalData(self, reqId, bar):
        symbol = self.trading_bot.market_data_req_ids.get(reqId)
        if symbol is None:
            self.logger.error(f"No symbol found for reqId {reqId} in historicalData.")
            return

        if symbol not in self.trading_bot.market_data:
            self.trading_bot.market_data[symbol] = pd.DataFrame(
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )

        dt_str = bar.date.strip()
        dt_str_clean = re.sub(r'\s+[A-Za-z_/]+$', '', dt_str)

        parsed_time = None
        try:
            parsed_time = datetime.strptime(dt_str_clean, '%Y%m%d  %H:%M:%S')
        except ValueError:
            try:
                parsed_time = datetime.strptime(dt_str_clean, '%Y%m%d')
            except ValueError:
                self.logger.error(f"Could not parse historical date string: {bar.date}")
                return

        new_row = pd.DataFrame([{
            'timestamp': parsed_time,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume
        }])

        if not new_row.empty and not new_row.isna().all().all():
            existing_df = self.trading_bot.market_data[symbol]
            self.trading_bot.market_data[symbol] = pd.concat(
                [existing_df, new_row], ignore_index=True
            )
        else:
            self.logger.warning(
                f"Skipping concat for {symbol}: new_row empty or all-NA ({dt_str_clean})."
            )

    def historicalDataEnd(self, reqId, start, end):
        symbol = self.trading_bot.market_data_req_ids.get(reqId)
        if symbol is not None:
            self.trading_bot.save_market_data(symbol, data_type='historical')
            self.logger.info(f"Historical data received and saved for {symbol}")
        else:
            self.logger.error(f"No symbol found for reqId {reqId} in historicalDataEnd.")

    def tickPrice(self, reqId, tickType, price, attrib):
        symbol = self.trading_bot.market_data_req_ids.get(reqId)
        if symbol is not None:
            if symbol in self.unsubscribed_symbols:
                return

            if reqId in self.snapshot_requests and self.snapshot_requests[reqId]:
                if self.remaining_snapshots is not None and self.remaining_snapshots > 0:
                    self.remaining_snapshots -= 1
                    self.logger.info(
                        f"Snapshot used for {symbol}, remaining={self.remaining_snapshots}"
                    )
                del self.snapshot_requests[reqId]

            tick_time = datetime.now()
            self.live_ticks_queue.put((symbol, tickType, price, None, tick_time))
            self.logger.debug(f"tickPrice -> queue: {symbol} {tickType} {price}")
        else:
            self.logger.error(f"No symbol found for reqId {reqId} in tickPrice.")

    def tickSize(self, reqId, tickType, size):
        symbol = self.trading_bot.market_data_req_ids.get(reqId)
        if symbol is not None:
            if symbol in self.unsubscribed_symbols:
                return

            tick_time = datetime.now()
            self.live_ticks_queue.put((symbol, tickType, None, size, tick_time))
            self.logger.debug(f"tickSize -> queue: {symbol} {tickType} {size}")
        else:
            self.logger.error(f"No symbol found for reqId {reqId} in tickSize.")

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId,
                    parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        self.logger.info(
            f"Order Status - orderId={orderId}, status={status}, "
            f"filled={filled}, remaining={remaining}, avgFillPrice={avgFillPrice}"
        )
        if filled > 0 and remaining > 0:
            self.logger.info(
                f"Partial fill detected for orderId {orderId}. Filled={filled}, Remaining={remaining}"
            )

    def execDetails(self, reqId, contract, execution):
        with self.lock:
            self.executions[execution.orderId] = execution
            self.logger.info(f"Execution details for order {execution.orderId}")
            self.trading_bot.handle_execution(execution, contract)

    def execDetailsEnd(self, reqId):
        self.logger.info(f"Execution details ended for request {reqId}")

    def commissionReport(self, commissionReport):
        self.logger.info(f"Commission Report: {commissionReport}")

    def position(self, account, contract, position, avgCost):
        self.logger.info(
            f"Position - Acct: {account}, Symbol: {contract.symbol}, "
            f"Pos: {position}, AvgCost: {avgCost}"
        )

    def positionEnd(self):
        self.logger.info("Position data end")

    def get_next_min_trade_size(self, symbol):
        """Example for dynamic min trade size."""
        if '/' in symbol:
            return 0.0001  # fractional for crypto
        else:
            return 1       # integer for stocks
