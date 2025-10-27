# managers/portfolio_manager.py
import threading
from collections import deque  # For limited trade history
from datetime import date, datetime, timedelta

import numpy as np
import pytz  # Import pytz

from utils.logger import setup_logger


class PortfolioManager:
    """
    Manages the overall portfolio state, including positions, cash,
    P&L calculations, and drawdown tracking. Ensures thread safety for state access.
    Uses UTC timestamps internally and for state persistence.
    """

    def __init__(self, settings, logger=None):
        self.settings = settings
        self.logger = logger or setup_logger('PortfolioManager', 'logs/app.log', level=settings.LOG_LEVEL)
        self.trade_logger = setup_logger(
            'TradeLogger', 'logs/trade_logs/trades.log', level=settings.LOG_LEVEL
        )  # Reuse trade logger
        self.error_logger = setup_logger('PortfolioError', 'logs/error_logs/errors.log', level='ERROR')

        # Timezone setup
        try:
            self.default_tz = pytz.timezone(self.settings.TIMEZONE)
        except pytz.UnknownTimeZoneError:
            self.logger.warning(f"Unknown timezone '{self.settings.TIMEZONE}'. Using UTC.")
            self.default_tz = pytz.utc
        except Exception as e:
            self.logger.error(f'Error setting portfolio timezone: {e}. Using UTC.')
            self.default_tz = pytz.utc

        # --- Portfolio State (Protected by _lock) ---
        # positions = { symbol: {'quantity': float, 'average_price': float, 'last_update_utc': datetime}}
        self.positions = {}
        # Cache of latest prices {symbol: {'price': float, 'time_utc': datetime}}
        self._latest_prices = {}
        # Account Values (initialized, but prioritize broker updates)
        self.initial_capital = self.settings.TOTAL_CAPITAL
        self.current_cash = self.settings.TOTAL_CAPITAL  # Tracks available cash
        self.current_equity = self.settings.TOTAL_CAPITAL  # Tracks net liquidation value
        self.available_funds = self.settings.TOTAL_CAPITAL  # Tracks funds available for trading (often includes margin)
        # P&L Tracking
        self.realized_pnl_total = 0.0  # Cumulative realized PnL
        self.unrealized_pnl_total = 0.0  # Current unrealized PnL
        self.commissions_total = 0.0  # Cumulative commissions
        # Daily Tracking (relative to default_tz)
        self.daily_realized_pnl = 0.0
        self.daily_commissions = 0.0
        self._last_daily_reset_date = date.min  # Tracks the date of the last daily reset
        # Drawdown Tracking
        self.peak_equity = self.settings.TOTAL_CAPITAL  # Initialize peak equity
        self.current_drawdown_pct = 0.0  # Current drawdown percentage
        # Store broker-reported values for reference/reconciliation
        self.broker_reported_cash = None
        self.broker_reported_equity = None
        self.broker_reported_funds = None
        # Limited Trade History {deque allows efficient fixed-size history}
        self.trade_history = deque(maxlen=getattr(settings, 'MAX_TRADE_HISTORY_SIZE', 500))
        # --- End Portfolio State ---

        self._lock = threading.Lock()  # Lock to protect all shared state access

        # Mapping exec_id to trade details for commission matching (optional)
        self._exec_id_map = {}  # {exec_id: trade_dict_reference} - Needs careful memory management

    def _check_reset_daily_stats(self):
        """Checks if a new day (in default_tz) has started and resets daily stats."""
        # Called internally within locked methods
        now_local = datetime.now(self.default_tz)
        today_local = now_local.date()

        if today_local > self._last_daily_reset_date:
            self.logger.info(
                f'New day detected ({today_local} in {self.default_tz.zone}). Resetting daily PnL/Commissions.'
            )
            self.daily_realized_pnl = 0.0
            self.daily_commissions = 0.0
            self._last_daily_reset_date = today_local
            # Return True if reset occurred
            return True
        return False

    def get_state(self):
        """Returns the current state for persistence (thread-safe)."""
        with self._lock:
            # Convert datetime objects to aware UTC ISO strings
            serializable_positions = {}
            for symbol, data in self.positions.items():
                serializable_positions[symbol] = data.copy()
                last_update_utc = data.get('last_update_utc')
                if isinstance(last_update_utc, datetime):
                    serializable_positions[symbol]['last_update_utc'] = last_update_utc.isoformat()

            # Convert deque to list for serialization, ensure timestamps are strings
            serializable_trade_history = []
            for trade in list(self.trade_history):  # Convert deque to list
                trade_copy = trade.copy()
                trade_time_utc = trade.get('time_utc')
                if isinstance(trade_time_utc, datetime):
                    trade_copy['time_utc'] = trade_time_utc.isoformat()
                serializable_trade_history.append(trade_copy)

            return {
                'positions': serializable_positions,
                'current_cash': self.current_cash,
                'current_equity': self.current_equity,  # Persist last calculated equity
                'available_funds': self.available_funds,
                'realized_pnl_total': self.realized_pnl_total,
                'commissions_total': self.commissions_total,
                'peak_equity': self.peak_equity,
                'current_drawdown_pct': self.current_drawdown_pct,
                'trade_history': serializable_trade_history,
                # Daily stats are reset, maybe don't persist or persist with date?
                'last_daily_reset_date': self._last_daily_reset_date.isoformat()
                if self._last_daily_reset_date != date.min
                else None,
            }

    def load_state(self, state):
        """Loads the portfolio state (thread-safe)."""
        with self._lock:
            self.logger.info('Loading PortfolioManager state...')
            # Load values, prioritizing broker updates later
            self.current_cash = state.get('current_cash', self.settings.TOTAL_CAPITAL)
            self.current_equity = state.get('current_equity', self.settings.TOTAL_CAPITAL)
            self.available_funds = state.get('available_funds', self.settings.TOTAL_CAPITAL)
            self.realized_pnl_total = state.get('realized_pnl_total', 0.0)
            self.commissions_total = state.get('commissions_total', 0.0)
            self.peak_equity = state.get('peak_equity', self.current_equity)  # Initialize peak from loaded equity
            self.current_drawdown_pct = state.get('current_drawdown_pct', 0.0)

            # Load last daily reset date
            last_reset_str = state.get('last_daily_reset_date')
            if last_reset_str:
                try:
                    self._last_daily_reset_date = date.fromisoformat(last_reset_str)
                except (ValueError, TypeError):
                    self._last_daily_reset_date = date.min
            else:
                self._last_daily_reset_date = date.min
            # Force daily reset check after loading state
            self._check_reset_daily_stats()

            # Load trade history, converting timestamps back to aware UTC datetime
            loaded_history = state.get('trade_history', [])
            self.trade_history.clear()  # Clear existing deque
            for trade_data in loaded_history:
                trade_time_str = trade_data.get('time_utc')
                if isinstance(trade_time_str, str):
                    try:
                        trade_data['time_utc'] = datetime.fromisoformat(trade_time_str.replace('Z', '+00:00'))
                    except (ValueError, TypeError):
                        self.logger.warning(f"Could not parse trade time '{trade_time_str}' from state.")
                        trade_data['time_utc'] = datetime.now(pytz.utc)  # Fallback
                else:  # Handle cases where time might be missing or wrong type
                    trade_data['time_utc'] = datetime.now(pytz.utc)
                self.trade_history.append(trade_data)  # Append to deque

            # Load positions, converting timestamps back
            loaded_positions = state.get('positions', {})
            self.positions = {}  # Clear existing before loading
            for symbol, data in loaded_positions.items():
                last_update_str = data.get('last_update_utc')
                if isinstance(last_update_str, str):
                    try:
                        data['last_update_utc'] = datetime.fromisoformat(last_update_str.replace('Z', '+00:00'))
                    except (ValueError, TypeError):
                        self.logger.warning(
                            f"Could not parse last_update time '{last_update_str}' for {symbol} from state."
                        )
                        data['last_update_utc'] = datetime.now(pytz.utc)  # Fallback
                else:
                    data['last_update_utc'] = datetime.now(pytz.utc)

                # Basic validation
                if isinstance(data.get('quantity'), (int, float)) and isinstance(
                    data.get('average_price'), (int, float)
                ):
                    # Ensure zero quantity has zero average price
                    if abs(data['quantity']) < 1e-9:
                        data['average_price'] = 0.0
                    self.positions[symbol] = data
                else:
                    self.logger.warning(f'Skipping invalid position data for {symbol} from state file: {data}')

            self.logger.info(
                f'PortfolioManager state loaded. Positions: {len(self.positions)}, Equity: {self.current_equity:.2f}, Peak: {self.peak_equity:.2f}'
            )
            # Trigger recalculation based on loaded state (including UPL)
            self._recalculate_unrealized_pnl_and_equity()

    def reconcile_broker_values(self, account_details):
        """Updates cash, equity, funds based on broker's account summary (thread-safe)."""
        with self._lock:
            self.logger.debug(f'Reconciling account values with broker data: {account_details}')
            cash_updated = False
            equity_updated = False
            funds_updated = False
            base_currency = 'USD'  # TODO: Make configurable?

            # --- Reconcile Available Funds ---
            if (
                'AvailableFunds' in account_details
                and account_details['AvailableFunds'].get('currency') == base_currency
            ):
                try:
                    new_broker_funds = float(account_details['AvailableFunds']['value'])
                    # Update if significantly different
                    if self.broker_reported_funds is None or not np.isclose(
                        self.broker_reported_funds, new_broker_funds
                    ):
                        self.broker_reported_funds = new_broker_funds
                        self.available_funds = new_broker_funds  # Overwrite with broker value
                        self.logger.info(f'Reconciled Available Funds with Broker: {self.available_funds:.2f}')
                        funds_updated = True
                except (ValueError, TypeError) as e:
                    self.error_logger.warning(
                        f'Invalid AvailableFunds format from broker: {account_details["AvailableFunds"]} - {e}'
                    )

            # --- Reconcile Total Cash Value ---
            if (
                'TotalCashValue' in account_details
                and account_details['TotalCashValue'].get('currency') == base_currency
            ):
                try:
                    new_broker_cash = float(account_details['TotalCashValue']['value'])
                    if self.broker_reported_cash is None or not np.isclose(self.broker_reported_cash, new_broker_cash):
                        self.broker_reported_cash = new_broker_cash
                        self.current_cash = new_broker_cash  # Overwrite with broker value
                        self.logger.info(f'Reconciled Current Cash with Broker: {self.current_cash:.2f}')
                        cash_updated = True
                except (ValueError, TypeError) as e:
                    self.error_logger.warning(
                        f'Invalid TotalCashValue format from broker: {account_details["TotalCashValue"]} - {e}'
                    )

            # --- Reconcile Net Liquidation (Equity) ---
            if (
                'NetLiquidation' in account_details
                and account_details['NetLiquidation'].get('currency') == base_currency
            ):
                try:
                    new_broker_equity = float(account_details['NetLiquidation']['value'])
                    if self.broker_reported_equity is None or not np.isclose(
                        self.broker_reported_equity, new_broker_equity
                    ):
                        self.broker_reported_equity = new_broker_equity
                        # Don't directly overwrite current_equity, let _recalculate handle it based on UPL
                        # self.current_equity = new_broker_equity
                        self.logger.info(f'Broker Reported Net Liquidation (Equity): {self.broker_reported_equity:.2f}')
                        equity_updated = True
                except (ValueError, TypeError) as e:
                    self.error_logger.warning(
                        f'Invalid NetLiquidation format from broker: {account_details["NetLiquidation"]} - {e}'
                    )

            # --- Update Realized PnL (if provided by broker) ---
            # Note: Broker RPL might differ from internal calculation due to timing/costs.
            # Decide whether to trust broker RPL or internal calculation. Let's log broker RPL for comparison.
            if 'RealizedPnL' in account_details and account_details['RealizedPnL'].get('currency') == base_currency:
                try:
                    broker_rpl = float(account_details['RealizedPnL']['value'])
                    self.logger.info(
                        f'Broker Reported Realized PnL: {broker_rpl:.2f} (Internal Total: {self.realized_pnl_total:.2f})'
                    )
                    # Optionally overwrite internal RPL: self.realized_pnl_total = broker_rpl
                except (ValueError, TypeError) as e:
                    self.error_logger.warning(
                        f'Invalid RealizedPnL format from broker: {account_details["RealizedPnL"]} - {e}'
                    )

            # If any key value was updated from broker, trigger recalculation
            if cash_updated or equity_updated or funds_updated:
                self._recalculate_unrealized_pnl_and_equity()

    def reconcile_positions(self, broker_positions):
        """Compares internal positions with broker report (thread-safe)."""
        with self._lock:
            self.logger.info(f'Reconciling positions. Local: {len(self.positions)}, Broker: {len(broker_positions)}')
            local_symbols = set(self.positions.keys())
            broker_symbols = set(broker_positions.keys())
            reconciliation_time_utc = datetime.now(pytz.utc)

            # --- Clean up local zero positions not in broker report ---
            symbols_to_remove = set()
            for symbol, data in self.positions.items():
                # Use isclose for float comparison
                if np.isclose(data['quantity'], 0.0) and symbol not in broker_symbols:
                    self.logger.debug(f'Removing local zero-qty position for {symbol} (not in broker report).')
                    symbols_to_remove.add(symbol)
            for symbol in symbols_to_remove:
                del self.positions[symbol]
                local_symbols.discard(symbol)

            # --- Handle positions closed/missing on broker side ---
            closed_on_broker = local_symbols - broker_symbols
            for symbol in closed_on_broker:
                local_data = self.positions[symbol]
                if not np.isclose(local_data['quantity'], 0.0):
                    self.logger.warning(
                        f'Position {symbol} exists locally ({local_data["quantity"]}) but not reported by broker. Assuming closed, setting qty to 0.'
                    )
                    # PNL should have been realized on fill. Update local state.
                    local_data['quantity'] = 0.0
                    local_data['average_price'] = 0.0
                    local_data['last_update_utc'] = reconciliation_time_utc
                else:
                    # Already zero locally, just ensure it's removed if needed (handled above)
                    pass

            # --- Handle positions new/missing on local side ---
            new_on_broker = broker_symbols - local_symbols
            for symbol in new_on_broker:
                broker_data = broker_positions[symbol]
                broker_qty = broker_data['position']
                broker_avg_cost = broker_data['averageCost']
                if not np.isclose(broker_qty, 0.0):  # Only add if broker reports non-zero
                    self.logger.warning(
                        f'Position {symbol} ({broker_qty} @ {broker_avg_cost}) reported by broker but missing locally. Adding.'
                    )
                    self.positions[symbol] = {
                        'quantity': broker_qty,
                        'average_price': broker_avg_cost,
                        'last_update_utc': reconciliation_time_utc,
                    }

            # --- Reconcile matching symbols ---
            matching_symbols = local_symbols.intersection(broker_symbols)
            for symbol in matching_symbols:
                local_pos = self.positions[symbol]
                broker_data = broker_positions[symbol]
                broker_qty = broker_data['position']
                broker_avg_cost = broker_data['averageCost']
                needs_update = False

                # Check Quantity
                if not np.isclose(local_pos['quantity'], broker_qty):
                    self.logger.warning(
                        f'Position mismatch for {symbol}. Local Qty: {local_pos["quantity"]:.8f}, Broker Qty: {broker_qty:.8f}. Using Broker value.'
                    )
                    local_pos['quantity'] = broker_qty
                    needs_update = True

                # Check Average Price (only if position is non-zero)
                if not np.isclose(broker_qty, 0.0):
                    # Allow small differences, use relative diff threshold
                    price_diff_threshold = 0.0001  # 0.01% relative difference
                    abs_diff = abs(local_pos['average_price'] - broker_avg_cost)
                    relative_diff = abs_diff / abs(broker_avg_cost) if not np.isclose(broker_avg_cost, 0.0) else 0

                    # Update if absolute diff is non-negligible AND relative diff exceeds threshold
                    if abs_diff > 1e-9 and relative_diff > price_diff_threshold:
                        self.logger.info(
                            f'Updating average price for {symbol} based on broker data. Local: {local_pos["average_price"]:.5f}, Broker: {broker_avg_cost:.5f}'
                        )
                        local_pos['average_price'] = broker_avg_cost
                        needs_update = True
                # Ensure zero quantity has zero average price
                elif np.isclose(local_pos['quantity'], 0.0) and not np.isclose(local_pos['average_price'], 0.0):
                    local_pos['average_price'] = 0.0
                    needs_update = True

                if needs_update:
                    local_pos['last_update_utc'] = reconciliation_time_utc

            # Final cleanup: Remove any positions that ended up with zero quantity
            final_symbols_to_remove = {s for s, d in self.positions.items() if np.isclose(d['quantity'], 0.0)}
            if final_symbols_to_remove:
                self.logger.debug(f'Removing reconciled zero-qty positions: {final_symbols_to_remove}')
                for symbol in final_symbols_to_remove:
                    if symbol in self.positions:
                        del self.positions[symbol]

            self.logger.info('Position reconciliation complete.')
            # Trigger recalculation after position changes
            self._recalculate_unrealized_pnl_and_equity()

    def update_latest_price(self, symbol, price, timestamp_utc=None):
        """Updates cached latest price (thread-safe). Recalculates UPL."""
        with self._lock:
            if isinstance(price, (int, float)) and price > 0:
                # Ensure timestamp is aware UTC
                update_time = timestamp_utc or datetime.now(pytz.utc)
                if update_time.tzinfo is None:
                    update_time = pytz.utc.localize(update_time)
                elif update_time.tzinfo != pytz.utc:
                    update_time = update_time.astimezone(pytz.utc)

                # Update only if price or time significantly changes
                current_data = self._latest_prices.get(symbol)
                if (
                    current_data is None
                    or not np.isclose(current_data['price'], price)
                    or update_time > current_data['time_utc']
                ):
                    self._latest_prices[symbol] = {'price': price, 'time_utc': update_time}
                    # Trigger UPL and Equity recalculation immediately after price update
                    self._recalculate_unrealized_pnl_and_equity()
            else:
                self.logger.debug(f'Ignored invalid latest price update for {symbol}: {price}')

    def get_latest_price(self, symbol):
        """Safely gets the latest cached price for a symbol."""
        with self._lock:
            price_data = self._latest_prices.get(symbol)
            return price_data['price'] if price_data else None

    def get_latest_prices_copy(self):
        """Safely returns a shallow copy of the latest prices cache."""
        with self._lock:
            return self._latest_prices.copy()

    def update_position_from_fill(self, symbol, action, quantity, price, timestamp_utc, order_id, strategy, exec_id):
        """Updates position from execution, calculates RPL (thread-safe)."""
        # This method is called by OrderManager (likely from API thread)
        with self._lock:
            # Check/Reset daily stats based on fill timestamp
            fill_date_local = timestamp_utc.astimezone(self.default_tz).date()
            if fill_date_local > self._last_daily_reset_date:
                self._check_reset_daily_stats()  # Perform reset if needed

            if symbol not in self.positions:
                self.positions[symbol] = {'quantity': 0.0, 'average_price': 0.0, 'last_update_utc': None}

            pos = self.positions[symbol]
            current_qty = pos['quantity']
            current_avg_price = pos['average_price']
            trade_pnl = 0.0
            realized_qty = 0.0  # Qty involved in PnL calculation (positive)

            self.logger.debug(
                f'Before fill ({action} {quantity} {symbol} @ {price}): Qty={current_qty:.8f}, AvgPx={current_avg_price:.5f}'
            )

            # Determine quantity that closes/reduces existing position vs opens/increases new
            if action == 'BUY':
                if current_qty >= 0:  # Increasing long or opening long from flat
                    new_total_cost = (current_avg_price * current_qty) + (price * quantity)
                    pos['quantity'] += quantity
                    pos['average_price'] = (
                        new_total_cost / pos['quantity'] if not np.isclose(pos['quantity'], 0.0) else 0.0
                    )
                else:  # Reducing/Closing short position
                    realized_qty = min(quantity, abs(current_qty))
                    trade_pnl = (current_avg_price - price) * realized_qty  # PNL for short cover
                    pos['quantity'] += realized_qty  # Moves towards zero or flips long

                    if quantity > realized_qty:  # Flipped to long
                        remaining_buy_qty = quantity - realized_qty
                        pos['quantity'] = remaining_buy_qty
                        pos['average_price'] = price  # Avg price of the new long leg is the fill price
                    elif np.isclose(pos['quantity'], 0.0):  # Position closed exactly
                        pos['average_price'] = 0.0
                        pos['quantity'] = 0.0  # Ensure clean zero
                    # else: Reduced short, avg price remains unchanged

            elif action == 'SELL':
                if current_qty <= 0:  # Increasing short or opening short from flat
                    new_total_credit = (current_avg_price * abs(current_qty)) + (price * quantity)
                    pos['quantity'] -= quantity
                    pos['average_price'] = (
                        new_total_credit / abs(pos['quantity']) if not np.isclose(pos['quantity'], 0.0) else 0.0
                    )
                else:  # Reducing/Closing long position
                    realized_qty = min(quantity, current_qty)
                    trade_pnl = (price - current_avg_price) * realized_qty  # PNL for long sale
                    pos['quantity'] -= realized_qty  # Moves towards zero or flips short

                    if quantity > realized_qty:  # Flipped to short
                        remaining_sell_qty = quantity - realized_qty
                        pos['quantity'] = -remaining_sell_qty
                        pos['average_price'] = price  # Avg price (credit) of new short leg is fill price
                    elif np.isclose(pos['quantity'], 0.0):  # Position closed exactly
                        pos['average_price'] = 0.0
                        pos['quantity'] = 0.0  # Ensure clean zero
                    # else: Reduced long, avg price remains unchanged

            pos['last_update_utc'] = timestamp_utc  # Store aware UTC timestamp

            # --- Update P&L ---
            if trade_pnl != 0:
                self.realized_pnl_total += trade_pnl
                self.daily_realized_pnl += trade_pnl  # Add to daily tracker
                self.logger.info(
                    f'Realized PnL from trade: {trade_pnl:.2f}, Cumulative Total RPL: {self.realized_pnl_total:.2f}, Daily RPL: {self.daily_realized_pnl:.2f}'
                )
                self.trade_logger.info(
                    f'Trade Closed/Reduced: {symbol}, Qty: {realized_qty:.8f}, Action: {action}, Fill Price: {price:.5f}, Avg Entry: {current_avg_price:.5f}, PnL: {trade_pnl:.2f}'
                )

            # --- Store Trade History ---
            trade = {
                'symbol': symbol,
                'order_id': order_id,
                'exec_id': exec_id,
                'action': action,
                'quantity': quantity,
                'fill_price': price,
                'avg_entry_price': current_avg_price if realized_qty > 0 else None,
                'time_utc': timestamp_utc,
                'pnl': trade_pnl,
                'commission': 0.0,  # Updated later by add_commission
                'strategy': strategy,
                'position_after_trade': pos['quantity'],
                'avg_price_after_trade': pos['average_price'],
            }
            self.trade_history.append(trade)
            # Add to exec_id map for commission matching (if desired)
            self._exec_id_map[exec_id] = trade  # Store reference (overwrites if duplicate exec_id?)

            self.logger.debug(f'After fill: Qty={pos["quantity"]:.8f}, AvgPx={pos["average_price"]:.5f}')

            # Recalculate portfolio values (UPL, Equity, Drawdown) after position change
            self._recalculate_unrealized_pnl_and_equity()

    def add_commission(self, exec_id, commission, currency, timestamp):
        """Adds commission cost and updates associated trade history (thread-safe)."""
        with self._lock:
            # Check/Reset daily stats based on commission timestamp
            comm_date_local = timestamp.astimezone(self.default_tz).date()
            if comm_date_local > self._last_daily_reset_date:
                self._check_reset_daily_stats()  # Perform reset if needed

            # Convert commission to base currency if necessary (TODO: Implement conversion)
            base_currency = 'USD'
            if currency == base_currency:
                comm_amount = abs(commission)  # Commissions are costs
                self.commissions_total += comm_amount
                self.daily_commissions += comm_amount
                self.logger.info(
                    f'Commission Recorded: {comm_amount:.2f} {currency} (ExecID: {exec_id}). Total Comm: {self.commissions_total:.2f}, Daily: {self.daily_commissions:.2f}'
                )

                # Update realized P&L to include commission cost
                self.realized_pnl_total -= comm_amount
                self.daily_realized_pnl -= comm_amount

                # --- Attempt to find matching trade in history and update its commission ---
                if exec_id in self._exec_id_map:
                    trade_entry = self._exec_id_map[exec_id]
                    # Check if commission already added (unlikely but possible)
                    if np.isclose(trade_entry.get('commission', 0.0), 0.0):
                        trade_entry['commission'] = comm_amount
                        # Also update PNL in the trade record itself
                        trade_entry['pnl'] -= comm_amount
                        self.logger.debug(f'Associated commission {comm_amount:.2f} with trade (ExecID: {exec_id})')
                        # Clean up map entry? Optional, might keep for debugging.
                        # del self._exec_id_map[exec_id]
                    else:
                        self.logger.warning(
                            f'Commission for ExecID {exec_id} possibly already recorded in trade history ({trade_entry.get("commission")}). Ignoring duplicate report.'
                        )
                else:
                    # Fallback: If no exact match, maybe find most recent trade for the order ID? Less reliable.
                    self.logger.warning(f'Could not find exact trade match for ExecID {exec_id} to record commission.')

            else:
                self.logger.warning(
                    f'Received commission in non-base currency ({commission} {currency}). Conversion not implemented. PnL impact ignored.'
                )

            # Recalculate equity after commission adjustment (affects Realized PnL)
            self._recalculate_unrealized_pnl_and_equity()

    def _recalculate_unrealized_pnl_and_equity(self):
        """Internal method: Calculates UPL, Equity, Peak, Drawdown (MUST be called within lock)."""
        total_unrealized = 0.0
        now_utc = datetime.now(pytz.utc)
        stale_price_threshold = timedelta(seconds=self.settings.MAX_DATA_STALENESS_SECONDS)

        # Calculate UPL based on current positions and latest prices
        for symbol, pos in self.positions.items():
            qty = pos['quantity']
            avg_price = pos['average_price']
            if np.isclose(qty, 0.0):
                continue  # Skip zero positions

            latest_price_data = self._latest_prices.get(symbol)

            if latest_price_data:
                latest_price = latest_price_data['price']
                price_time_utc = latest_price_data['time_utc']

                # Check if price is stale
                if (now_utc - price_time_utc) > stale_price_threshold:
                    self.logger.warning(
                        f'UPL Calc for {symbol}: Using potentially stale price (updated at {price_time_utc.strftime(self.settings.LOG_TIMESTAMP_FORMAT)}).'
                    )

                # Calculate UPL based on direction
                if qty > 0:  # Long
                    upl = (latest_price - avg_price) * qty
                else:  # Short
                    upl = (avg_price - latest_price) * abs(qty)
                total_unrealized += upl
            elif not np.isclose(qty, 0.0):  # If holding position but price missing
                self.logger.warning(f'Cannot calculate UPL for {symbol}: Latest price missing.')
                # Should UPL be zero or use last known UPL? Setting to zero is safer.

        self.unrealized_pnl_total = total_unrealized

        # --- Calculate Equity ---
        # Prioritize broker-reported equity if available
        if self.broker_reported_equity is not None:
            self.current_equity = self.broker_reported_equity
        else:
            # Fallback to internal calculation: Initial Cap + Realized PnL (Net Comm) + Unrealized PnL
            self.current_equity = self.initial_capital + self.realized_pnl_total + self.unrealized_pnl_total

        # --- Update Peak Equity and Drawdown ---
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
            self.current_drawdown_pct = 0.0
            self.logger.debug(f'New peak equity reached: {self.peak_equity:.2f}')
        else:
            # Calculate drawdown percentage from peak
            if self.peak_equity > 0 and not np.isclose(self.peak_equity, 0.0):
                self.current_drawdown_pct = max(0.0, (self.peak_equity - self.current_equity) / self.peak_equity)
            else:  # Avoid division by zero or issues if peak is zero/negative
                self.current_drawdown_pct = 0.0

        # Log updates (consider throttling this log)
        self.logger.debug(
            f'Portfolio Recalc - Equity: {self.current_equity:.2f}, PeakEq: {self.peak_equity:.2f}, '
            f'DD: {self.current_drawdown_pct:.2%}, Cash: {self.current_cash:.2f}, AvailFunds: {self.available_funds:.2f}, '
            f'RPL: {self.realized_pnl_total:.2f}, UPL: {self.unrealized_pnl_total:.2f}, Comm: {self.commissions_total:.2f}'
        )

    # --- Public Accessor Methods (Thread-Safe) ---

    def get_position_size(self, symbol):
        """Returns the quantity of the position for a symbol (thread-safe)."""
        with self._lock:
            pos = self.positions.get(symbol)
            return pos['quantity'] if pos else 0.0

    def get_average_price(self, symbol):
        """Returns the average entry price for a symbol's position (thread-safe)."""
        with self._lock:
            pos = self.positions.get(symbol)
            return pos['average_price'] if pos else 0.0

    def get_current_cash(self):
        """Returns the last known cash value (thread-safe). Prioritizes broker report."""
        with self._lock:
            # Return broker value if available, else internal tracking
            return self.broker_reported_cash if self.broker_reported_cash is not None else self.current_cash

    def get_available_funds(self):
        """Returns the last known available funds value (thread-safe). Prioritizes broker report."""
        with self._lock:
            # Return broker value if available, else internal tracking (which should match broker if reconciled)
            return self.broker_reported_funds if self.broker_reported_funds is not None else self.available_funds

    def get_total_equity(self):
        """Returns the last known total portfolio equity (thread-safe). Prioritizes broker report."""
        with self._lock:
            # Return broker value if available, else internal calculation
            return self.broker_reported_equity if self.broker_reported_equity is not None else self.current_equity

    def get_daily_pnl(self):
        """Returns the realized PnL for the current day (net of commissions, thread-safe)."""
        with self._lock:
            # Ensure daily stats are potentially reset before returning
            self._check_reset_daily_stats()
            return self.daily_realized_pnl

    def get_peak_equity(self):
        """Returns the highest recorded portfolio equity (thread-safe)."""
        with self._lock:
            return self.peak_equity

    def get_current_drawdown(self):
        """Returns the current drawdown percentage from the peak equity (thread-safe)."""
        with self._lock:
            # Ensure value is reasonably current before returning
            # No need to recalculate here, _recalculate updates it on changes
            return self.current_drawdown_pct

    def get_trade_history(self, limit=None):
        """Returns a copy of the recorded trades list (thread-safe), optionally limited."""
        with self._lock:
            # Return a list copy of the deque items
            history_list = list(self.trade_history)
            if limit and isinstance(limit, int) and limit > 0:
                return history_list[-limit:]  # Return copy of last N trades
            return history_list  # Return a copy of all trades in the deque
