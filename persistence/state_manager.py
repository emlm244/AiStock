# persistence/state_manager.py
import json
import os
import threading
from datetime import datetime
import pytz # Use pytz for timezone handling

try:
    from utils.logger import setup_logger
    from config.settings import Settings
    from persistence.backup_manager import BackupManager
except ImportError as e:
    print(f"Error importing modules in StateManager: {e}")
    raise


class StateManager:
    """Handles saving and loading the bot's critical state in a thread-safe manner."""

    def __init__(self, order_manager, portfolio_manager, settings, state_file='data/bot_state.json', logger=None):
        self.order_manager = order_manager
        self.portfolio_manager = portfolio_manager
        self.settings = settings # May need settings for context or hashing
        self.logger = logger or setup_logger('StateManager', 'logs/app.log', level=settings.LOG_LEVEL)
        self.error_logger = setup_logger('StateError', 'logs/error_logs/errors.log', level='ERROR')
        self.state_file = state_file
        self._lock = threading.Lock() # Lock for file access and state modification

        # Initialize backup manager
        self.backup_manager = BackupManager(
            state_file_path=state_file,
            max_backups=10,
            logger=self.logger
        )

        # Ensure data directory exists
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        except OSError as e:
            self.error_logger.critical(f"Failed to create directory for state file {self.state_file}: {e}. State saving/loading will fail.")
            # Raise error? Or just log and continue knowing it won't work? Let's log.

    def save_state(self):
        """Gathers state from managers and saves it to a JSON file (thread-safe)."""
        with self._lock: # Acquire lock for the entire save operation
            try:
                self.logger.info(f"Attempting to save bot state to {self.state_file}...")
                # Gather state from components (these methods MUST be thread-safe)
                om_state = self.order_manager.get_state()
                pm_state = self.portfolio_manager.get_state()
                # TODO: Add state from StrategyManager/Optimizer if needed
                # strat_mgr_state = self.strategy_manager.get_state()

                state = {
                    # Use aware UTC timestamp in ISO format
                    'timestamp_utc': datetime.now(pytz.utc).isoformat(),
                    'order_manager': om_state,
                    'portfolio_manager': pm_state,
                    # 'strategy_manager': strat_mgr_state, # Example
                    'settings_hash': self._get_settings_hash() # Store hash of critical settings
                }

                # Write to file atomically (write to temp file, then rename)
                temp_file_path = self.state_file + ".tmp"
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    json.dump(state, f, indent=4, ensure_ascii=False)

                # Atomic rename (on most OS)
                os.replace(temp_file_path, self.state_file)

                # Create backup after successful save
                try:
                    backup_path = self.backup_manager.create_backup(reason="Scheduled state save")
                    if backup_path:
                        self.logger.debug(f"Backup created: {backup_path}")
                except Exception as backup_error:
                    self.error_logger.error(f"Backup creation failed: {backup_error}", exc_info=True)
                    # Don't fail the save operation due to backup failure

                self.logger.info(f"Bot state successfully saved to {self.state_file}")
                return True

            except AttributeError as ae:
                 self.error_logger.error(f"Failed to save state: Component missing 'get_state' method? {ae}", exc_info=True)
                 return False
            except Exception as e:
                self.error_logger.error(f"Failed to save bot state to {self.state_file}: {e}", exc_info=True)
                # Clean up temp file if it exists
                if os.path.exists(temp_file_path):
                     try: os.remove(temp_file_path)
                     except OSError: pass
                return False

    def load_state(self):
        """Loads state from the file and applies it to the managers (thread-safe)."""
        with self._lock: # Acquire lock for the entire load operation
            if not os.path.exists(self.state_file):
                self.logger.warning(f"State file {self.state_file} not found. Starting with default state.")
                return False # Indicate state was not loaded

            try:
                self.logger.info(f"Attempting to load bot state from {self.state_file}...")
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                # Optional: Check settings hash for compatibility
                saved_hash = state.get('settings_hash')
                current_hash = self._get_settings_hash()
                if saved_hash and saved_hash != current_hash:
                     self.logger.warning(
                        "!!! SETTINGS MISMATCH DETECTED !!! Saved state hash does not match current settings hash. "
                        "Loading state, but behavior may be unexpected due to configuration changes. Review settings and state file."
                     )
                elif not saved_hash:
                     self.logger.warning("Saved state file does not contain settings hash. Cannot verify compatibility.")

                # Load state into managers (these methods MUST be thread-safe)
                load_success = True
                if 'order_manager' in state:
                    try:
                        self.order_manager.load_state(state['order_manager'])
                    except Exception as om_e:
                         self.error_logger.error(f"Error loading OrderManager state: {om_e}", exc_info=True)
                         load_success = False
                else: self.logger.warning("No 'order_manager' state found in file.")

                if 'portfolio_manager' in state:
                     try:
                         self.portfolio_manager.load_state(state['portfolio_manager'])
                     except Exception as pm_e:
                          self.error_logger.error(f"Error loading PortfolioManager state: {pm_e}", exc_info=True)
                          load_success = False
                else: self.logger.warning("No 'portfolio_manager' state found in file.")

                # TODO: Load state for other components if added
                # if 'strategy_manager' in state:
                #     self.strategy_manager.load_state(state['strategy_manager'])

                if load_success:
                     load_time_str = state.get('timestamp_utc', 'Unknown Time')
                     self.logger.info(f"Bot state successfully loaded from {self.state_file} (Saved At: {load_time_str})")
                     return True # Indicate state was loaded successfully
                else:
                     self.error_logger.error(f"Partial or complete failure loading state from {self.state_file}. Bot may start with incorrect state.")
                     # Should we revert to fresh state? Or proceed with potentially partial load?
                     # Let's proceed but log critically.
                     return False # Indicate state load had issues

            except json.JSONDecodeError as jde:
                 self.error_logger.critical(f"Failed to decode JSON from state file {self.state_file}: {jde}. Starting fresh.", exc_info=True)
                 return False
            except Exception as e:
                self.error_logger.critical(f"Failed to load bot state from {self.state_file}: {e}. Starting fresh.", exc_info=True)
                return False # Indicate state was not loaded


    def _get_settings_hash(self):
         """ Generates a hash of critical settings for compatibility comparison. """
         # Select settings that, if changed, would make the loaded state potentially incompatible
         # Exclude dynamic state like capital, but include structural elements.
         try:
             import hashlib
             critical_params = {
                 'TIMEFRAME': self.settings.TIMEFRAME,
                 'TRADING_MODE': self.settings.TRADING_MODE,
                 'TRADE_INSTRUMENTS': sorted(self.settings.TRADE_INSTRUMENTS), # Sort list for consistent hash
                 'ENABLED_STRATEGIES': self.settings.ENABLED_STRATEGIES,
                 # Include risk structure settings
                 'RISK_PER_TRADE': self.settings.RISK_PER_TRADE,
                 'STOP_LOSS_TYPE': self.settings.STOP_LOSS_TYPE,
                 'TAKE_PROFIT_TYPE': self.settings.TAKE_PROFIT_TYPE,
                 'MAX_DAILY_LOSS': self.settings.MAX_DAILY_LOSS,
                 'MAX_DRAWDOWN_LIMIT': self.settings.MAX_DRAWDOWN_LIMIT,
                 # Add other critical structural settings here
             }
             # Convert dict to canonical string format (sort keys)
             params_str = json.dumps(critical_params, sort_keys=True)
             return hashlib.sha256(params_str.encode('utf-8')).hexdigest() # Use SHA256
         except Exception as e:
             self.error_logger.error(f"Could not generate settings hash: {e}", exc_info=True)
             return None