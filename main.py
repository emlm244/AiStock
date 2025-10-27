# main.py

import sys
import os
import time
import pandas as pd
import numpy as np
import threading # <-- Ensure threading is imported
import json
import re
import argparse  # For CLI argument parsing
from datetime import datetime, timedelta, time as dt_time
import queue
import logging
import pytz # Import pytz for timezone handling
from collections import defaultdict
import concurrent.futures # For running training in background
from ibapi.contract import ContractDetails

# --- Critical: Ensure project root is in path EARLY ---
# This helps resolve imports correctly, especially when run from different directories
try:
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
except NameError: # Handle case where __file__ is not defined (e.g., interactive interpreter)
    project_root = os.getcwd()
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

# --- Settings and Logging Setup (Early) ---
# Setup logging before importing other components that might log
# This ensures handlers are configured correctly from the start.
try:
    from config.settings import Settings
    from utils.logger import setup_logger

    # Setup loggers early
    # Use a dedicated main logger for startup/shutdown messages
    main_logger = setup_logger('main_startup', 'logs/app.log', level='INFO')
    main_error_logger = setup_logger('main_error', 'logs/error_logs/errors.log', level='ERROR')
    main_logger.info("--- AIStocker Boot Sequence Initiated ---")

except ImportError as e:
    print(f"CRITICAL: Failed to import core config/logging: {e}. Ensure config/settings.py and utils/logger.py exist. Exiting.")
    sys.exit(1)
except Exception as e:
    print(f"CRITICAL: Unexpected error during initial setup: {e}. Exiting.")
    sys.exit(1)


# --- Core Components Imports ---
try:
    from api.ibkr_api import IBKRApi
    from aggregator.data_aggregator import DataAggregator
    from managers.order_manager import OrderManager
    from managers.portfolio_manager import PortfolioManager
    from managers.risk_manager import RiskManager
    from managers.strategy_manager import StrategyManager
    from persistence.state_manager import StateManager
except ImportError as e:
    main_error_logger.critical(f"Failed to import core components (Managers, API, etc.): {e}", exc_info=True)
    print(f"CRITICAL: Failed to import core components: {e}. Check imports and file paths. Exiting.")
    sys.exit(1)

# --- Strategies & Utilities Imports ---
try:
    from strategies import MLStrategy # Specifically needed for retraining checks
    from utils.market_analyzer import MarketRegimeDetector
    from indicators.volatility import calculate_atr
    # from utils.parameter_optimizer import AdaptiveParameterOptimizer # Keep if needed
    from utils.data_utils import calculate_position_size
    from train_model import main as train_model_main # For triggering training
    from contract_utils import create_contract, get_contract_details, get_min_trade_size, get_min_tick, round_price, round_quantity
except ImportError as e:
    main_error_logger.critical(f"Failed to import strategies or utilities: {e}", exc_info=True)
    print(f"CRITICAL: Failed to import strategies or utilities: {e}. Check imports and file paths. Exiting.")
    sys.exit(1)


# --- Timezone Setup ---
try:
    DEFAULT_TZ_STR = Settings.TIMEZONE
    DEFAULT_TZ = pytz.timezone(DEFAULT_TZ_STR)
    main_logger.info(f"Default Timezone set to: {DEFAULT_TZ_STR}")
except pytz.UnknownTimeZoneError:
    main_error_logger.critical(f"Unknown timezone '{Settings.TIMEZONE}' in settings. Exiting.")
    print(f"CRITICAL: Unknown timezone '{Settings.TIMEZONE}' in settings. Exiting.")
    sys.exit(1)
except AttributeError:
    main_error_logger.critical("TIMEZONE not found in settings. Exiting.")
    print("CRITICAL: TIMEZONE not found in settings. Exiting.")
    sys.exit(1)


