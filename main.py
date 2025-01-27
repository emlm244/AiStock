import sys
import os
import time
import pandas as pd
import numpy as np
import threading
import hashlib
import json
from datetime import datetime, timedelta
from ibapi.order import Order
from ibapi.ticktype import TickTypeEnum

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from api.ibkr_api import IBKRApi
from aggregator.data_aggregator import DataAggregator

from strategies.trend_following import TrendFollowingStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.ml_strategy import MLStrategy
from utils.parameter_optimizer import AdaptiveParameterOptimizer
from config.settings import Settings
from utils.logger import setup_logger
from utils.data_utils import calculate_position_size
from train_model import main as train_model_main

from contract_utils import create_contract


def get_settings_hash(settings):
    """
    Create a hash from critical parameters in Settings, allowing you
    to detect if certain user-facing parameters have changed.
    """
    critical_params = {
        'TIMEFRAME': settings.TIMEFRAME,
        'DATA_SOURCE': settings.DATA_SOURCE,
        'MAX_POSITION_SIZE': settings.MAX_POSITION_SIZE,
        'RISK_PER_TRADE': settings.RISK_PER_TRADE,
        'TOTAL_CAPITAL': settings.TOTAL_CAPITAL,
    }
    params_str = json.dumps(critical_params, sort_keys=True)
    return hashlib.md5(params_str.encode('utf-8')).hexdigest()


def parse_timeframe_to_seconds(timeframe_str: str) -> int:
    """
    Convert a user-friendly timeframe string (e.g. '1 min', '5 min', '1 hour') to seconds.
    """
    value, unit = timeframe_str.split()
    value = int(value)
    if unit == 'min':
        return value * 60
    elif unit == 'hour':
        return value * 3600
    elif unit == 'day':
        return value * 86400
    else:
        return 60  # Default to 60 seconds if unrecognized


