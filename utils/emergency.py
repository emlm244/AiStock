# utils/emergency.py

"""
Emergency Shutdown and Recovery Procedures

Provides safe emergency shutdown procedures and recovery mechanisms
to protect capital and ensure system integrity during critical failures.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

import pytz


class EmergencyShutdownHandler:
    """Handles emergency shutdown procedures"""

    REASON_CRITICAL_ERROR = 'CRITICAL_ERROR'
    REASON_DATA_INTEGRITY = 'DATA_INTEGRITY_FAILURE'
    REASON_RISK_BREACH = 'RISK_LIMIT_BREACH'
    REASON_API_FAILURE = 'API_CONNECTION_FAILURE'
    REASON_USER_ABORT = 'USER_ABORT'
    REASON_SYSTEM_FAILURE = 'SYSTEM_FAILURE'

    def __init__(self, logger=None):
        self.logger = logger
        self.shutdown_in_progress = False
        self._shutdown_lock = threading.Lock()
        self.shutdown_log_file = 'logs/emergency_shutdowns.log'

    def execute_emergency_shutdown(
        self, trading_bot, reason: str, details: str = '', cancel_orders: bool = True, save_state: bool = True
    ) -> bool:
        """
        Execute emergency shutdown procedure

        Args:
            trading_bot: TradingBot instance
            reason: Shutdown reason code
            details: Additional details about the shutdown
            cancel_orders: Whether to cancel all open orders
            save_state: Whether to save final state

        Returns:
            True if shutdown completed successfully
        """
        with self._shutdown_lock:
            if self.shutdown_in_progress:
                if self.logger:
                    self.logger.warning('Emergency shutdown already in progress')
                return False

            self.shutdown_in_progress = True

        try:
            if self.logger:
                self.logger.critical(f'🚨 EMERGENCY SHUTDOWN INITIATED - Reason: {reason}')
                if details:
                    self.logger.critical(f'Details: {details}')

            # Log shutdown event
            self._log_shutdown_event(reason, details)

            # Display user notification
            self._display_emergency_message(reason, details)

            # Execute shutdown steps
            success = self._execute_shutdown_steps(trading_bot, cancel_orders=cancel_orders, save_state=save_state)

            if success:
                if self.logger:
                    self.logger.info('✓ Emergency shutdown completed successfully')
                print('\n✓ Emergency shutdown completed successfully.\n')
            else:
                if self.logger:
                    self.logger.error('✗ Emergency shutdown completed with errors')
                print('\n✗ Emergency shutdown completed with errors. Check logs.\n')

            return success

        except Exception as e:
            if self.logger:
                self.logger.critical(f'Exception during emergency shutdown: {e}', exc_info=True)
            print(f'\n✗ CRITICAL: Exception during emergency shutdown: {e}\n')
            return False
        finally:
            self.shutdown_in_progress = False

    def _execute_shutdown_steps(self, trading_bot, cancel_orders: bool, save_state: bool) -> bool:
        """Execute the actual shutdown steps"""
        success = True

        # Step 1: Stop main loop
        if self.logger:
            self.logger.info('Step 1/5: Stopping main trading loop...')
        print('Step 1/5: Stopping main trading loop...')

        try:
            trading_bot.running = False
        except Exception as e:
            if self.logger:
                self.logger.error(f'Error stopping main loop: {e}')
            success = False

        # Step 2: Stop data aggregator
        if self.logger:
            self.logger.info('Step 2/5: Stopping data aggregator...')
        print('Step 2/5: Stopping data aggregator...')

        try:
            if hasattr(trading_bot, 'data_aggregator') and trading_bot.data_aggregator:
                trading_bot.data_aggregator.stop()
        except Exception as e:
            if self.logger:
                self.logger.error(f'Error stopping data aggregator: {e}')
            success = False

        # Step 3: Cancel orders if requested
        if cancel_orders:
            if self.logger:
                self.logger.info('Step 3/5: Cancelling all open orders...')
            print('Step 3/5: Cancelling all open orders...')

            try:
                if hasattr(trading_bot, 'order_manager') and trading_bot.order_manager:
                    if hasattr(trading_bot, 'api') and trading_bot.api.is_connected():
                        open_ids = trading_bot.order_manager.get_open_order_ids()
                        if open_ids:
                            for order_id in open_ids:
                                trading_bot.order_manager.cancel_order(order_id)
                                import time

                                time.sleep(0.1)  # Pacing
                            if self.logger:
                                self.logger.info(f'Cancelled {len(open_ids)} orders')
                        else:
                            if self.logger:
                                self.logger.info('No open orders to cancel')
                    else:
                        if self.logger:
                            self.logger.warning('Cannot cancel orders: API not connected')
            except Exception as e:
                if self.logger:
                    self.logger.error(f'Error cancelling orders: {e}')
                success = False
        else:
            print('Step 3/5: Skipping order cancellation (as requested)...')

        # Step 4: Save state if requested
        if save_state:
            if self.logger:
                self.logger.info('Step 4/5: Saving final state...')
            print('Step 4/5: Saving final state...')

            try:
                if hasattr(trading_bot, 'state_manager') and trading_bot.state_manager:
                    trading_bot.state_manager.save_state()
                    if self.logger:
                        self.logger.info('Final state saved successfully')
            except Exception as e:
                if self.logger:
                    self.logger.error(f'Error saving state: {e}')
                success = False
        else:
            print('Step 4/5: Skipping state save (as requested)...')

        # Step 5: Disconnect API
        if self.logger:
            self.logger.info('Step 5/5: Disconnecting from API...')
        print('Step 5/5: Disconnecting from API...')

        try:
            if hasattr(trading_bot, 'api') and trading_bot.api and trading_bot.api.is_connected():
                trading_bot.api.disconnect_app()
                if self.logger:
                    self.logger.info('API disconnected successfully')
        except Exception as e:
            if self.logger:
                self.logger.error(f'Error disconnecting API: {e}')
            success = False

        return success

    def _display_emergency_message(self, reason: str, details: str):
        """Display emergency shutdown message to user"""
        print('\n' + '=' * 70)
        print(' 🚨 EMERGENCY SHUTDOWN 🚨')
        print('=' * 70)
        print(f'\nReason: {reason}')
        if details:
            print(f'Details: {details}')
        print(f'\nTimestamp: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print('\nThe system is performing a safe shutdown to protect your capital.')
        print('Please wait while shutdown procedures complete...')
        print('\n' + '=' * 70 + '\n')

    def _log_shutdown_event(self, reason: str, details: str):
        """Log shutdown event to emergency log file"""
        try:
            # Ensure log directory exists
            log_dir = Path(self.shutdown_log_file).parent
            log_dir.mkdir(parents=True, exist_ok=True)

            # Create log entry
            log_entry = {
                'timestamp': datetime.now(pytz.utc).isoformat(),
                'reason': reason,
                'details': details,
            }

            # Append to log file
            with open(self.shutdown_log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

        except Exception as e:
            if self.logger:
                self.logger.error(f'Failed to log shutdown event: {e}')


class RecoveryManager:
    """Manages system recovery after shutdown"""

    def __init__(self, logger=None):
        self.logger = logger
        self.recovery_log_file = 'logs/recovery.log'

    def check_recovery_needed(self, state_manager) -> tuple[bool, str]:
        """
        Check if system needs recovery

        Returns:
            (needs_recovery, reason)
        """
        # Check for emergency shutdown log
        emergency_log = Path('logs/emergency_shutdowns.log')
        if emergency_log.exists():
            try:
                with open(emergency_log) as f:
                    lines = f.readlines()
                    if lines:
                        last_shutdown = json.loads(lines[-1])
                        return True, f'Previous emergency shutdown: {last_shutdown.get("reason")}'
            except Exception as e:
                if self.logger:
                    self.logger.warning(f'Could not read emergency log: {e}')

        # Check state file timestamp
        if hasattr(state_manager, 'state_file'):
            state_file = Path(state_manager.state_file)
            if state_file.exists():
                mod_time = datetime.fromtimestamp(state_file.stat().st_mtime)
                age_hours = (datetime.now() - mod_time).total_seconds() / 3600

                # If state file is older than 24 hours, may need review
                if age_hours > 24:
                    return True, f'State file is {age_hours:.1f} hours old'

        return False, ''

    def perform_recovery_checks(self, trading_bot) -> tuple[bool, list[str]]:
        """
        Perform recovery checks before allowing restart

        Returns:
            (can_restart, list_of_issues)
        """
        issues = []

        # Check API connectivity
        if hasattr(trading_bot, 'api') and not trading_bot.api.is_connected():
            issues.append('API is not connected')

        # Check state integrity
        if hasattr(trading_bot, 'state_manager'):
            # Verify state file is readable
            try:
                state_file = Path(trading_bot.state_manager.state_file)
                if state_file.exists():
                    with open(state_file) as f:
                        json.load(f)  # Verify it's valid JSON
                else:
                    issues.append('State file does not exist')
            except json.JSONDecodeError:
                issues.append('State file is corrupted (invalid JSON)')
            except Exception as e:
                issues.append(f'Cannot read state file: {e}')

        # Check portfolio manager
        if hasattr(trading_bot, 'portfolio_manager'):
            pm = trading_bot.portfolio_manager
            equity = pm.get_total_equity()

            if equity <= 0:
                issues.append(f'Portfolio equity is {equity} (should be positive)')

        can_restart = len(issues) == 0
        return can_restart, issues

    def log_recovery_attempt(self, success: bool, issues: list[str] = None):
        """Log recovery attempt"""
        try:
            log_dir = Path(self.recovery_log_file).parent
            log_dir.mkdir(parents=True, exist_ok=True)

            log_entry = {
                'timestamp': datetime.now(pytz.utc).isoformat(),
                'success': success,
                'issues': issues or [],
            }

            with open(self.recovery_log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

        except Exception as e:
            if self.logger:
                self.logger.error(f'Failed to log recovery attempt: {e}')