class TradingBot:
    def __init__(self):
        self.settings = Settings()
        # Setup instance-specific loggers
        self.logger = setup_logger('TradingBot', 'logs/app.log', level=self.settings.LOG_LEVEL)
        self.trade_logger = setup_logger('TradeExecution', 'logs/trade_logs/trades.log', level=self.settings.LOG_LEVEL)
        self.error_logger = setup_logger('BotErrors', 'logs/error_logs/errors.log', level='ERROR')

        self.logger.info(f"--- Initializing AIStocker Trading Bot (PID: {os.getpid()}) ---")
        self.logger.info(f"Default Settings - Mode: {self.settings.TRADING_MODE}, "
                         f"Autonomous: {self.settings.AUTONOMOUS_MODE}, "
                         f"Capital: {self.settings.TOTAL_CAPITAL}")

        # --- Prompt User for Configuration Overrides ---
        if not self.prompt_user_config():
             self.logger.critical("User configuration failed or cancelled. Exiting.")
             sys.exit(1) # Exit directly if config fails
        self.logger.info(f"Effective Settings - Mode: {self.settings.TRADING_MODE}, "
                         f"Instruments: {self.settings.TRADE_INSTRUMENTS}, "
                         f"Autonomous: {self.settings.AUTONOMOUS_MODE}, "
                         f"Adaptive Risk: {self.settings.ENABLE_ADAPTIVE_RISK}, "
                         f"Auto Retrain: {self.settings.ENABLE_AUTO_RETRAINING}")

        # --- Initialize Core Managers ---
        # Note: Dependencies flow: Settings -> PM -> RM/SM/OM -> API -> Aggregator
        self.logger.info("Initializing Portfolio Manager...")
        self.portfolio_manager = PortfolioManager(self.settings, self.logger)
        self.logger.info("Initializing Risk Manager...")
        self.risk_manager = RiskManager(self.portfolio_manager, self.settings, self.logger)
        self.logger.info("Initializing Regime Detector...")
        self.regime_detector = MarketRegimeDetector(self.settings, self.logger)
        self.logger.info("Initializing Strategy Manager...")
        self.strategy_manager = StrategyManager(self.settings, self.portfolio_manager, self.regime_detector, self.logger)
        # self.logger.info("Initializing Parameter Optimizer...") # Keep if using heuristics
        # self.parameter_optimizer = AdaptiveParameterOptimizer(self.settings, self.portfolio_manager.get_trade_history, self.regime_detector, self.logger)


        # --- Initialize API Connection ---
        self.logger.info("Initializing IBKR API...")
        # Pass self (TradingBot) for callbacks like historical data, contract details
        self.api = IBKRApi(self, self.settings) # Pass settings directly
        self.logger.info("IBKR API initialized.")

        # --- Initialize Order Manager (API object needed) ---
        self.logger.info("Initializing Order Manager...")
        self.order_manager = OrderManager(self.api, self.portfolio_manager, self.settings, self.logger)
        # Assign managers to API AFTER they are initialized
        self.api.order_manager = self.order_manager
        self.api.portfolio_manager = self.portfolio_manager


        # --- Initialize State Manager (Needs OM and PM) ---
        self.logger.info("Initializing State Manager...")
        # TODO: Pass StrategyManager/Optimizer to StateManager if their state needs saving/loading
        self.state_manager = StateManager(self.order_manager, self.portfolio_manager, self.settings, logger=self.logger)

        # --- Initialize Data Aggregator (Needs API) ---
        self.logger.info("Initializing Data Aggregator...")
        try:
            # Robust timeframe parsing
            parts = str(self.settings.TIMEFRAME).lower().split() # Ensure string conversion
            if len(parts) == 1 and parts[0].isdigit(): # Assume minutes if only number given
                 value = int(parts[0]); unit = "min"
            elif len(parts) == 2 and parts[0].isdigit():
                value = int(parts[0]); unit = parts[1]
            else: raise ValueError(f"Invalid TIMEFRAME format: '{self.settings.TIMEFRAME}'")

            if unit.startswith("sec"):    bar_size_td = timedelta(seconds=value)
            elif unit.startswith("min"):  bar_size_td = timedelta(minutes=value)
            elif unit.startswith("hour"): bar_size_td = timedelta(hours=value)
            elif unit.startswith("day"):  bar_size_td = timedelta(days=value)
            else: raise ValueError(f"Unsupported TIMEFRAME unit: '{unit}'")

            # Pass self.on_aggregator_error callback
            self.data_aggregator = DataAggregator(self.api, bar_size_td, self.logger, self.on_aggregator_error)
            self.logger.info(f"Data Aggregator initialized with bar size: {bar_size_td}.")
        except ValueError as e:
            self.error_logger.critical(f"Invalid TIMEFRAME setting: {e}. Exiting.")
            print(f"CRITICAL: Invalid TIMEFRAME setting: {e}. Exiting.")
            sys.exit(1)
        except Exception as e:
            self.error_logger.critical(f"Failed to initialize Data Aggregator: {e}", exc_info=True)
            print(f"CRITICAL: Failed to initialize Data Aggregator: {e}. Exiting.")
            sys.exit(1)


        # --- Get Global Data Requirements ---
        # Primarily driven by StrategyManager now
        self.min_data_points_global = self.strategy_manager.get_min_data_points()
        # Add ATR period if adaptive stops/TPs are used
        if self.settings.ENABLE_ADAPTIVE_RISK and ('ATR' in self.settings.STOP_LOSS_TYPE or 'ATR' in self.settings.TAKE_PROFIT_TYPE):
             self.min_data_points_global = max(self.min_data_points_global, self.settings.ATR_PERIOD + 1)
        # Add Regime Detector requirements
        if hasattr(self.regime_detector, 'min_data_points'):
             self.min_data_points_global = max(self.min_data_points_global, self.regime_detector.min_data_points)
        self.logger.info(f"Minimum data points required globally (Strategies & Regime): {self.min_data_points_global}")


        # --- Internal State ---
        # {symbol: pd.DataFrame with UTC index}
        self.market_data = {}
        # {symbol: list_of_dicts with UTC timestamps} - Buffer for incoming historical bars
        self.historical_data_buffer = {}
        # {reqId: symbol} - Track historical data requests
        self.historical_data_req_ids = {}
        # {symbol: float} - Latest calculated ATR value
        self.latest_atr = {}
        # {symbol: datetime} - Last time regime was checked (aware UTC)
        self.last_regime_check_time = defaultdict(lambda: datetime.min.replace(tzinfo=pytz.utc))
        # {symbol: bool} - Track trading pause state per symbol
        self.symbol_trading_paused = defaultdict(bool)
        # {symbol: str} - Track pause reason per symbol
        self.pause_reason = defaultdict(str)

        self.running = False
        self.main_thread = None
        self._lock = threading.Lock() # General lock for TradingBot internal state if needed
        self._retrain_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1) # Background executor for training
        self._retrain_future = None

        self.last_state_save_time = datetime.min.replace(tzinfo=pytz.utc)
        self.last_reconciliation_time = datetime.min.replace(tzinfo=pytz.utc)
        # self.last_optimizer_run_time = datetime.min.replace(tzinfo=pytz.utc) # Keep if optimizer used
        self.last_risk_check_time = datetime.min.replace(tzinfo=pytz.utc)
        self.last_stale_data_check_time = datetime.min.replace(tzinfo=pytz.utc)


    def prompt_user_config(self, args=None):
        """
        Configures bot settings from CLI args, env vars, or interactive prompts.
        Priority: CLI args > env vars > interactive prompts > defaults

        Args:
            args: argparse.Namespace from parse_args(), or None for interactive mode
        """
        # If args provided (headless mode), use them; else prompt
        headless = args is not None

        # Trading Mode
        if headless and args.mode:
            mode_map = {'stock': 'stock', 'crypto': 'crypto', 'forex': 'forex'}
            self.settings.TRADING_MODE = mode_map.get(args.mode.lower(), 'crypto')
        elif not headless:
            print("\n--- AIStocker Configuration ---")
            while True:
                print("Select Trading Mode:")
                print("  1: Stock")
                print("  2: Crypto")
                print("  3: Forex")
                choice = input("Enter choice [1, 2, or 3]: ").strip()
                if choice == '1': self.settings.TRADING_MODE = 'stock'; break
                elif choice == '2': self.settings.TRADING_MODE = 'crypto'; break
                elif choice == '3': self.settings.TRADING_MODE = 'forex'; break
                else: print("Invalid input.")
        self.logger.info(f"Trading Mode set to: {self.settings.TRADING_MODE}")

        # Default instruments per mode
        default_instruments_map = {
            'stock': ['AAPL', 'MSFT', 'SPY'],
            'crypto': ['ETH/USD', 'BTC/USD'],
            'forex': ['EUR/USD', 'GBP/USD']
        }
        default_instruments = default_instruments_map.get(self.settings.TRADING_MODE, ['ETH/USD', 'BTC/USD'])

        # Instruments
        if headless and args.instruments:
            self.settings.TRADE_INSTRUMENTS = [inst.strip().upper() for inst in args.instruments.split(',') if inst.strip()]
        elif not headless:
            instr_prompt = f"Enter instruments (comma-separated, e.g., {','.join(default_instruments)}): "
            instr_input = input(instr_prompt).strip()
            if instr_input:
                self.settings.TRADE_INSTRUMENTS = [inst.strip().upper() for inst in instr_input.split(',') if inst.strip()]
            else:
                self.settings.TRADE_INSTRUMENTS = default_instruments
        else:
            # Headless but no instruments specified, use defaults
            self.settings.TRADE_INSTRUMENTS = default_instruments
        self.logger.info(f"Trading Instruments selected: {self.settings.TRADE_INSTRUMENTS}")

        # Autonomous Mode
        if headless:
            self.settings.AUTONOMOUS_MODE = args.autonomous if hasattr(args, 'autonomous') else True
        elif not headless:
            while True:
                choice = input(f"Enable Autonomous Mode? (Adapts strategies/risk) [Y/n]: ").strip().lower()
                if choice in ['y', 'yes', '']: self.settings.AUTONOMOUS_MODE = True; break
                elif choice in ['n', 'no']: self.settings.AUTONOMOUS_MODE = False; break
                else: print("Invalid input.")
        self.logger.info(f"Autonomous Mode set to: {self.settings.AUTONOMOUS_MODE}")

        # Dependent settings if Autonomous Mode enabled
        if self.settings.AUTONOMOUS_MODE:
            if headless:
                self.settings.ENABLE_ADAPTIVE_RISK = args.adaptive_risk if hasattr(args, 'adaptive_risk') else True
                self.settings.ENABLE_AUTO_RETRAINING = args.auto_retrain if hasattr(args, 'auto_retrain') else True
                self.settings.ENABLE_DYNAMIC_STRATEGY_WEIGHTING = args.dynamic_weighting if hasattr(args, 'dynamic_weighting') else True
            else:
                while True:
                    choice = input(f"  Enable Adaptive Risk? (Adapts SL/TP based on volatility) [Y/n]: ").strip().lower()
                    if choice in ['y', 'yes', '']: self.settings.ENABLE_ADAPTIVE_RISK = True; break
                    elif choice in ['n', 'no']: self.settings.ENABLE_ADAPTIVE_RISK = False; break
                    else: print("Invalid input.")
                self.logger.info(f"Adaptive Risk set to: {self.settings.ENABLE_ADAPTIVE_RISK}")

                while True:
                    choice = input(f"  Enable Automated ML Retraining? (If ML strategy enabled) [Y/n]: ").strip().lower()
                    if choice in ['y', 'yes', '']: self.settings.ENABLE_AUTO_RETRAINING = True; break
                    elif choice in ['n', 'no']: self.settings.ENABLE_AUTO_RETRAINING = False; break
                    else: print("Invalid input.")
                self.logger.info(f"Automated Retraining set to: {self.settings.ENABLE_AUTO_RETRAINING}")

                while True:
                    choice = input(f"  Enable Dynamic Strategy Weighting? [Y/n]: ").strip().lower()
                    if choice in ['y', 'yes', '']: self.settings.ENABLE_DYNAMIC_STRATEGY_WEIGHTING = True; break
                    elif choice in ['n', 'no']: self.settings.ENABLE_DYNAMIC_STRATEGY_WEIGHTING = False; break
                    else: print("Invalid input.")
                self.logger.info(f"Dynamic Strategy Weighting set to: {self.settings.ENABLE_DYNAMIC_STRATEGY_WEIGHTING}")

        # Continue After Close (only ask if stock mode)
        if self.settings.TRADING_MODE == 'stock':
            if headless:
                self.settings.CONTINUE_AFTER_CLOSE = args.extended_hours if hasattr(args, 'extended_hours') else False
            else:
                while True:
                    choice = input("Allow trading in extended hours? [y/N]: ").strip().lower()
                    if choice in ['y', 'yes']: self.settings.CONTINUE_AFTER_CLOSE = True; break
                    elif choice in ['n', 'no', '']: self.settings.CONTINUE_AFTER_CLOSE = False; break
                    else: print("Invalid input.")
            self.logger.info(f"Continue After Close (Extended Hours) set to: {self.settings.CONTINUE_AFTER_CLOSE}")
        else: # Force True for 24/7 markets
            self.settings.CONTINUE_AFTER_CLOSE = True
            self.logger.info(f"Continue After Close set to True (Crypto/Forex Mode).")

        # Validate instruments based on mode (using heuristics for now)
        valid_instruments = []
        for inst in self.settings.TRADE_INSTRUMENTS:
            contract = create_contract(inst) # Use utility (heuristic check)
            if contract is None:
                 print(f"Warning: Could not create valid contract for '{inst}'. Skipping.")
                 self.logger.warning(f"Skipping invalid instrument format: '{inst}'")
            elif self.settings.TRADING_MODE == 'stock' and contract.secType != 'STK':
                 print(f"Warning: '{inst}' determined as {contract.secType} but mode is Stock. Skipping.")
                 self.logger.warning(f"Skipping instrument '{inst}' ({contract.secType}) due to mode mismatch (stock).")
            elif self.settings.TRADING_MODE == 'crypto' and contract.secType != 'CRYPTO':
                 print(f"Warning: '{inst}' determined as {contract.secType} but mode is Crypto. Skipping.")
                 self.logger.warning(f"Skipping instrument '{inst}' ({contract.secType}) due to mode mismatch (crypto).")
            elif self.settings.TRADING_MODE == 'forex' and contract.secType != 'CASH':
                 print(f"Warning: '{inst}' determined as {contract.secType} but mode is Forex. Skipping.")
                 self.logger.warning(f"Skipping instrument '{inst}' ({contract.secType}) due to mode mismatch (forex).")
            else:
                 valid_instruments.append(inst)
        self.settings.TRADE_INSTRUMENTS = valid_instruments
        if not self.settings.TRADE_INSTRUMENTS:
             print("Error: No valid instruments selected after validation. Exiting.")
             self.logger.critical("No valid instruments selected after validation.")
             return False # Indicate failure
        self.logger.info(f"Validated Trading Instruments: {self.settings.TRADE_INSTRUMENTS}")

        return True

    # --- Callbacks & Error Handling ---
    def on_aggregator_error(self, message=""):
        """Callback if DataAggregator stops due to errors."""
        self.error_logger.critical(f"DataAggregator Error Callback Triggered: {message}. Stopping TradingBot.")
        self.stop(reason=f"Aggregator Failure: {message}")

    # --- Lifecycle ---
    def start(self):
        """Connects to API, loads state, requests data, starts main loop."""
        self.logger.info("--- Starting Trading Bot ---")
        self.running = True

        # 1. Load State
        self.logger.info("Loading previous bot state...")
        state_loaded_ok = self.state_manager.load_state()
        if state_loaded_ok:
            self.logger.info("Successfully loaded previous state.")
            # TODO: Apply loaded state to StrategyManager/Optimizer if they have persistent state
            # self.strategy_manager.load_state(self.state_manager.get_component_state('strategy_manager')) # Example
        else:
            self.logger.warning("Starting with fresh state (state file not found or failed to load).")
            # Critical check: If state load failed but file existed, manual intervention might be needed.
            if os.path.exists(self.state_manager.state_file):
                 self.error_logger.critical(f"Failed to load existing state file '{self.state_manager.state_file}'. Starting fresh, but review the file!")


        # 2. Connect API (Starts connection thread)
        self.api.connect_app()

        # ---> MODIFIED PART START <---
        # 3. Wait for API to be Ready (Connection + Initial Data)
        self.logger.info("Waiting for API connection and initial data...")
        api_ready_ok = self.api.api_ready.wait(timeout=65) # Use a generous timeout

        if not api_ready_ok:
            self.error_logger.critical("API failed to become ready within timeout. Bot cannot start.")
            self.stop(reason="API Ready Timeout")
            return
        elif not self.api.is_connected(): # Double-check connection status just in case
             self.error_logger.critical("API Ready event set, but is_connected() is false. Bot cannot start.")
             self.stop(reason="API Connection Discrepancy")
             return
        else:
             self.logger.info("API connection established and initial data received.")
        # ---> MODIFIED PART END <---


        # 4. Request Contract Details (NOW safe to call)
        self.logger.info("Requesting contract details...")
        self.request_all_contract_details()
        # Wait for details (implement timeout/check) - crucial for accurate sizing/tick info
        if not self._wait_for_contract_details(timeout=30):
             self.logger.warning("Contract details request may be incomplete (timeout or error). Proceeding with heuristics.")
             # Bot can continue but might use less accurate sizing/rounding.

        # 5. Reconciliation Complete Check (Already waited in _wait_for_initial_data)
        # Log status after wait
        if not self.api.positions_received.is_set():
             self.logger.warning("Position reconciliation may be incomplete (initial wait timed out).")
        if not self.api.open_orders_received.is_set():
             self.logger.warning("Order reconciliation may be incomplete (initial wait timed out).")
        self.logger.info("Initial reconciliation process complete (or timed out).")


        # 6. Request Initial Historical Data
        instruments_to_load = list(self.settings.TRADE_INSTRUMENTS)
        self.logger.info(f"Requesting initial historical data for: {instruments_to_load}")
        request_interval = 0.7 # Pacing (slightly increased)
        for instrument in instruments_to_load:
            if not self.running: break
            self.request_historical_data(instrument)
            time.sleep(request_interval)

        # 7. Start Main Loop ONLY if API connected & bot running
        if self.running and self.api.is_connected():
            self.logger.info("Starting main trading loop...")
            self.main_thread = threading.Thread(target=self.main_loop, name="TradingBotMainLoop", daemon=True)
            self.main_thread.start()
            self.logger.info("--- Trading Bot Started Successfully ---")
        elif self.running:
            self.error_logger.critical("API disconnected before main loop could start. Bot stopped.")
            self.stop(reason="API Disconnected Pre-Loop")
        else:
             self.logger.info("Bot startup sequence interrupted by stop signal.")


    def stop(self, reason="Unknown"):
        """Initiates safe shutdown sequence."""
        # Prevent double execution
        if not self.running: return
        self.logger.info(f"--- Stopping Trading Bot (Reason: {reason}) ---")
        self.running = False # Signal loops FIRST

        # 1. Shutdown background tasks (like training)
        if self._retrain_future and not self._retrain_future.done():
            self.logger.info("Attempting to cancel ongoing ML retraining task...")
            # Executor doesn't directly support cancellation, rely on task checking self.running
            # Consider adding a self.running check inside _run_training_task
            # self._retrain_future.cancel() # May not work depending on task
        self._retrain_executor.shutdown(wait=False, cancel_futures=True) # cancel_futures available in Python 3.9+
        self.logger.info("Retraining executor shutdown requested.")

        # 2. Stop Data Aggregator
        if hasattr(self, 'data_aggregator') and self.data_aggregator:
            self.logger.info("Stopping Data Aggregator...")
            self.data_aggregator.stop()

        # 3. Wait for Main Loop
        if self.main_thread and self.main_thread.is_alive():
            self.logger.info("Waiting for main loop to finish...")
            self.main_thread.join(timeout=15) # Increased timeout
            if self.main_thread.is_alive(): self.logger.warning("Main loop did not exit cleanly after 15 seconds.")

        # 4. Cancel Open Orders (Optional - Controlled by Setting)
        if self.settings.CANCEL_ORDERS_ON_EXIT:
            self.logger.info("Cancelling all open orders as per settings...")
            if hasattr(self, 'order_manager') and self.order_manager and self.api.is_connected():
                open_ids = self.order_manager.get_open_order_ids()
                if open_ids:
                    self.logger.info(f"Requesting cancellation for {len(open_ids)} orders...")
                    for oid in open_ids: self.order_manager.cancel_order(oid); time.sleep(0.1)
                    time.sleep(3) # Allow cancellations to process
                    self.logger.info("Cancellation requests submitted.")
                else: self.logger.info("No open orders found to cancel.")
            elif not self.api.is_connected():
                 self.logger.warning("Cannot cancel orders: API is disconnected.")
            else: self.logger.warning("Cannot cancel orders: Order Manager unavailable.")
        else:
            self.logger.info("Skipping cancellation of open orders on exit (CANCEL_ORDERS_ON_EXIT is False).")

        # 5. Save Final State
        if hasattr(self, 'state_manager') and self.state_manager:
            self.logger.info("Saving final bot state...")
            # TODO: Get state from StrategyManager/Optimizer if they have persistent state
            # self.state_manager.add_component_state('strategy_manager', self.strategy_manager.get_state()) # Example
            self.state_manager.save_state()
            self.logger.info("Final bot state saved.")
        else: self.logger.warning("State manager not available, cannot save final state.")

        # 6. Disconnect API
        if hasattr(self, 'api') and self.api:
            self.logger.info("Disconnecting API...")
            if self.api.is_connected(): # Use the corrected is_connected() method
                self.api.disconnect_app()
            else:
                self.logger.info("API already disconnected.")
             # Wait for API thread to finish if it exists
            if self.api.api_thread and self.api.api_thread.is_alive():
                 self.logger.info("Waiting for API message loop thread to finish...")
                 self.api.api_thread.join(timeout=5)
                 if self.api.api_thread.is_alive():
                      self.logger.warning("API message loop thread did not exit cleanly.")


        self.logger.info("--- Trading Bot Stopped ---")
        logging.shutdown() # Ensure all log handlers are flushed and closed


    # --- Data Handling (Contract Details, Historical & Live Processing) ---

    def request_all_contract_details(self):
        """Requests contract details for all instruments configured for trading."""
        if not self.api or not self.api.is_connected():
            self.logger.warning("Cannot request contract details: API not connected.")
            return
        self.logger.info(f"Requesting contract details for: {self.settings.TRADE_INSTRUMENTS}")
        for symbol in self.settings.TRADE_INSTRUMENTS:
            if not self.running: break
            self.api.request_contract_details(symbol)
            time.sleep(0.2) # Pacing for requests

    def _wait_for_contract_details(self, timeout=30):
         """ Waits for contract details cache in API to be populated. """
         self.logger.info(f"Waiting up to {timeout}s for contract details...")
         start_time = time.time()
         all_details_received = True
         while time.time() - start_time < timeout:
             if not self.running or not self.api.is_connected():
                 self.error_logger.error("Stopped or disconnected while waiting for contract details.")
                 return False
             missing_symbols = []
             with self.api.api_lock: # Access cache safely
                  for symbol in self.settings.TRADE_INSTRUMENTS:
                       if symbol not in self.api.contract_details_cache:
                            missing_symbols.append(symbol)

             if not missing_symbols:
                 self.logger.info("All contract details received.")
                 return True
             # Log missing periodically
             if int(time.time() - start_time) % 5 == 0:
                  self.logger.debug(f"Still waiting for contract details for: {missing_symbols}")

             time.sleep(0.5)

         # Timeout reached
         if missing_symbols:
             self.logger.warning(f"Timeout waiting for contract details. Missing for: {missing_symbols}")
             all_details_received = False

         return all_details_received


    def request_historical_data(self, symbol):
        """Requests historical data from IBKR API."""
        with self._lock: # Protect access to buffer/req_ids
            if symbol in self.historical_data_req_ids: # Check tracking dictionary
                self.logger.warning(f"Historical data request already pending for {symbol}. Skipping duplicate request.")
                return

        # Use heuristic contract first to determine whatToShow, etc.
        contract = create_contract(symbol, self.api) # Use heuristic contract, pass API for potential cache use
        if not contract:
             self.error_logger.error(f"Cannot request historical data: Failed to create contract for {symbol}")
             return

        points_to_request = max(self.min_data_points_global + 100, 250) # Increased buffer
        duration_days = 1
        try:
            bar_size_seconds = self.data_aggregator.bar_size.total_seconds()
            if bar_size_seconds > 0:
                 seconds_in_day = 24 * 60 * 60
                 if contract.secType == 'STK' and not self.settings.CONTINUE_AFTER_CLOSE:
                      seconds_in_day = 6.5 * 60 * 60 # Approx RTH for US stocks
                 bars_per_day = max(1, seconds_in_day / bar_size_seconds) # Approx
                 duration_days = max(1, int(np.ceil(points_to_request / bars_per_day)))
            duration_days = min(duration_days, 90) # Limit request duration
            self.logger.debug(f"Calculated duration: {duration_days} days for {points_to_request} bars @ {self.settings.TIMEFRAME}")
        except Exception as e:
             self.logger.warning(f"Could not estimate duration from timeframe '{self.settings.TIMEFRAME}': {e}. Using default.")

        duration_str = f"{duration_days} D"
        what_to_show = 'TRADES'
        if contract.secType == "CRYPTO": what_to_show = 'AGGTRADES'
        elif contract.secType == "CASH": what_to_show = 'MIDPOINT'
        use_rth = 1 if contract.secType == "STK" and not self.settings.CONTINUE_AFTER_CLOSE else 0

        req_id = self.api.get_next_req_id()
        with self._lock: # Protect access to buffer/req_ids
            self.historical_data_req_ids[req_id] = symbol # Add to tracking dict
            self.api.active_hist_data_reqs[req_id] = symbol # Let API also track it
            self.historical_data_buffer[symbol] = [] # Initialize buffer

        self.logger.info(f"Requesting historical data for {symbol} (ReqId: {req_id}), "
                         f"Duration: {duration_str}, BarSize: {self.settings.TIMEFRAME}, Show: {what_to_show}, UseRTH: {use_rth}")
        try:
            # Use format 1 for UTC timestamps
            self.api.reqHistoricalData(req_id, contract, '', duration_str, self.settings.TIMEFRAME, what_to_show, use_rth, 1, False, [])
        except Exception as e:
            self.error_logger.error(f"Exception during reqHistoricalData for {symbol} (ReqId: {req_id}): {e}", exc_info=True)
            with self._lock: # Clean up on exception during request
                self.historical_data_req_ids.pop(req_id, None)
                self.api.active_hist_data_reqs.pop(req_id, None)
                self.historical_data_buffer.pop(symbol, None)


    def process_historical_bar(self, symbol, bar):
        """Callback from IBKRApi to add a historical bar (dict with UTC time) to buffer."""
        # --- Logic to parse bar data and add to self.historical_data_buffer[symbol] ---
        # (Ensure timestamp is parsed to aware UTC datetime)
        try:
             # Use API's parser which handles multiple formats including Unix time
             parsed_time_utc = self.api._parse_ibkr_timestamp(bar.date)

             if parsed_time_utc is None:
                  self.logger.warning(f"Could not parse historical date format for {symbol}: '{bar.date}'")
                  return

             bar_data = {
                 'timestamp': parsed_time_utc, # Store aware UTC
                 'open': float(bar.open), 'high': float(bar.high), 'low': float(bar.low), 'close': float(bar.close),
                 'volume': int(bar.volume) if bar.volume != -1 else 0
             }
             with self._lock: # Protect buffer access
                 if symbol in self.historical_data_buffer:
                     self.historical_data_buffer[symbol].append(bar_data)
                 else:
                     self.logger.warning(f"Received historical bar for {symbol} but buffer not initialized?")
        except Exception as e:
             self.error_logger.error(f"Error processing historical bar for {symbol}: {bar} - {e}", exc_info=True)


    def finalize_historical_data(self, symbol):
        """Processes buffered historical data, cleans, merges, saves, subscribes live."""
        # Remove from bot's tracking dict *before* processing
        with self._lock:
             # Find reqId associated with this symbol to remove from bot's tracking
             req_id_to_remove = None
             for rid, sym in self.historical_data_req_ids.items():
                 if sym == symbol:
                     req_id_to_remove = rid
                     break
             if req_id_to_remove:
                 del self.historical_data_req_ids[req_id_to_remove]
             else:
                  self.logger.warning(f"Could not find reqId in bot tracking for finalized historical data: {symbol}")

             # Now safely pop the buffer data
             if symbol not in self.historical_data_buffer:
                 self.logger.debug(f"Finalize called for {symbol} but no buffer found.")
                 buffered_bars = [] # Ensure it's defined
             else:
                 buffered_bars = self.historical_data_buffer.pop(symbol, [])


        if not buffered_bars:
             self.logger.warning(f"No historical bars processed for {symbol} upon finalization.")
             hist_df = pd.DataFrame() # Empty dataframe
        else:
            hist_df = pd.DataFrame(buffered_bars)
            if not hist_df.empty:
                # Clean & Process
                try:
                    # Timestamp is already aware UTC from process_historical_bar
                    hist_df = hist_df.sort_values(by='timestamp').drop_duplicates(subset=['timestamp'], keep='last')
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        hist_df[col] = pd.to_numeric(hist_df[col], errors='coerce')
                    hist_df[['open', 'high', 'low', 'close']] = hist_df[['open', 'high', 'low', 'close']].ffill() # Use ffill for OHLC
                    hist_df['volume'] = hist_df['volume'].fillna(0)
                    hist_df.dropna(subset=['timestamp', 'open', 'high', 'low', 'close'], inplace=True) # Drop rows where OHLC still NaN
                    hist_df = hist_df.set_index('timestamp') # Use UTC timestamp as index

                except Exception as e:
                     self.error_logger.error(f"Error cleaning historical data for {symbol}: {e}", exc_info=True)
                     hist_df = pd.DataFrame() # Reset on error
            else:
                 self.logger.warning(f"Historical buffer for {symbol} resulted in empty DataFrame.")

        # Merge with existing live data (if any)
        with self._lock: # Protect market_data access
             live_df = self.market_data.get(symbol)
             if live_df is not None and not live_df.empty:
                  # Ensure live_df also has UTC DatetimeIndex
                  if not isinstance(live_df.index, pd.DatetimeIndex) or live_df.index.tz is None:
                       try:
                            live_df = live_df.set_index(pd.to_datetime(live_df.index, utc=True))
                       except Exception as e:
                           self.error_logger.error(f"Failed to convert existing live data index to UTC for {symbol}: {e}. Discarding old live data.")
                           live_df = None # Discard if conversion fails

                  if live_df is not None and not hist_df.empty:
                      # Combine, ensure no duplicates (keep historical), sort
                      combined_df = pd.concat([hist_df, live_df])
                      combined_df = combined_df[~combined_df.index.duplicated(keep='last')].sort_index()
                      self.market_data[symbol] = combined_df
                  elif not hist_df.empty:
                       self.market_data[symbol] = hist_df # Only have historical
                  # else: keep existing live_df if hist_df is empty

             elif not hist_df.empty: # No existing live data, only historical
                  self.market_data[symbol] = hist_df

             final_count = len(self.market_data.get(symbol, pd.DataFrame()))
             self.logger.info(f"Finalized historical data for {symbol}. Total bars now: {final_count}")
             # Save initial historical load
             if final_count > 0: self.save_market_data(symbol, data_type='historical')


        # Ensure live data subscription is active/attempted regardless of history success
        # Check if symbol was previously unsubscribed due to errors
        if symbol not in self.api.unsubscribed_symbols:
            self.logger.info(f"Ensuring live data subscription for {symbol} after historical load.")
            self.data_aggregator.subscribe_symbols([symbol]) # Make sure aggregator knows about it
            self.api.subscribe_market_data(symbol) # Make sure API subscription is active
        else:
            self.logger.warning(f"Skipping live data subscription for {symbol} as it was previously marked unsubscribed.")


    def save_market_data(self, symbol, data_type='live'):
        """Saves the aggregated market data bars (with UTC index) to CSV."""
        df_to_save = self.get_market_data(symbol) # Gets copy with UTC index
        if df_to_save is None or df_to_save.empty: return

        directory = f'data/{data_type}_data'
        try:
             os.makedirs(directory, exist_ok=True)
             # Sanitize filename (replace slashes common in forex/crypto)
             safe_filename = re.sub(r'[\\/*?:"<>|]', "_", symbol)
             file_path = os.path.join(directory, f"{safe_filename}.csv")
             # Save with index (timestamp)
             df_to_save.to_csv(file_path, index=True)
             self.logger.info(f"Saved {data_type} data ({len(df_to_save)} bars) for {symbol} to {file_path}")
        except Exception as e:
            self.error_logger.error(f"Failed to save market data for {symbol} to {file_path}: {e}", exc_info=True)


    # --- Market State Checks ---
    def get_exchange_tz(self, symbol):
        """ Get the timezone for the symbol's primary exchange using ContractDetails or settings. """
        # Prioritize ContractDetails if available
        details = get_contract_details(symbol, self.api)
        if details and isinstance(details, ContractDetails) and details.timeZoneId:
            try:
                return pytz.timezone(details.timeZoneId)
            except pytz.UnknownTimeZoneError:
                self.logger.warning(f"Unknown timezone '{details.timeZoneId}' from ContractDetails for {symbol}. Falling back.")

        # Fallback to settings heuristics
        contract = create_contract(symbol, self.api) # Use API for potential cache hit
        exchange = contract.exchange if contract else 'SMART' # Default to SMART
        tz_name = self.settings.EXCHANGE_TIMEZONES.get(exchange, self.settings.TIMEZONE) # Fallback to default bot TZ
        try:
            return pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            self.logger.warning(f"Unknown timezone '{tz_name}' for exchange '{exchange}' in settings. Using default {DEFAULT_TZ_STR}.")
            return DEFAULT_TZ

    def is_market_open(self, symbol):
        """ Checks if the market for the given symbol is likely open using timezones and basic rules. """
        # TODO: Enhance with trading hours from ContractDetails for more accuracy
        contract = create_contract(symbol, self.api) # Get best contract available
        sec_type = contract.secType if contract else None
        exchange_tz = self.get_exchange_tz(symbol)
        now_exchange_time = datetime.now(exchange_tz)
        now_utc = datetime.now(pytz.utc) # For comparison

        # --- Add Holiday Check Here ---
        # Placeholder for pandas_market_calendars or similar logic
        # is_holiday = check_holiday(symbol, now_exchange_time.date()) # Assumed function
        # if is_holiday: return False

        # --- Basic time checks ---
        if sec_type == "STK":
             market_open_time = dt_time(9, 30)
             market_close_time = dt_time(16, 0)
             ext_hours_end_time = dt_time(20, 0) # Post-market typically ends 8 PM ET
             is_weekday = now_exchange_time.weekday() < 5 # Monday = 0, Friday = 4
             if not is_weekday: return False

             current_time = now_exchange_time.time()
             is_regular_open = market_open_time <= current_time < market_close_time
             is_extended_trading = self.settings.CONTINUE_AFTER_CLOSE and \
                                   (market_close_time <= current_time < ext_hours_end_time)
             # Consider pre-market?
             # pre_market_start_time = dt_time(4, 0)
             # is_pre_market = self.settings.CONTINUE_AFTER_CLOSE and \
             #                 (pre_market_start_time <= current_time < market_open_time)
             # return is_regular_open or is_extended_trading or is_pre_market
             return is_regular_open or is_extended_trading

        elif sec_type == "CRYPTO": return True # Assume 24/7

        elif sec_type == "CASH": # Forex
             # ~Sunday 5 PM ET to Friday 5 PM ET
             try: ny_tz = pytz.timezone('America/New_York')
             except pytz.UnknownTimeZoneError: ny_tz = DEFAULT_TZ # Fallback
             now_ny_time = datetime.now(ny_tz)
             day_of_week = now_ny_time.weekday(); current_ny_time = now_ny_time.time()
             is_weekend_closure = (day_of_week == 4 and current_ny_time >= dt_time(17, 0)) or \
                                  day_of_week == 5 or \
                                  (day_of_week == 6 and current_ny_time < dt_time(17, 0))
             return not is_weekend_closure
        else:
             self.logger.warning(f"Market open check not implemented for secType: {sec_type}. Assuming open.")
             return True # Default to open if unsure? Risky.


    def check_pause_conditions(self, symbol):
        """Checks if trading for a specific symbol should be paused (e.g., market closed)."""
        is_open = self.is_market_open(symbol)
        contract = create_contract(symbol, self.api)
        sec_type = contract.secType if contract else 'Unknown'

        should_pause = False
        pause_reason = ""

        # Pause based on market hours (respecting CONTINUE_AFTER_CLOSE)
        if not is_open:
             if sec_type == 'STK': should_pause, pause_reason = True, "Market Closed"
             elif sec_type == 'CASH': should_pause, pause_reason = True, "Forex Market Closed (Weekend)"

        # Check if symbol was unsubscribed due to API/data errors
        if symbol in self.api.unsubscribed_symbols:
            should_pause = True
            pause_reason = "Data Subscription Issue"

        # Check for stale data (from main loop check)
        # Note: Main loop already pauses based on stale data, this is redundant if called after that check
        # latest_price_info = self.portfolio_manager.get_latest_prices_copy().get(symbol)
        # now_utc = datetime.now(pytz.utc)
        # if latest_price_info and (now_utc - latest_price_info['time']) > timedelta(seconds=self.settings.MAX_DATA_STALENESS_SECONDS):
        #      should_pause = True
        #      pause_reason = "Stale Market Data"

        # Update pause state and log changes
        with self._lock: # Protect pause state dict
            currently_paused = self.symbol_trading_paused.get(symbol, False)
            if should_pause and not currently_paused:
                self.symbol_trading_paused[symbol] = True
                self.pause_reason[symbol] = pause_reason
                self.logger.info(f"Pausing trading evaluation for {symbol}. Reason: {pause_reason}")
            elif not should_pause and currently_paused:
                self.symbol_trading_paused[symbol] = False
                self.pause_reason[symbol] = ""
                self.logger.info(f"Resuming trading evaluation for {symbol}.")

        return should_pause


    # --- Automated Retraining Trigger ---
    def check_and_trigger_retraining(self):
        """ Checks if MLStrategy requests retraining and starts it in the background. """
        if not self.settings.AUTONOMOUS_MODE or not self.settings.ENABLE_AUTO_RETRAINING:
            return
        if not any(isinstance(s, MLStrategy) for s in self.strategy_manager.get_strategies()):
            return

        if MLStrategy.is_retraining_requested():
            if self._retrain_future is None or self._retrain_future.done():
                self.logger.info("Initiating automated ML model retraining in background...")
                MLStrategy.clear_retraining_request()
                self._retrain_future = self._retrain_executor.submit(self._run_training_task)
            else:
                self.logger.info("Retraining requested, but a previous retraining task is still running.")


    def _run_training_task(self):
        """ Wrapper function to execute training and handle results/errors. """
        self.logger.info("Background retraining task started.")
        success = False
        try:
            os.makedirs('logs/error_logs', exist_ok=True)
            os.makedirs('logs', exist_ok=True)
            os.makedirs('models', exist_ok=True)
            os.makedirs('data/historical_data', exist_ok=True)
            os.makedirs('data/live_data', exist_ok=True)

            success = train_model_main() # Call the training script's main function
            if success:
                self.logger.info("Background retraining task completed successfully.")
                for strategy in self.strategy_manager.get_strategies():
                     if isinstance(strategy, MLStrategy):
                          strategy.load_model(force_reload=True)
            else:
                self.error_logger.error("Background retraining task failed (returned False).")

        except Exception as e:
            self.error_logger.critical(f"Exception in background retraining task: {e}", exc_info=True)
        finally:
            self.logger.info(f"Background retraining task finished (Success: {success}).")
            if self._retrain_future and self._retrain_future.done():
                 if self._retrain_future.exception():
                     self.error_logger.error(f"Exception reported by retraining future: {self._retrain_future.exception()}")


    # --- Main Execution Loop ---
    def main_loop(self):
        """ Main loop processing bars, evaluating strategies, managing trades. """
        self.logger.info("Main trading loop started.")
        spinner = ['|', '/', '-', '\\']
        idx = 0

        while self.running:
            try:
                loop_start_time = time.monotonic()
                current_time_utc = datetime.now(pytz.utc)

                # --- Check API Connection ---
                if not self.api.is_connected():
                    self.error_logger.error("API disconnected in main loop. Initiating stop.")
                    self.stop(reason="API Disconnected")
                    break # Exit loop immediately

                # --- Automated Retraining Check ---
                self.check_and_trigger_retraining()

                # --- Periodic Tasks ---
                if current_time_utc - self.last_state_save_time > timedelta(seconds=self.settings.STATE_SAVE_INTERVAL_SECONDS):
                    self.state_manager.save_state(); self.last_state_save_time = current_time_utc
                if current_time_utc - self.last_reconciliation_time > timedelta(seconds=self.settings.RECONCILIATION_INTERVAL_SECONDS):
                    if self.api.is_connected(): self.api.request_account_and_positions(); self.last_reconciliation_time = current_time_utc
                if current_time_utc - self.last_risk_check_time > timedelta(seconds=60):
                    latest_prices = self.portfolio_manager.get_latest_prices_copy()
                    self.risk_manager.check_portfolio_risk(latest_prices); self.last_risk_check_time = current_time_utc

                # --- Process New Bars ---
                bars_processed_this_cycle = 0
                for symbol in list(self.settings.TRADE_INSTRUMENTS): # Iterate over copy
                    if not self.running: break
                    bar_queue = self.data_aggregator.get_bar_queue(symbol)
                    if bar_queue:
                        try:
                            while not bar_queue.empty():
                                new_bar_df = bar_queue.get_nowait() # DataFrame with UTC timestamp index
                                if new_bar_df is not None and not new_bar_df.empty:
                                    with self._lock: # Lock access to shared market_data
                                        current_df = self.market_data.get(symbol)
                                        if current_df is None or current_df.empty:
                                            self.market_data[symbol] = new_bar_df
                                        else:
                                            # Ensure index types match
                                            if not isinstance(current_df.index, pd.DatetimeIndex) or current_df.index.tz is None:
                                                 try: current_df = current_df.set_index(pd.to_datetime(current_df.index, utc=True))
                                                 except Exception: current_df = pd.DataFrame() # Discard on error
                                            combined = pd.concat([current_df, new_bar_df])
                                            combined = combined[~combined.index.duplicated(keep='last')].sort_index()
                                            max_bars = self.settings.MAX_BARS_IN_MEMORY
                                            if len(combined) > max_bars: combined = combined.iloc[-max_bars:]
                                            self.market_data[symbol] = combined

                                    new_bar = new_bar_df.iloc[0]
                                    ts_str = new_bar.name.strftime(self.settings.LOG_TIMESTAMP_FORMAT)
                                    self.logger.debug(f"Processed new bar for {symbol}: {ts_str} C={new_bar['close']:.5f}")
                                    bars_processed_this_cycle += 1
                                    if bars_processed_this_cycle % 20 == 0:
                                         self.save_market_data(symbol, data_type='live')

                        except queue.Empty: pass
                        except Exception as e: self.error_logger.error(f"Error processing bar queue for {symbol}: {e}", exc_info=True)

                # --- Check for Stale Data ---
                stale_check_interval = timedelta(seconds=self.settings.MAX_DATA_STALENESS_SECONDS / 2)
                if current_time_utc - self.last_stale_data_check_time > stale_check_interval:
                     self.last_stale_data_check_time = current_time_utc
                     for symbol in self.settings.TRADE_INSTRUMENTS:
                          latest_price_info = self.portfolio_manager.get_latest_prices_copy().get(symbol)
                          is_stale = False
                          if latest_price_info:
                              price_time_utc = latest_price_info['time']
                              if (current_time_utc - price_time_utc) > timedelta(seconds=self.settings.MAX_DATA_STALENESS_SECONDS):
                                   is_stale = True
                                   last_update_str = price_time_utc.strftime(self.settings.LOG_TIMESTAMP_FORMAT)
                                   reason = f"potentially stale (last update: {last_update_str})"
                          elif self.get_position_size(symbol) != 0: # Holding position but no price info
                               is_stale = True
                               reason = "no recent price data available"

                          # Update pause state based on staleness
                          with self._lock:
                              currently_paused = self.symbol_trading_paused.get(symbol, False)
                              if is_stale and not currently_paused:
                                   self.symbol_trading_paused[symbol] = True
                                   self.logger.warning(f"Market data for {symbol} is {reason}. Trading paused for symbol.")
                              elif not is_stale and currently_paused and "Stale" in self.pause_reason.get(symbol, ""): # Unpause if ONLY paused for staleness
                                   # More complex logic needed if multiple pause reasons can exist
                                   self.symbol_trading_paused[symbol] = False
                                   self.logger.info(f"Market data for {symbol} is no longer stale. Resuming trading for symbol.")


                # --- Strategy Evaluation & Signal Generation (Per Symbol) ---
                for symbol in self.settings.TRADE_INSTRUMENTS:
                    if not self.running: break

                    # --- Check Pause Conditions (Market Hours, Staleness, Subscription Issues, etc.) ---
                    # The stale check above updates self.symbol_trading_paused
                    if self.check_pause_conditions(symbol):
                         continue # Skip evaluation if paused for any reason

                    # --- Update Regime Detection Periodically ---
                    regime_update_interval = timedelta(seconds=self.settings.MARKET_REGIME_UPDATE_INTERVAL_SECONDS)
                    if current_time_utc - self.last_regime_check_time[symbol] > regime_update_interval:
                         market_data_df = self.get_market_data(symbol)
                         if market_data_df is not None and len(market_data_df) >= self.regime_detector.min_data_points:
                              self.regime_detector.detect_regime(symbol, market_data_df)
                              self.last_regime_check_time[symbol] = current_time_utc

                    # --- Evaluate ---
                    market_data_df = self.get_market_data(symbol)
                    if market_data_df is None or len(market_data_df) < self.min_data_points_global:
                         continue

                    # --- Risk Manager Global Halt Check ---
                    if self.risk_manager.is_trading_halted():
                         if symbol == self.settings.TRADE_INSTRUMENTS[0]: # Log once per cycle
                              self.logger.warning(f"Skipping evaluations: Trading halted ({self.risk_manager.get_halt_reason()}).")
                         continue

                    # --- Calculate ATR ---
                    current_atr = None
                    if self.settings.ENABLE_ADAPTIVE_RISK or 'ATR' in self.settings.STOP_LOSS_TYPE or 'ATR' in self.settings.TAKE_PROFIT_TYPE:
                         if len(market_data_df) >= self.settings.ATR_PERIOD + 1:
                             try:
                                  atr_series = calculate_atr(market_data_df, period=self.settings.ATR_PERIOD)
                                  latest_atr_val = atr_series.iloc[-1]
                                  if pd.notna(latest_atr_val) and latest_atr_val > self.settings.MIN_ATR_VALUE:
                                       current_atr = latest_atr_val
                                       with self._lock: self.latest_atr[symbol] = current_atr
                                  else:
                                       with self._lock: current_atr = self.latest_atr.get(symbol)
                             except Exception as e:
                                  self.error_logger.error(f"Error calculating ATR for {symbol}: {e}")
                                  with self._lock: current_atr = self.latest_atr.get(symbol)

                    # --- Get Aggregated Signal ---
                    final_signal, individual_signals = self.strategy_manager.aggregate_signals(symbol, market_data_df.copy())

                    # --- Trade Execution Logic ---
                    if final_signal != 0:
                         self.attempt_trade_execution(symbol, final_signal, individual_signals, current_atr)


                # --- Update Status Display ---
                now_local_str = current_time_utc.astimezone(DEFAULT_TZ).strftime('%H:%M:%S')
                equity = self.portfolio_manager.get_total_equity()
                daily_pnl = self.portfolio_manager.get_daily_pnl()
                drawdown = self.portfolio_manager.get_current_drawdown()
                halt_status = f"HALTED ({self.risk_manager.get_halt_reason()})" if self.risk_manager.is_trading_halted() else "Running"
                conn_status = self.api.connection_status
                retrain_active = self._retrain_future and not self._retrain_future.done()
                retrain_status = "Retraining ML..." if retrain_active else ""
                cache_size = sys.getsizeof(self.market_data) / (1024*1024) # Approx MB

                status_line = (f"\r[{now_local_str} {DEFAULT_TZ.zone}] Eq:{equity:,.2f} | "
                               f"DD:{drawdown:.1%} | DailyPnL:{daily_pnl:,.2f} | Conn:{conn_status} | Status:{halt_status} {retrain_status} "
                               f"Cache:{cache_size:.1f}MB {spinner[idx%len(spinner)]} ")
                print(status_line, end="", flush=True)
                idx += 1

                # --- Main loop sleep ---
                loop_end_time = time.monotonic()
                loop_duration = loop_end_time - loop_start_time
                target_loop_time = 0.1
                sleep_time = max(0, target_loop_time - loop_duration)
                time.sleep(sleep_time)

            except KeyboardInterrupt:
                self.logger.warning("KeyboardInterrupt received. Initiating stop.")
                self.stop(reason="Keyboard Interrupt")
                break
            except Exception as e:
                self.error_logger.critical(f"CRITICAL ERROR in main loop: {e}", exc_info=True)
                self.stop(reason=f"Critical Error in Main Loop: {e}")
                break

        print() # Newline after spinner stops
        self.logger.info("Main trading loop finished.")


    def get_market_data(self, symbol):
        """Safely retrieves a copy of market data DataFrame with UTC DatetimeIndex."""
        with self._lock: # Protect market_data access
            df = self.market_data.get(symbol)
            if df is not None:
                df_copy = df.copy()
                if not isinstance(df_copy.index, pd.DatetimeIndex) or df_copy.index.tz is None:
                    try: df_copy = df_copy.set_index(pd.to_datetime(df_copy.index, utc=True))
                    except Exception: return None # Return None if index correction fails
                return df_copy
            else:
                return None

    def get_latest_price(self, symbol):
         """Gets the latest close price from portfolio manager cache or market data."""
         price = self.portfolio_manager.get_latest_price(symbol)
         if price: return price

         market_data_df = self.get_market_data(symbol)
         if market_data_df is not None and not market_data_df.empty:
             last_close = market_data_df['close'].iloc[-1]
             if pd.notna(last_close) and last_close > 0: return last_close
         return None

    def get_position_size(self, symbol):
         """ Gets current position size from Portfolio Manager. """
         return self.portfolio_manager.get_position_size(symbol)


    def attempt_trade_execution(self, symbol, signal, strategy_signals, current_atr):
        """Handles trade execution logic, including adaptive risk sizing if enabled."""
        latest_price = self.get_latest_price(symbol)
        if latest_price is None:
            self.error_logger.error(f"Cannot execute trade for {symbol}: Failed to get latest valid price.")
            return

        min_tick = get_min_tick(symbol, self.api)
        min_trade_size = get_min_trade_size(symbol, self.api)
        if min_tick is None or min_trade_size is None:
             self.error_logger.error(f"Cannot execute trade for {symbol}: Failed to get min_tick/min_trade_size.")
             return

        current_position = self.get_position_size(symbol)
        action = 'BUY' if signal == 1 else 'SELL' if signal == -1 else None
        if action is None: return

        is_closing_trade = (action == 'SELL' and current_position > 0) or (action == 'BUY' and current_position < 0)
        is_opening_trade = np.isclose(current_position, 0.0, atol=min_trade_size / 2) # Use isclose
        is_reversing_trade = (action == 'BUY' and current_position < 0) or (action == 'SELL' and current_position > 0)

        quantity = 0.0
        if is_closing_trade or is_reversing_trade:
             quantity = abs(current_position)
             if quantity < min_trade_size:
                  self.logger.warning(f"Attempting to close small position ({quantity:.6f}) for {symbol}, less than min size {min_trade_size}. Skipping closure signal.")
                  return
             self.logger.info(f"Signal to close/reverse {symbol}. Action: {action}, Qty: {quantity:.6f}")
        elif is_opening_trade:
             total_equity = self.portfolio_manager.get_total_equity()
             if total_equity <= 0:
                  self.logger.error(f"Cannot size trade for {symbol}: Zero/negative equity ({total_equity:.2f}).")
                  return

             vol_level = 'Normal'; vol_multiplier = 1.0
             if self.settings.AUTONOMOUS_MODE and self.settings.ENABLE_ADAPTIVE_RISK:
                  vol_level = self.regime_detector.get_volatility_level(symbol)
                  vol_multiplier = self.settings.ADAPTIVE_SL_TP_VOLATILITY_MAP.get(vol_level, 1.0)

             stop_loss_price_calc = 0.0; risk_per_unit = 0.0
             base_sl_atr_multiplier = self.settings.STOP_LOSS_ATR_MULTIPLIER

             if self.settings.STOP_LOSS_TYPE == 'PERCENT':
                 stop_loss_pct = self.settings.STOP_LOSS_PERCENT
                 sl_delta = latest_price * stop_loss_pct
                 stop_loss_price_calc = latest_price - sl_delta if action == 'BUY' else latest_price + sl_delta
                 risk_per_unit = sl_delta
             elif self.settings.STOP_LOSS_TYPE == 'ATR':
                 if current_atr is None or current_atr <= self.settings.MIN_ATR_VALUE:
                      self.logger.error(f"Cannot size trade for {symbol}: Valid ATR ({current_atr}) needed for ATR Stop Loss.")
                      return
                 effective_sl_atr_multiplier = base_sl_atr_multiplier * vol_multiplier
                 sl_delta = effective_sl_atr_multiplier * current_atr
                 stop_loss_price_calc = latest_price - sl_delta if action == 'BUY' else latest_price + sl_delta
                 risk_per_unit = sl_delta
             else:
                 self.logger.error(f"Invalid STOP_LOSS_TYPE: {self.settings.STOP_LOSS_TYPE}")
                 return

             stop_loss_price_calc = round_price(stop_loss_price_calc, min_tick)
             if action == 'BUY' and stop_loss_price_calc >= latest_price: stop_loss_price_calc = round_price(latest_price - min_tick, min_tick)
             elif action == 'SELL' and stop_loss_price_calc <= latest_price: stop_loss_price_calc = round_price(latest_price + min_tick, min_tick)
             risk_per_unit = abs(latest_price - stop_loss_price_calc)

             min_risk_per_unit = max(min_tick, latest_price * self.settings.MIN_RISK_PER_UNIT_FACTOR)
             if risk_per_unit < min_risk_per_unit: risk_per_unit = min_risk_per_unit
             if risk_per_unit <= 1e-9:
                 self.logger.error(f"Risk per unit is zero/negative for {symbol}. Cannot size trade.")
                 return

             risk_capital_amount = total_equity * self.settings.RISK_PER_TRADE
             available_funds = self.portfolio_manager.get_available_funds()
             estimated_commission = self.settings.ESTIMATED_COMMISSION_PER_SHARE
             estimated_slippage = self.settings.ESTIMATED_SLIPPAGE_PER_SHARE

             quantity = calculate_position_size(
                 entry_price=latest_price, stop_loss_price=stop_loss_price_calc,
                 risk_amount=risk_capital_amount, available_funds=available_funds, symbol=symbol,
                 min_trade_size=min_trade_size, min_tick=min_tick, api=self.api,
                 commission_per_unit=estimated_commission, slippage_per_unit=estimated_slippage
             )

             if quantity > 0:
                  effective_sl_atr_mult_str = f"{base_sl_atr_multiplier * vol_multiplier:.2f}" if self.settings.STOP_LOSS_TYPE == 'ATR' else "N/A"
                  self.logger.info(f"Signal to open {action} position for {symbol}. Calc Qty: {quantity:.6f} (Vol: {vol_level}, SL ATR Mult: {effective_sl_atr_mult_str})")
             else:
                 self.logger.warning(f"Calculated quantity is zero/negative for {symbol} ({quantity:.6f}). Skipping trade.")
                 return
        else:
            self.logger.debug(f"Ignoring signal for {symbol}: Not opening/closing/reversing based on current position ({current_position}).")
            return

        if quantity < min_trade_size:
             self.logger.warning(f"Attempting {action} for {symbol} failed: Final quantity {quantity:.8f} is less than min trade size {min_trade_size:.8f}.")
             return

        quantity = round_quantity(quantity, min_trade_size)
        if quantity <= 0:
             self.logger.warning(f"Attempting {action} for {symbol} failed: Quantity became zero after rounding to min size increment {min_trade_size:.8f}.")
             return

        available_funds = self.portfolio_manager.get_available_funds()
        if not self.risk_manager.check_pre_trade_risk(symbol, action, quantity, latest_price, available_funds):
             self.logger.warning(f"Trade for {symbol} ({action} {quantity}) failed pre-trade risk checks.")
             return

        place_sl, place_tp, sl_distance, tp_distance = 0.0, 0.0, 0.0, 0.0
        vol_level = 'Normal'; vol_multiplier = 1.0
        if self.settings.AUTONOMOUS_MODE and self.settings.ENABLE_ADAPTIVE_RISK:
             vol_level = self.regime_detector.get_volatility_level(symbol)
             vol_multiplier = self.settings.ADAPTIVE_SL_TP_VOLATILITY_MAP.get(vol_level, 1.0)

        if self.settings.STOP_LOSS_TYPE == 'PERCENT':
             sl_percent = self.settings.STOP_LOSS_PERCENT
             sl_distance = latest_price * sl_percent
             place_sl = latest_price - sl_distance if action == 'BUY' else latest_price + sl_distance
        elif self.settings.STOP_LOSS_TYPE == 'ATR':
             if current_atr is None or current_atr <= self.settings.MIN_ATR_VALUE:
                  self.error_logger.error(f"Cannot place trade {symbol}: Valid ATR needed for SL price ({current_atr})."); return
             effective_sl_atr_multiplier = self.settings.STOP_LOSS_ATR_MULTIPLIER * vol_multiplier
             sl_distance = effective_sl_atr_multiplier * current_atr
             place_sl = latest_price - sl_distance if action == 'BUY' else latest_price + sl_distance
        sl_distance = max(sl_distance, min_tick) # Ensure min distance

        if self.settings.TAKE_PROFIT_TYPE == 'PERCENT':
             tp_percent = self.settings.TAKE_PROFIT_PERCENT
             tp_distance = latest_price * tp_percent
             place_tp = latest_price + tp_distance if action == 'BUY' else latest_price - tp_distance
        elif self.settings.TAKE_PROFIT_TYPE == 'ATR':
             if current_atr is None or current_atr <= self.settings.MIN_ATR_VALUE:
                  self.error_logger.error(f"Cannot place trade {symbol}: Valid ATR needed for TP price ({current_atr})."); return
             effective_tp_atr_multiplier = self.settings.TAKE_PROFIT_ATR_MULTIPLIER * vol_multiplier
             tp_distance = effective_tp_atr_multiplier * current_atr
             place_tp = latest_price + tp_distance if action == 'BUY' else latest_price - tp_distance
        elif self.settings.TAKE_PROFIT_TYPE == 'RATIO':
             effective_rr_ratio = self.settings.TAKE_PROFIT_RR_RATIO * vol_multiplier
             tp_distance = effective_rr_ratio * sl_distance
             place_tp = latest_price + tp_distance if action == 'BUY' else latest_price - tp_distance
        else: self.logger.error(f"Invalid TAKE_PROFIT_TYPE."); return
        tp_distance = max(tp_distance, min_tick) # Ensure min distance

        place_sl = round_price(place_sl, min_tick)
        place_tp = round_price(place_tp, min_tick)

        if action == 'BUY':
             place_sl = min(place_sl, round_price(latest_price - min_tick, min_tick))
             place_tp = max(place_tp, round_price(latest_price + min_tick, min_tick))
             if place_sl >= place_tp: self.logger.error(f"Invalid SL/TP for BUY {symbol}: SL ({place_sl:.5f}) >= TP ({place_tp:.5f}). Cannot place trade."); return
        else: # SELL
             place_sl = max(place_sl, round_price(latest_price + min_tick, min_tick))
             place_tp = min(place_tp, round_price(latest_price - min_tick, min_tick))
             if place_sl <= place_tp: self.logger.error(f"Invalid SL/TP for SELL {symbol}: SL ({place_sl:.5f}) <= TP ({place_tp:.5f}). Cannot place trade."); return

        strategy_name_log = ",".join([name for name, sig in strategy_signals.items() if sig != 0]) or "Aggregated"
        log_price_precision = max(5, len(str(min_tick).split('.')[-1]) if '.' in str(min_tick) else 0)

        self.logger.info(
            f"Attempting {action} bracket order: {quantity:.8f} {symbol} "
            f"via {strategy_name_log} (Entry ~{latest_price:.{log_price_precision}f}, "
            f"SL: {place_sl:.{log_price_precision}f}, TP: {place_tp:.{log_price_precision}f}, "
            f"Vol: {vol_level})"
        )

        parent_id, stop_id, profit_id = self.order_manager.create_and_place_bracket_order(
            symbol=symbol, action=action, quantity=quantity, entry_price=latest_price,
            stop_loss_price=place_sl, take_profit_price=place_tp, strategy_name=strategy_name_log
        )

        if parent_id:
             self.trade_logger.info(f"Successfully submitted bracket order for {symbol}. ParentID: {parent_id}, SL: {stop_id}, TP: {profit_id}")
        else:
             self.error_logger.error(f"Failed to submit bracket order for {symbol}.")