class TradingBot:
    def __init__(self):
        self.settings = Settings()
        self.logger = setup_logger('app_logger', 'logs/app.log', level=self.settings.LOG_LEVEL)
        self.trade_logger = setup_logger('trade_logger', 'logs/trade_logs/trades.log', level=self.settings.LOG_LEVEL)
        self.error_logger = setup_logger('error_logger', 'logs/error_logs/errors.log', level='ERROR')

        # Initialization Confirmation Logs
        self.logger.info("Initializing IBKR API...")
        self.api = IBKRApi(self)
        self.logger.info("IBKR API initialized successfully.")

        self.logger.info("Initializing Data Aggregator...")
        self.bar_size = timedelta(minutes=int(self.settings.TIMEFRAME.split()[0]))
        self.data_aggregator = DataAggregator(
            api=self.api,
            bar_size=self.bar_size,
            logger=self.logger,
            max_errors=5,
            error_callback=self.on_aggregator_error
        )
        self.logger.info("Data Aggregator initialized successfully.")

        self.logger.info("Loading trading strategies...")
        self.strategies = self.load_strategies()
        self.logger.info(f"Loaded strategies: {[s.__class__.__name__ for s in self.strategies]}")

        # Data structures
        self.market_data = {}    
        self.market_data_req_ids = {}  
        self.positions = {}
        self.running = True
        self.daily_pnl = 0.0
        self.trade_history = []
        self.lock = threading.Lock()

        # Trade metrics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.total_loss = 0.0

        # Request ID counter for dynamic subscriptions
        self.req_id_counter = 1

        # Ensure we have enough data for strategies
        self.min_data_points = max(s.min_data_points() for s in self.strategies)

        # Initialize Adaptive Parameter Optimizer
        self.parameter_optimizer = AdaptiveParameterOptimizer(self.settings, self.logger)

        # For hashing certain settings
        self.settings_hash = get_settings_hash(self.settings)

        # Mapping from order ID to strategy
        self.order_strategy_mapping = {}

        # Prompt user for trading mode
        self.prompt_trading_mode()

        # Prompt user for continuing after market closure
        self.prompt_continue_after_close()

        # Configure subscriptions automatically based on the selected trading mode
        self.configure_subscriptions()

    def prompt_trading_mode(self):
        """Prompt user to select trading mode: Stock or Crypto."""
        while True:
            choice = input("Select Trading Mode: 1. Stock  2. Crypto (Enter 1 or 2): ").strip()
            if choice == '1':
                self.settings.TRADING_MODE = 'stock'
                self.settings.TRADE_INSTRUMENTS = ['AAPL']  # Default example stock
                break
            elif choice == '2':
                self.settings.TRADING_MODE = 'crypto'
                self.settings.TRADE_INSTRUMENTS = ['ETH/USD', 'BTC/USD']  # Default cryptos
                break
            else:
                print("Invalid input. Please enter '1' for Stock or '2' for Crypto.")

    def prompt_continue_after_close(self):
        """Prompt user whether to continue trading after market closes."""
        while True:
            choice = input("Do you want the bot to continue trading after the market closes? (Yes/No): ").strip().lower()
            if choice in ["yes", "y"]:
                self.settings.CONTINUE_AFTER_CLOSE = True
                break
            elif choice in ["no", "n"]:
                self.settings.CONTINUE_AFTER_CLOSE = False
                break
            else:
                print("Please enter 'Yes' or 'No'.")

        self.logger.info(f"CONTINUE_AFTER_CLOSE set to: {self.settings.CONTINUE_AFTER_CLOSE}")

    def configure_subscriptions(self):
        """Configure data subscription settings based on the selected trading mode."""
        mode = self.settings.TRADING_MODE
        subscription_config = self.settings.SUBSCRIPTIONS.get(mode, {})

        if subscription_config.get('enabled'):
            if mode == 'stock':
                self.api.use_snapshot_quotes = subscription_config.get('snapshot_enabled', False)
                self.api.real_time_sources = subscription_config.get('data_sources', [])
            elif mode == 'crypto':
                self.api.use_snapshot_quotes = False
                self.api.real_time_sources = subscription_config.get('data_sources', [])

        self.logger.info(f"Configured subscriptions for {mode} trading.")

    def on_aggregator_error(self):
        self.logger.error("DataAggregator encountered critical errors. Stopping TradingBot.")
        self.stop()

    def load_strategies(self):
        """
        Load and enable only the strategies you have turned on in Settings.
        """
        strategies = []
        enabled = self.settings.ENABLED_STRATEGIES
        if enabled.get('trend_following'):
            strategies.append(TrendFollowingStrategy())
        if enabled.get('mean_reversion'):
            strategies.append(MeanReversionStrategy())
        if enabled.get('momentum'):
            strategies.append(MomentumStrategy())
        if enabled.get('machine_learning'):
            strategies.append(MLStrategy())
        if not strategies:
            self.logger.error("No strategies enabled. Please enable at least one strategy.")
            raise Exception("No strategies enabled.")
        return strategies

    def update_daily_pnl(self, trade_pnl):
        self.daily_pnl += trade_pnl
        self.logger.info(f"Updated daily P&L: {self.daily_pnl}")

    def update_trade_metrics(self, trade_pnl):
        """Track total trades, wins/losses, and log metrics after each execution."""
        self.total_trades += 1
        if trade_pnl > 0:
            self.winning_trades += 1
            self.total_profit += trade_pnl
        else:
            self.losing_trades += 1
            self.total_loss += trade_pnl

        win_rate = (self.winning_trades / self.total_trades) * 100
        avg_return = (self.total_profit + self.total_loss) / self.total_trades if self.total_trades > 0 else 0.0

        self.logger.info(
            f"Trade Metrics - Total Trades: {self.total_trades}, "
            f"Win Rate: {win_rate:.2f}%, Average Return per Trade: {avg_return:.2f}"
        )

    def save_market_data(self, symbol, data_type='historical'):
        """Save the market_data DataFrame for a symbol to CSV files."""
        directory = 'data/historical_data' if data_type == 'historical' else 'data/live_data'
        os.makedirs(directory, exist_ok=True)
        file_path = os.path.join(directory, f"{symbol.replace('/', '_')}.csv")
        self.market_data[symbol].to_csv(file_path, index=False)
        self.logger.info(f"Saved {data_type} data for {symbol} to {file_path}")

    def ai_performance_good_enough(self):
        """Check if MLStrategy's recent trades are good enough to go AI-only."""
        ai_trades = [t for t in self.trade_history if t.get('strategy') == 'MLStrategy']
        N = 10
        threshold_win_rate = 0.6
        if len(ai_trades) >= N:
            recent_trades = ai_trades[-N:]
            wins = sum(1 for t in recent_trades if t['pnl'] > 0)
            win_rate = wins / N
            self.logger.info(f"AI Strategy win rate (last {N} trades): {win_rate*100:.2f}%")
            return win_rate >= threshold_win_rate
        else:
            self.logger.info(
                f"Insufficient AI trades to evaluate performance. "
                f"Needed: {N}, Available: {len(ai_trades)}"
            )
            return False

    def start(self, enable_simulator=False):
        """Connect to IBKR, request historical data, start aggregator, and run main loop."""
        self.api.connect_app()
        self.logger.info("Starting trading bot.")

        # Request 1 day of historical data for each instrument
        for instrument in self.settings.TRADE_INSTRUMENTS:
            self.request_historical_data(instrument)

        # Start aggregator, which calls subscribe_market_data for each instrument
        self.data_aggregator.subscribe_symbols(self.settings.TRADE_INSTRUMENTS)

        # If simulator mode is enabled, feed mock ticks
        if enable_simulator:
            self.logger.info("Simulator mode enabled. Feeding mock data into the aggregator.")
            mock_data = self.load_mock_ticks_from_csv("data/mock_data.csv")  # Example CSV
            self.data_aggregator.feed_mock_ticks(mock_data)

        # Launch main loop in a background thread
        threading.Thread(target=self.main_loop, daemon=True).start()

    def update_snapshot_quota(self, remaining_snapshots):
        """(Optional) Update the snapshot quota dynamically."""
        self.logger.info(f"Snapshot quota updated: {remaining_snapshots}")

    def stop(self):
        """Safely stop the bot and disconnect from IBKR."""
        self.running = False
        self.data_aggregator.stop()
        self.api.disconnect_app()
        self.logger.info("Trading bot stopped.")

    def load_mock_ticks_from_csv(self, file_path):
        """Example function to read CSV mock tick data and return a list of ticks."""
        if not os.path.isfile(file_path):
            self.logger.error(f"Mock data file not found: {file_path}")
            return []
        df = pd.read_csv(file_path)
        tick_list = []
        for _, row in df.iterrows():
            symbol = row['symbol']
            tickType = row['tickType']
            price = row['price']
            size = row['size']
            ts = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
            tick_list.append((symbol, tickType, price, size, ts))
        return tick_list

    def request_historical_data(self, symbol):
        """Request 1 day of historical data from IBKR for a symbol."""
        with self.lock:
            contract = create_contract(symbol)
            req_id = self.req_id_counter
            self.req_id_counter += 1

        self.api.reqHistoricalData(
            reqId=req_id,
            contract=contract,
            endDateTime='',
            durationStr='1 D',
            barSizeSetting=self.settings.TIMEFRAME,
            whatToShow='MIDPOINT' if contract.secType == "CASH" else 'TRADES',
            useRTH=1,
            formatDate=1,
            keepUpToDate=False,
            chartOptions=[]
        )
        self.logger.info(f"Requested historical data for {symbol}")
        self.market_data_req_ids[req_id] = symbol

    def is_market_closed(self, instrument):
        """
        For 'stock': simple 9:30-16:00 check.
        For 'crypto': open 24/7 => never "closed."
        """
        if self.settings.TRADING_MODE == 'stock':
            current_time = datetime.now().time()
            market_open_time = datetime.strptime("09:30", "%H:%M").time()
            market_close_time = datetime.strptime("16:00", "%H:%M").time()
            return not (market_open_time <= current_time <= market_close_time)
        elif self.settings.TRADING_MODE == 'crypto':
            return False
        return False

    def check_market_closed_all(self):
        """
        If stock, consider closed if outside 9:30-16:00.
        If crypto, never closed.
        """
        if self.settings.TRADING_MODE == 'stock':
            return self.is_market_closed(None)
        elif self.settings.TRADING_MODE == 'crypto':
            return False
        return False

    def main_loop(self):
        """
        Primary loop, run in a background thread:
          1) Collect bars
          2) Evaluate strategies
          3) Check market closure logic
          4) Execute trades
          5) Periodically save data
        """
        SPINNER_CHARS = ['|', '/', '-', '\\']
        spinner_index = 0

        # Simple cooldown to avoid spam trades
        trade_skip_cooldown = 60
        last_trade_attempt_time = 0

        while self.running:
            try:
                current_time = time.time()

                if current_time - last_trade_attempt_time < trade_skip_cooldown:
                    time.sleep(1)
                    continue

                # 1) Collect completed bars
                all_strategies_used = []
                for symbol in self.settings.TRADE_INSTRUMENTS:
                    bar_queue = self.data_aggregator.get_bar_queue(symbol)
                    while bar_queue is not None and not bar_queue.empty():
                        new_bar_df = bar_queue.get()
                        self.logger.debug(f"New bar received for {symbol}: {new_bar_df}")

                        with self.lock:
                            if symbol not in self.market_data:
                                self.market_data[symbol] = pd.DataFrame(
                                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                                )
                            self.market_data[symbol] = pd.concat(
                                [self.market_data[symbol], new_bar_df],
                                ignore_index=True
                            )

                # 2) AI-only check
                ai_only = self.ai_performance_good_enough()

                # 3) Evaluate strategies & possibly place bracket orders
                for instrument in self.settings.TRADE_INSTRUMENTS:
                    if self.is_market_closed(instrument):
                        if not self.settings.CONTINUE_AFTER_CLOSE:
                            self.logger.info(f"Market for {instrument} is closed. Halting trading.")
                            self.stop()
                            break
                        else:
                            self.logger.info(f"Market for {instrument} is closed. Continuing as per user preference.")

                    data = self.get_market_data(instrument)
                    if data is not None and len(data) >= self.min_data_points:
                        signals = []
                        strategies_used_this_symbol = []

                        with self.lock:
                            current_position = self.positions.get(instrument, {'quantity': 0})['quantity']
                            available_cash = self.get_available_cash()

                        if ai_only:
                            ml_strategy = next((s for s in self.strategies if isinstance(s, MLStrategy)), None)
                            if ml_strategy and available_cash >= self.settings.TOTAL_CAPITAL * self.settings.RISK_PER_TRADE:
                                signal = ml_strategy.generate_signal(data)
                                signals.append(signal)
                                strategies_used_this_symbol.append('MLStrategy')
                            else:
                                self.logger.info("AI-only mode not active or insufficient funds.")
                        else:
                            # Evaluate all enabled strategies
                            for strategy in self.strategies:
                                sig = 0
                                if (available_cash < (self.settings.TOTAL_CAPITAL * self.settings.RISK_PER_TRADE)
                                        and current_position <= 0):
                                    # Not enough funds to open new trades; still allow SELL if we have a position
                                    if current_position > 0:
                                        sig = strategy.generate_signal(data)
                                else:
                                    sig = strategy.generate_signal(data)

                                strategies_used_this_symbol.append(strategy.__class__.__name__)
                                signals.append(sig)

                        final_signal = self.aggregate_signals(signals)
                        self.logger.debug(f"Signal for {instrument}: {final_signal} by {strategies_used_this_symbol}")

                        if hasattr(self, 'previous_signal'):
                            previous_signal = self.previous_signal
                        else:
                            previous_signal = None

                        if final_signal != 0 and final_signal != previous_signal:
                            self.execute_bracket(instrument, final_signal, strategies_used_this_symbol)
                            last_trade_attempt_time = current_time
                            self.previous_signal = final_signal
                        else:
                            if final_signal == 0:
                                self.logger.info(f"No actionable signal for {instrument}.")
                            else:
                                self.logger.info(f"Signal {final_signal} is same as previous. Skipping.")

                        all_strategies_used.extend(strategies_used_this_symbol)
                    else:
                        length_of_data = len(data) if data is not None else 0
                        self.logger.warning(
                            f"Insufficient data for {instrument}. "
                            f"Required: {self.min_data_points}, Got: {length_of_data}"
                        )

                if self.check_market_closed_all():
                    if not self.settings.CONTINUE_AFTER_CLOSE:
                        self.logger.info("All markets are closed. Halting trading bot.")
                        self.stop()

                # 4) Update parameters dynamically
                self.parameter_optimizer.update_parameters(self.trade_history)

                # 5) Save live data periodically (example: every 10 minutes)
                if datetime.now().minute % 10 == 0:
                    for symbol in self.settings.TRADE_INSTRUMENTS:
                        with self.lock:
                            if symbol in self.market_data and not self.market_data[symbol].empty:
                                self.save_market_data(symbol, data_type='live')

                current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                strategies_logged = ', '.join(set(all_strategies_used)) if all_strategies_used else 'None'
                self.logger.info(f"{current_time_str} - Strategies evaluated: {strategies_logged}")

                print(f"\rAIStocker is waiting... {SPINNER_CHARS[spinner_index]}", end="", flush=True)
                spinner_index = (spinner_index + 1) % len(SPINNER_CHARS)

                time.sleep(1)

            except Exception as e:
                self.error_logger.error(f"Exception in main loop: {e}", exc_info=True)
                self.running = False

    def aggregate_signals(self, signals):
        """Combine multiple strategy signals into a single final signal."""
        sig_sum = sum(signals)
        if sig_sum > 0:
            return 1
        elif sig_sum < 0:
            return -1
        else:
            return 0

    def get_market_data(self, symbol):
        """Return a copy of the DataFrame for the requested symbol, or None if missing."""
        with self.lock:
            df = self.market_data.get(symbol)
            if df is not None and not df.empty:
                return df.copy()
            else:
                return None

    def get_latest_price(self, symbol):
        """Return the latest 'close' price from market_data for this symbol."""
        with self.lock:
            df = self.market_data.get(symbol)
            if df is not None and not df.empty:
                return df.iloc[-1]['close']
            else:
                self.logger.warning(f"No market data available for {symbol}")
                return None

    def get_available_cash(self):
        """Calculate available cash based on TOTAL_CAPITAL and current positions."""
        used_cash = 0.0
        with self.lock:
            for sym, pos in self.positions.items():
                if pos['quantity'] > 0:
                    latest_price = self.get_latest_price(sym)
                    if latest_price:
                        used_cash += latest_price * pos['quantity']
        available_cash = self.settings.TOTAL_CAPITAL - used_cash
        self.logger.debug(f"Available Cash: {available_cash} USD")
        return available_cash

    def execute_bracket(self, symbol, signal, strategies_used):
        """Places a bracket order (parent + stop loss + take profit)."""
        if self.daily_pnl <= -self.settings.TOTAL_CAPITAL * self.settings.MAX_DAILY_LOSS:
            self.logger.warning("Max daily loss limit reached. Not placing trades.")
            return

        contract = create_contract(symbol)
        latest_price = self.get_latest_price(symbol)
        if latest_price is None:
            self.error_logger.error(f"Cannot retrieve latest price for {symbol}")
            return

        if signal == 1:
            action = 'BUY'
        elif signal == -1:
            action = 'SELL'
        else:
            return

        self.logger.info(f"*** Attempting new trade: {action} {symbol} ***")

        if action == 'SELL':
            with self.lock:
                current_position = self.positions.get(symbol, {'quantity': 0})['quantity']
            if current_position <= 0:
                self.logger.warning(f"No existing position for {symbol}. Cannot place SELL order.")
                return

        if action == 'BUY':
            stop_loss_price = latest_price * (1 - self.settings.STOP_LOSS_PERCENT)
            take_profit_price = latest_price * (1 + self.settings.TAKE_PROFIT_PERCENT)
        else:
            stop_loss_price = latest_price * (1 + self.settings.STOP_LOSS_PERCENT)
            take_profit_price = latest_price * (1 - self.settings.TAKE_PROFIT_PERCENT)

        # Rounding logic
        if '/' in symbol:  # Possibly crypto or Forex
            if 'JPY' in symbol.upper():
                stop_loss_price = round(stop_loss_price, 2)
                take_profit_price = round(take_profit_price, 2)
            else:
                stop_loss_price = round(stop_loss_price, 5)
                take_profit_price = round(take_profit_price, 5)
        else:
            stop_loss_price = round(stop_loss_price, 2)
            take_profit_price = round(take_profit_price, 2)

        available_cash = self.get_available_cash()
        position_size = calculate_position_size(
            entry_price=latest_price,
            stop_loss_price=stop_loss_price,
            risk_per_trade=self.settings.RISK_PER_TRADE,
            available_cash=available_cash,
            symbol=symbol
        )

        self.logger.info(f"Available Cash: {available_cash} USD, Calculated Position Size: {position_size} units")

        max_affordable = available_cash / latest_price if latest_price else 0
        if action == 'BUY' and position_size < 1e-8:
            self.logger.warning(
                f"Insufficient funds to purchase any {symbol}. "
                f"Price: {latest_price}, Available: {available_cash}."
            )
            return

        if action == 'SELL':
            with self.lock:
                current_qty = self.positions[symbol]['quantity']
            if position_size > current_qty:
                position_size = current_qty

        if position_size <= 0:
            self.logger.warning(f"Position size {position_size} invalid. Skipping trade.")
            return

        self.logger.info(
            f"Executing {action} for {symbol}: size={position_size}, "
            f"Stop={stop_loss_price:.5f}, TP={take_profit_price:.5f}"
        )

        from ibapi.order import Order
        parent_order = Order()
        parent_order.action = action
        parent_order.orderType = self.settings.ORDER_TYPE
        parent_order.totalQuantity = position_size
        parent_order.transmit = False

        stop_order = Order()
        stop_order.action = "SELL" if action == "BUY" else "BUY"
        stop_order.orderType = "STP"
        stop_order.auxPrice = stop_loss_price
        stop_order.totalQuantity = position_size
        stop_order.parentId = 0
        stop_order.transmit = False

        take_profit_order = Order()
        take_profit_order.action = "SELL" if action == "BUY" else "BUY"
        take_profit_order.orderType = "LMT"
        take_profit_order.lmtPrice = take_profit_price
        take_profit_order.totalQuantity = position_size
        take_profit_order.parentId = 0
        take_profit_order.transmit = True

        parent_order_id = self.api.get_next_order_id()
        order_id_stop = self.api.get_next_order_id()
        order_id_take_profit = self.api.get_next_order_id()

        stop_order.parentId = parent_order_id
        take_profit_order.parentId = parent_order_id

        self.api.placeOrder(parent_order_id, contract, parent_order)
        self.api.placeOrder(order_id_stop, contract, stop_order)
        self.api.placeOrder(order_id_take_profit, contract, take_profit_order)

        if len(strategies_used) == 1:
            self.order_strategy_mapping[parent_order_id] = strategies_used[0]
        else:
            self.order_strategy_mapping[parent_order_id] = 'MultipleStrategies'

        self.trade_logger.info(
            f"Placed bracket order {action} {symbol}, size={position_size}, "
            f"Stop={stop_loss_price:.5f}, TP={take_profit_price:.5f}."
        )

    def handle_execution(self, execution, contract):
        """Called by IBKRApi when an execution (fill) occurs. Update positions, PnL, etc."""
        if contract.secType in ["CASH", "CRYPTO"]:
            symbol = f"{contract.symbol}/{contract.currency}"
        else:
            symbol = contract.symbol

        order_id = execution.orderId
        action = 'BUY' if execution.side == 'BOT' else 'SELL'
        quantity = execution.shares
        price = execution.price
        exec_time = execution.time
        strategy = self.order_strategy_mapping.get(order_id, 'Unknown')

        if symbol not in self.positions:
            self.positions[symbol] = {'quantity': 0, 'average_price': 0.0}

        pos = self.positions[symbol]
        if action == 'BUY':
            total_cost = pos['average_price'] * pos['quantity'] + price * quantity
            pos['quantity'] += quantity
            if pos['quantity'] != 0:
                pos['average_price'] = total_cost / pos['quantity']
            else:
                pos['average_price'] = 0.0
            pnl = 0
        else:
            pnl = (price - pos['average_price']) * quantity
            self.update_daily_pnl(pnl)
            self.update_trade_metrics(pnl)
            pos['quantity'] -= quantity
            if pos['quantity'] == 0:
                pos['average_price'] = 0.0

        trade = {
            'symbol': symbol,
            'order_id': order_id,
            'action': action,
            'quantity': quantity,
            'price': price,
            'time': exec_time,
            'pnl': pnl,
            'strategy': strategy
        }
        self.trade_history.append(trade)
        self.trade_logger.info(
            f"Trade executed: {action} {quantity} of {symbol} at {price}, P&L: {pnl:.2f}"
        )


if __name__ == "__main__":
    bot = TradingBot()
    try:
        print("Select an option:")
        print("1. Launch the current AI/ML algorithm and start trading.")
        print("2. Train (add on knowledge) the current AI with historical data.")
        choice = input("Enter your choice (1 or 2): ")
        if choice == '1':
            bot.start()
            while True:
                time.sleep(1)
        elif choice == '2':
            duration = input("Enter training duration in seconds: ")
            try:
                duration = int(duration)
            except ValueError:
                print("Invalid duration input.")
                sys.exit(1)

            print("Training the AI with historical data...")
            try:
                train_model_main()
                print("Training completed.")
            except Exception as e:
                print(f"An error occurred during training: {e}")
                sys.exit(1)

            launch = input("Do you want to launch the AI to the market? (yes/no): ")
            if launch.lower() == 'yes':
                bot.start()
                while True:
                    time.sleep(1)
            else:
                print("Exiting the system.")
        else:
            print("Invalid choice. Exiting.")
    except KeyboardInterrupt:
        bot.stop()
