# managers/order_manager.py
import threading
import time
from datetime import datetime, timezone
import pytz # Import pytz
from ibapi.order import Order # Import only Order
# Import the sets defined in ibkr_api.py
from api.ibkr_api import ORDER_FINAL_STATES, ORDER_ACTIVE_STATES
from ibapi.contract import Contract
from ibapi.execution import Execution
from utils.logger import setup_logger
from config.settings import Settings
from contract_utils import create_contract

# Note: ORDER_ACTIVE_STATES is also defined in ibkr_api.py, importing it is preferred
# to keep definitions consistent. Redefining it here is less ideal.
# Let's rely on the imported version.
# ORDER_ACTIVE_STATES = {"PendingSubmit", "PreSubmitted", "Submitted", "ApiPending"}

class OrderManager:
    """
    Manages the lifecycle of orders, including placement, status tracking,
    and interaction with the PortfolioManager upon execution. Uses UTC timestamps internally.
    """
    def __init__(self, api, portfolio_manager, settings, logger=None):
        self.api = api
        self.portfolio_manager = portfolio_manager
        self.settings = settings
        self.logger = logger or setup_logger('order_manager', 'logs/app.log', level=settings.LOG_LEVEL)
        self.trade_logger = setup_logger('trade_logger', 'logs/trade_logs/trades.log', level=settings.LOG_LEVEL)
        self.error_logger = setup_logger('error_logger', 'logs/error_logs/errors.log', level='ERROR')

        # Stores active orders: {order_id: {'order': Order, 'contract': Contract, 'status': str, 'strategy': str, ...}}
        self.active_orders = {}
        self._lock = threading.Lock()
        self.bracket_orders = {} # {parent_id: {'stop_id': int, 'profit_id': int}}
        self.order_strategy_mapping = {}
        self.open_orders_received = False # Flag for reconciliation

    def get_order_details(self, order_id):
        """ Safely gets details for an active order. """
        with self._lock:
            return self.active_orders.get(order_id) # Returns None if not found

    def get_state(self):
        """Returns the current state for persistence (using UTC ISO format)."""
        with self._lock:
            serializable_orders = {}
            for order_id, data in self.active_orders.items():
                 # Ensure Order/Contract details are serializable (store key info)
                 serializable_orders[order_id] = {
                     'order_details': {
                         'action': data['order'].action, 'orderType': data['order'].orderType,
                         'totalQuantity': data['order'].totalQuantity, 'lmtPrice': data['order'].lmtPrice,
                         'auxPrice': data['order'].auxPrice, 'transmit': data['order'].transmit,
                         'parentId': data['order'].parentId, 'tif': data['order'].tif,
                     },
                     'contract_details': {
                         'symbol': data['contract'].symbol, 'secType': data['contract'].secType,
                         'currency': data['contract'].currency, 'exchange': data['contract'].exchange,
                     },
                     'status': data['status'],
                     'strategy': data['strategy'],
                     'parent_id': data.get('parent_id'),
                     'children_ids': data.get('children_ids', []),
                     # Add creation/update time if needed, store as ISO UTC string
                     'last_update_utc': data.get('last_update_utc', pytz.utc.localize(datetime.utcnow())).isoformat()
                 }
            return {
                'active_orders': serializable_orders,
                'bracket_orders': self.bracket_orders,
                'order_strategy_mapping': self.order_strategy_mapping
            }

    def load_state(self, state):
        """Loads the state into the OrderManager (parsing UTC ISO format)."""
        with self._lock:
            self.bracket_orders = state.get('bracket_orders', {})
            self.order_strategy_mapping = state.get('order_strategy_mapping', {})
            loaded_orders = state.get('active_orders', {})

            self.active_orders = {} # Clear existing
            now_utc = pytz.utc.localize(datetime.utcnow())
            for order_id_str, data in loaded_orders.items():
                try:
                    order_id = int(order_id_str)
                    # Reconstruct Order
                    order = Order()
                    details = data.get('order_details', {})
                    order.action = details.get('action')
                    order.orderType = details.get('orderType')
                    order.totalQuantity = float(details.get('totalQuantity', 0)) # Ensure float
                    order.lmtPrice = float(details.get('lmtPrice', float('inf'))) # Use inf/nan?
                    order.auxPrice = float(details.get('auxPrice', float('inf')))
                    order.transmit = details.get('transmit', True)
                    order.parentId = int(details.get('parentId', 0))
                    order.tif = details.get('tif', 'GTC')

                    # Reconstruct Contract
                    contract_details = data.get('contract_details', {})
                    contract = Contract()
                    contract.symbol = contract_details.get('symbol')
                    contract.secType = contract_details.get('secType')
                    contract.currency = contract_details.get('currency')
                    contract.exchange = contract_details.get('exchange')

                    # Parse last update time
                    last_update_utc = now_utc
                    if 'last_update_utc' in data:
                        try:
                           last_update_utc = datetime.fromisoformat(data['last_update_utc'].replace('Z', '+00:00'))
                        except ValueError: pass # Keep default now_utc


                    self.active_orders[order_id] = {
                        'order': order, 'contract': contract,
                        'status': data.get('status', 'Unknown'), # Mark Unknown until reconciled
                        'strategy': data.get('strategy', 'Unknown'),
                        'parent_id': data.get('parent_id'),
                        'children_ids': data.get('children_ids', []),
                        'last_update_utc': last_update_utc
                    }
                except Exception as e:
                    self.error_logger.error(f"Error reconstructing order {order_id_str} from state: {e}", exc_info=True)

            self.logger.info(f"OrderManager state loaded. Active orders: {len(self.active_orders)}")
            # Reset reconciliation flag, needs broker data
            self.open_orders_received = False


    def reconcile_orders(self, broker_open_orders):
        """ Compares local state with broker's open orders. """
        with self._lock:
            self.logger.info(f"Reconciling orders. Local active: {len(self.active_orders)}, Broker open: {len(broker_open_orders)}")
            # Use the imported set ORDER_FINAL_STATES
            local_active_ids = set(oid for oid, data in self.active_orders.items() if data['status'] not in ORDER_FINAL_STATES)
            broker_open_ids = set(broker_open_orders.keys())
            now_utc = pytz.utc.localize(datetime.utcnow())

            # Orders active locally but NOT reported as open by broker
            potentially_inactive_ids = local_active_ids - broker_open_ids
            for order_id in potentially_inactive_ids:
                old_status = self.active_orders[order_id]['status']
                self.active_orders[order_id]['status'] = 'Inactive' # Mark as likely inactive/filled/cancelled
                self.active_orders[order_id]['last_update_utc'] = now_utc
                self.logger.warning(f"Order {order_id} (Status: {old_status}) active locally but not reported open by broker. Marked Inactive.")

            # Orders reported open by broker but NOT active locally
            missing_locally_ids = broker_open_ids - local_active_ids
            for order_id in missing_locally_ids:
                broker_data = broker_open_orders[order_id]
                # Check if it exists at all locally, or if status is final/inactive
                local_entry = self.active_orders.get(order_id)
                # Use the imported set ORDER_FINAL_STATES
                if local_entry is None or local_entry['status'] in ORDER_FINAL_STATES or local_entry['status'] == 'Inactive':
                    self.logger.warning(f"Order {order_id} reported open by broker but missing or inactive locally. Adding/Updating.")
                    # broker_data from openOrder contains 'order', 'orderState', 'contract'
                    self.active_orders[order_id] = {
                        'order': broker_data['order'],
                        'contract': broker_data['contract'],
                        'status': broker_data['orderState'].status, # Get status string from orderState object
                        'strategy': self.order_strategy_mapping.get(order_id, 'Unknown'),
                        'parent_id': broker_data['order'].parentId if broker_data['order'].parentId != 0 else None,
                        'children_ids': [], # Cannot determine children here
                        'last_update_utc': now_utc
                    }
                # Else: it exists locally and is active, status updated below

            # Update status for orders present in both, ensuring consistency
            matching_ids = local_active_ids.intersection(broker_open_ids)
            for order_id in matching_ids:
                 # broker_data from openOrder contains 'order', 'orderState', 'contract'
                 broker_status = broker_open_orders[order_id]['orderState'].status # Get status string
                 if self.active_orders[order_id]['status'] != broker_status:
                     self.logger.info(f"Updating status for order {order_id}: {self.active_orders[order_id]['status']} -> {broker_status}")
                     self.active_orders[order_id]['status'] = broker_status
                     self.active_orders[order_id]['last_update_utc'] = now_utc


            self.logger.info("Order reconciliation complete.")
            self.open_orders_received = True


    def create_and_place_bracket_order(self, symbol, action, quantity, entry_price, stop_loss_price, take_profit_price, strategy_name):
        """Creates and places a bracket order (parent + stop + profit taker)."""
        with self._lock:
            contract = create_contract(symbol)
            if not contract:
                self.error_logger.error(f"Could not create contract for symbol: {symbol}")
                return None, None, None

            # --- Rate Limiting ---
            time.sleep(0.1) # Basic delay

            # --- Get Order IDs ---
            try:
                 parent_order_id = self.api.get_next_order_id()
                 stop_order_id = self.api.get_next_order_id()
                 profit_order_id = self.api.get_next_order_id()
            except (TimeoutError, ConnectionError) as e:
                 self.error_logger.error(f"Failed to get order IDs for bracket order {symbol}: {e}")
                 return None, None, None

            # Ensure quantity is appropriate type/precision
            # TODO: Get quantity precision rules based on contract details if possible
            order_quantity = round(quantity, 8) # Use generous precision for crypto/forex

            # --- Parent Order ---
            parent_order = Order()
            parent_order.action = action
            parent_order.orderType = self.settings.ORDER_TYPE
            parent_order.totalQuantity = order_quantity
            if self.settings.ORDER_TYPE == 'LMT':
                 parent_order.lmtPrice = round(entry_price, 8)
            parent_order.transmit = False
            parent_order.tif = "GTC"

            # --- Stop Loss Order ---
            stop_order = Order()
            stop_order.action = "SELL" if action == "BUY" else "BUY"
            stop_order.orderType = "STP"
            stop_order.auxPrice = round(stop_loss_price, 8)
            stop_order.totalQuantity = order_quantity
            stop_order.parentId = parent_order_id
            stop_order.transmit = False
            stop_order.tif = "GTC"

            # --- Take Profit Order ---
            profit_order = Order()
            profit_order.action = "SELL" if action == "BUY" else "BUY"
            profit_order.orderType = "LMT"
            profit_order.lmtPrice = round(take_profit_price, 8)
            profit_order.totalQuantity = order_quantity
            profit_order.parentId = parent_order_id
            profit_order.transmit = True # Last order transmits
            profit_order.tif = "GTC"

            # Store orders before placing
            now_utc = pytz.utc.localize(datetime.utcnow())
            self.active_orders[parent_order_id] = {'order': parent_order, 'contract': contract, 'status': 'PendingSubmit', 'strategy': strategy_name, 'parent_id': None, 'children_ids': [stop_order_id, profit_order_id], 'last_update_utc': now_utc}
            self.active_orders[stop_order_id] = {'order': stop_order, 'contract': contract, 'status': 'PendingSubmit', 'strategy': strategy_name + "_SL", 'parent_id': parent_order_id, 'children_ids': [], 'last_update_utc': now_utc}
            self.active_orders[profit_order_id] = {'order': profit_order, 'contract': contract, 'status': 'PendingSubmit', 'strategy': strategy_name + "_TP", 'parent_id': parent_order_id, 'children_ids': [], 'last_update_utc': now_utc}

            self.bracket_orders[parent_order_id] = {'stop_id': stop_order_id, 'profit_id': profit_order_id}
            self.order_strategy_mapping[parent_order_id] = strategy_name
            self.order_strategy_mapping[stop_order_id] = strategy_name + "_SL"
            self.order_strategy_mapping[profit_order_id] = strategy_name + "_TP"

            # Place orders via API
            orders_to_place = [
                (parent_order_id, contract, parent_order),
                (stop_order_id, contract, stop_order),
                (profit_order_id, contract, profit_order)
            ]
            success = True
            placed_ids = []
            for oid, c, o in orders_to_place:
                 if not self.api.placeOrder(oid, c, o):
                     self.error_logger.error(f"Failed to place order ID {oid} via API.")
                     success = False
                     # Attempt to cancel already placed parts of the bracket if one fails? Complex.
                     break
                 else:
                      placed_ids.append(oid)
                 time.sleep(0.1) # Delay between placements

            if success:
                self.trade_logger.info(
                    f"Submitted bracket order: ParentID={parent_order_id} (SL:{stop_order_id}, TP:{profit_order_id}) "
                    f"for {action} {order_quantity} {symbol} @ ~{entry_price:.5f} (SL={stop_loss_price:.5f}, TP={take_profit_price:.5f})"
                )
                return parent_order_id, stop_order_id, profit_order_id
            else:
                # Clean up internally if placement failed
                self.error_logger.error(f"Bracket order placement failed for {symbol}. Cleaning up internal state.")
                self._remove_order_internal(parent_order_id)
                self._remove_order_internal(stop_order_id)
                self._remove_order_internal(profit_order_id)
                # TODO: Attempt to cancel any orders actually placed via API?
                for placed_id in placed_ids:
                     self.logger.info(f"Attempting cancellation of potentially placed order ID {placed_id} due to bracket failure.")
                     self.cancel_order(placed_id)
                return None, None, None


    def update_order_status(self, order_id, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        """Callback from IBKRApi's orderStatus."""
        with self._lock:
            now_utc = pytz.utc.localize(datetime.utcnow())
            if order_id in self.active_orders:
                order_data = self.active_orders[order_id]
                # Update only if status changes or significant fill info changes
                if order_data['status'] != status or order_data.get('filled') != filled:
                    order_data['status'] = status
                    order_data['filled'] = filled
                    order_data['remaining'] = remaining
                    order_data['avgFillPrice'] = avgFillPrice
                    order_data['last_update_utc'] = now_utc

                    self.logger.info(f"OrderStatus Update - ID:{order_id}, Status:{status}, Filled:{filled}, Remaining:{remaining}, AvgFillPrice:{avgFillPrice}")

                    # Handle final states
                    # Use the imported set ORDER_FINAL_STATES
                    if status in ORDER_FINAL_STATES:
                        self._handle_final_status(order_id, status)
            else:
                # Received status for an unknown or already inactive/final order
                 # Use the imported sets ORDER_ACTIVE_STATES and ORDER_FINAL_STATES
                 if status not in ORDER_ACTIVE_STATES and status not in ORDER_FINAL_STATES:
                    # Log unexpected statuses for unknown orders
                    self.logger.warning(f"Received status '{status}' for unknown or inactive order ID: {order_id}")


    def _handle_final_status(self, order_id, status):
        """Internal logic when an order reaches a final state."""
        if order_id not in self.active_orders: return

        order_data = self.active_orders[order_id]
        parent_id = order_data.get('parent_id')
        now_utc = pytz.utc.localize(datetime.utcnow())

        self.logger.info(f"Order {order_id} reached final state: {status}. Parent ID: {parent_id}")
        order_data['last_update_utc'] = now_utc # Update timestamp

        # If a child order (SL or TP) finishes, cancel the other child
        if parent_id is not None and parent_id in self.bracket_orders:
            bracket_info = self.bracket_orders[parent_id]
            stop_id = bracket_info['stop_id']
            profit_id = bracket_info['profit_id']
            sibling_id = None

            if order_id == stop_id: sibling_id = profit_id
            elif order_id == profit_id: sibling_id = stop_id

            if sibling_id:
                 # Check if sibling exists and is active before cancelling
                 sibling_data = self.active_orders.get(sibling_id)
                 # Use the imported set ORDER_FINAL_STATES
                 if sibling_data and sibling_data['status'] not in ORDER_FINAL_STATES:
                     self.logger.info(f"Order {order_id} (child of {parent_id}) is final ({status}). Cancelling sibling order {sibling_id}.")
                     self.cancel_order(sibling_id)

            # Consider removing bracket mapping once one leg finishes?
            # Maybe keep it until parent is confirmed final?
            # For now, let's remove it to prevent duplicate cancellations
            if parent_id in self.bracket_orders:
                 del self.bracket_orders[parent_id]


        # If the parent order is cancelled, cancel its children
        elif parent_id is None and order_id in self.bracket_orders: # It's a parent
            if status == 'Cancelled':
                bracket_info = self.bracket_orders[order_id]
                for child_id in [bracket_info.get('stop_id'), bracket_info.get('profit_id')]:
                    if child_id:
                        child_data = self.active_orders.get(child_id)
                        # Use the imported set ORDER_FINAL_STATES
                        if child_data and child_data['status'] not in ORDER_FINAL_STATES:
                            self.logger.info(f"Parent order {order_id} cancelled. Cancelling child order {child_id}.")
                            self.cancel_order(child_id)
            # Remove bracket mapping once parent is final
            if order_id in self.bracket_orders:
                 del self.bracket_orders[order_id]

        # Don't remove order from active_orders immediately, PortfolioManager might need details via handle_execution.
        # Status is marked final, which prevents further actions like cancellation.


    def handle_execution(self, execution: Execution, contract: Contract, timestamp_utc: datetime):
        """
        Callback from IBKRApi's execDetails. Updates portfolio.
        Args:
            execution (Execution): The execution object from IBKR.
            contract (Contract): The contract object.
            timestamp_utc (datetime): Aware UTC datetime of the execution.
        """
        with self._lock:
            order_id = execution.orderId
            exec_id = execution.execId
            symbol = f"{contract.symbol}/{contract.currency}" if contract.secType in ["CASH", "CRYPTO"] else contract.symbol

            self.logger.info(f"Received execution: OrderID={order_id}, ExecID={exec_id}, Symbol={symbol}, Side={execution.side}, Qty={execution.shares}, Price={execution.price}, Time={timestamp_utc.isoformat()}")

            if order_id in self.active_orders:
                order_data = self.active_orders[order_id]
                strategy = order_data.get('strategy', self.order_strategy_mapping.get(order_id, 'Unknown'))

                # Update Portfolio Manager
                self.portfolio_manager.update_position_from_fill(
                    symbol=symbol,
                    action='BUY' if execution.side == 'BOT' else 'SELL',
                    quantity=execution.shares, # IB uses float for shares/qty
                    price=execution.price,
                    timestamp_utc=timestamp_utc, # Pass aware UTC time
                    order_id=order_id,
                    strategy=strategy,
                    exec_id=exec_id # Pass exec_id
                )

                # Log the trade execution detail
                self.trade_logger.info(
                     f"Execution Detail: OrderID={order_id}, ExecID={exec_id}, Symbol={symbol}, Side={execution.side}, "
                     f"Qty={execution.shares}, Price={execution.price}, Strategy={strategy}, Time={timestamp_utc.isoformat()}"
                 )

                # Optional: Store execId against order_id for commission matching?
                # if 'executions' not in order_data: order_data['executions'] = []
                # order_data['executions'].append({'exec_id': exec_id, 'qty': execution.shares, 'price': execution.price})


            else:
                # Log execution for unknown orders, might be from previous session or manual trade
                self.logger.warning(f"Received execution details for unknown or inactive order ID: {order_id}. Processing position update.")
                # Still update portfolio manager as the position *did* change
                self.portfolio_manager.update_position_from_fill(
                     symbol=symbol,
                     action='BUY' if execution.side == 'BOT' else 'SELL',
                     quantity=execution.shares,
                     price=execution.price,
                     timestamp_utc=timestamp_utc,
                     order_id=order_id,
                     strategy='Unknown/Manual', # Mark strategy as unknown
                     exec_id=exec_id # Pass exec_id
                 )


    def cancel_order(self, order_id):
        """Requests cancellation of an active order."""
        with self._lock:
            order_data = self.active_orders.get(order_id)
            # Use the imported set ORDER_FINAL_STATES
            if order_data and order_data['status'] not in ORDER_FINAL_STATES:
                self.logger.info(f"Requesting cancellation for order ID: {order_id}")
                if not self.api.cancelOrder(order_id):
                     self.error_logger.error(f"API call to cancel order {order_id} failed.")
                     # Consider marking order as 'CancelFailed' or similar?
            elif order_data:
                 self.logger.warning(f"Attempted to cancel order {order_id} already in final state: {order_data['status']}")
            else:
                self.logger.warning(f"Attempted to cancel unknown order ID: {order_id}")


    def _remove_order_internal(self, order_id):
        """Removes an order from internal tracking. Use carefully only during cleanup."""
        with self._lock:
            if order_id in self.active_orders: del self.active_orders[order_id]
            if order_id in self.order_strategy_mapping: del self.order_strategy_mapping[order_id]
            if order_id in self.bracket_orders: del self.bracket_orders[order_id]
            # Removing from parent's children list is complex, skip for now

    def get_open_order_ids(self):
         """Returns a list of order IDs considered active (not in final state)."""
         with self._lock:
             # Use the imported set ORDER_FINAL_STATES
             return [oid for oid, data in self.active_orders.items() if data['status'] not in ORDER_FINAL_STATES]