def parse_args():
    """Parse command-line arguments for headless operation."""
    parser = argparse.ArgumentParser(
        description='AIStocker: Automated trading system for Interactive Brokers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Interactive mode (prompts for config)
  python main.py

  # Headless mode with defaults
  python main.py --headless --mode crypto --instruments "BTC/USD,ETH/USD"

  # Train ML model
  python main.py --train

  # Headless with all options
  python main.py --headless --mode stock --instruments "AAPL,MSFT" --no-autonomous --extended-hours
        '''
    )
    parser.add_argument('--headless', action='store_true',
                        help='Run in headless mode (no interactive prompts)')
    parser.add_argument('--train', action='store_true',
                        help='Train ML model and exit')
    parser.add_argument('--mode', type=str, choices=['stock', 'crypto', 'forex'],
                        help='Trading mode (stock, crypto, forex)')
    parser.add_argument('--instruments', type=str,
                        help='Comma-separated list of instruments (e.g., "BTC/USD,ETH/USD")')
    parser.add_argument('--autonomous', dest='autonomous', action='store_true', default=True,
                        help='Enable autonomous mode (default: True)')
    parser.add_argument('--no-autonomous', dest='autonomous', action='store_false',
                        help='Disable autonomous mode')
    parser.add_argument('--adaptive-risk', dest='adaptive_risk', action='store_true', default=True,
                        help='Enable adaptive risk (default: True if autonomous)')
    parser.add_argument('--no-adaptive-risk', dest='adaptive_risk', action='store_false',
                        help='Disable adaptive risk')
    parser.add_argument('--auto-retrain', dest='auto_retrain', action='store_true', default=True,
                        help='Enable auto ML retraining (default: True if autonomous)')
    parser.add_argument('--no-auto-retrain', dest='auto_retrain', action='store_false',
                        help='Disable auto ML retraining')
    parser.add_argument('--dynamic-weighting', dest='dynamic_weighting', action='store_true', default=True,
                        help='Enable dynamic strategy weighting (default: True if autonomous)')
    parser.add_argument('--no-dynamic-weighting', dest='dynamic_weighting', action='store_false',
                        help='Disable dynamic strategy weighting')
    parser.add_argument('--extended-hours', dest='extended_hours', action='store_true', default=False,
                        help='Allow trading in extended hours (stock mode only)')
    return parser.parse_args()


# --- Main Execution ---
if __name__ == "__main__":
    bot = None
    # Setup basic logging for the main block itself
    startup_logger = setup_logger('AIStockerMain', 'logs/app.log', level='INFO')
    startup_error_logger = setup_logger('AIStockerMainError', 'logs/error_logs/errors.log', level='ERROR')
    # --- Essential Check: Ensure `config` directory and `credentials.py` exist ---
    config_dir = os.path.join(project_root, 'config')
    creds_file = os.path.join(config_dir, 'credentials.py')
    if not os.path.isdir(config_dir) or not os.path.isfile(creds_file):
        msg = "CRITICAL: 'config' directory or 'config/credentials.py' not found. Please create them. Exiting."
        startup_error_logger.critical(msg)
        print(msg)
        sys.exit(1)
    # --- Essential Check: Ensure logs directory is writable ---
    logs_dir = os.path.join(project_root, 'logs')
    try:
        os.makedirs(logs_dir, exist_ok=True)
        test_file = os.path.join(logs_dir, 'startup_test.log')
        with open(test_file, 'w') as f: f.write('test')
        os.remove(test_file)
    except Exception as e:
        msg = f"CRITICAL: Cannot write to logs directory '{logs_dir}'. Check permissions. Error: {e}. Exiting."
        startup_error_logger.critical(msg)
        print(msg)
        sys.exit(1)

    # Parse CLI arguments
    args = parse_args()

    try:
        # Check if training mode requested
        if args.train:
            print("\nStarting ML Model Training...")
            startup_logger.info("Training mode requested via CLI")
            try:
                os.makedirs('logs/error_logs', exist_ok=True); os.makedirs('logs', exist_ok=True)
                os.makedirs('models', exist_ok=True); os.makedirs('data/historical_data', exist_ok=True)
                success = train_model_main()
                if success: print("\n--- Training Task Completed Successfully ---")
                else: print("\n--- Training Task Failed ---")
                startup_logger.info(f"ML Model Training finished (Success: {success}).")
                sys.exit(0 if success else 1)
            except Exception as e:
                print(f"\nAn error occurred during training: {e}")
                startup_error_logger.critical(f"Training failed: {e}", exc_info=True)
                sys.exit(1)

        # Check if headless mode
        if args.headless:
            print("\nLaunching Trading Bot in headless mode...")
            startup_logger.info("Launching bot in headless mode")
            # Validate required args for headless
            if not args.mode:
                print("ERROR: --mode is required in headless mode")
                sys.exit(1)
            bot = TradingBot()
            # Pass args to prompt_user_config for headless configuration
            if not bot.prompt_user_config(args):
                startup_logger.critical("Bot configuration failed in headless mode. Exiting.")
                sys.exit(1)
            bot.start()

            # Keep main thread alive while bot runs
            while bot and bot.running:
                alive = True
                if bot.main_thread and not bot.main_thread.is_alive():
                    startup_error_logger.error("Main trading loop thread died unexpectedly.")
                    alive = False
                if bot.api and bot.api.api_thread and not bot.api.api_thread.is_alive() and bot.api.is_connected():
                    startup_error_logger.error("IBKR API message loop thread died unexpectedly while connected.")
                    alive = False
                if hasattr(bot, 'data_aggregator') and bot.data_aggregator.thread and \
                   not bot.data_aggregator.thread.is_alive() and bot.data_aggregator.running:
                    startup_error_logger.error("Data Aggregator thread died unexpectedly while running.")
                    alive = False
                if not alive and bot.running:
                    startup_error_logger.critical("A critical background thread died. Forcing bot stop.")
                    bot.stop(reason="A background thread died")
                time.sleep(2)

            print("\nBot execution finished or stopped.")
            startup_logger.info("Trading Bot execution finished.")
            sys.exit(0)

        # Interactive mode (original behavior)
        print("\n" + "="*30 + "\n   AIStocker Options\n" + "="*30)
        print(" 1. Launch Trading Bot")
        print(" 2. Train ML Model")
        print(" 3. Exit")
        choice = input(" Enter your choice [1, 2, or 3]: ").strip()

        if choice == '1':
            print("\nLaunching Trading Bot...")
            startup_logger.info("User selected: Launch Trading Bot")
            bot = TradingBot() # Initialization happens here
            bot.start() # Start the bot's operation

            # Keep main thread alive while bot runs, monitor background threads
            while bot and bot.running:
                alive = True
                # Check main trading loop thread
                if bot.main_thread and not bot.main_thread.is_alive():
                     startup_error_logger.error("Main trading loop thread died unexpectedly.")
                     alive = False
                # Check API message loop thread
                # Use bot.api.is_connected() which includes the internal flag check
                if bot.api and bot.api.api_thread and not bot.api.api_thread.is_alive() and bot.api.is_connected():
                     startup_error_logger.error("IBKR API message loop thread died unexpectedly while connected.")
                     alive = False
                # Check Data Aggregator thread
                if hasattr(bot, 'data_aggregator') and bot.data_aggregator.thread and \
                   not bot.data_aggregator.thread.is_alive() and bot.data_aggregator.running:
                     startup_error_logger.error("Data Aggregator thread died unexpectedly while running.")
                     alive = False

                if not alive and bot.running:
                    startup_error_logger.critical("A critical background thread died. Forcing bot stop.")
                    bot.stop(reason="A background thread died")

                time.sleep(2) # Check every 2 seconds

            print("\nBot execution finished or stopped.")
            startup_logger.info("Trading Bot execution finished.")

        elif choice == '2':
             print("\nStarting ML Model Training...")
             startup_logger.info("User selected: Train ML Model")
             try:
                 os.makedirs('logs/error_logs', exist_ok=True); os.makedirs('logs', exist_ok=True)
                 os.makedirs('models', exist_ok=True); os.makedirs('data/historical_data', exist_ok=True)
                 success = train_model_main()
                 if success: print("\n--- Training Task Completed Successfully ---")
                 else: print("\n--- Training Task Failed ---")
                 startup_logger.info(f"ML Model Training finished (Success: {success}).")
             except Exception as e:
                 print(f"\nAn error occurred during training: {e}")
                 startup_error_logger.critical(f"Training failed: {e}", exc_info=True)
                 sys.exit(1)

        elif choice == '3':
            print("Exiting.")
            startup_logger.info("User selected: Exit")
        else:
            print("Invalid choice. Exiting.")
            startup_logger.warning(f"Invalid startup choice: {choice}")

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Stopping bot...")
        startup_logger.warning("KeyboardInterrupt received. Initiating shutdown.")
        if bot and bot.running: bot.stop(reason="Keyboard Interrupt")
        elif bot:
             if hasattr(bot, 'api') and bot.api.is_connected(): bot.api.disconnect_app()
        print("Exiting.")
    except Exception as e:
         print(f"\nA critical unhandled error occurred: {e}. Check error logs. Forcing exit.")
         logger_to_use = startup_error_logger if 'startup_error_logger' in locals() else setup_logger('main_critical', 'logs/error_logs/errors.log', level='CRITICAL')
         logger_to_use.critical(f"Unhandled exception in main execution block: {e}", exc_info=True)
         if bot and bot.running: bot.stop(reason="Critical Error")
         elif bot:
             if hasattr(bot, 'api') and bot.api.is_connected(): bot.api.disconnect_app()
         sys.exit(1)
    finally:
         if 'logging' in sys.modules:
             logging.shutdown()