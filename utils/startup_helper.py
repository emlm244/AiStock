# utils/startup_helper.py

"""
Startup Helper - Production-Ready Bot Initialization

Provides comprehensive startup procedures with validation, diagnostics,
and beginner-friendly guidance.
"""

from utils.diagnostics import run_diagnostics
from utils.emergency import RecoveryManager
from utils.logger import setup_logger
from utils.validation import ConfigValidator


class StartupHelper:
    """Manages bot startup with comprehensive checks and user guidance"""

    def __init__(self):
        self.logger = setup_logger('StartupHelper', 'logs/app.log', level='INFO')
        self.startup_errors = []
        self.startup_warnings = []

    def perform_startup_sequence(self, settings, headless: bool = False) -> bool:
        """
        Execute complete startup sequence with all checks

        Args:
            settings: Settings object
            headless: Whether running in headless mode

        Returns:
            True if startup should proceed
        """
        print('\n' + '=' * 70)
        print(' 🚀 AIStocker Production Bot - Startup Sequence')
        print('=' * 70 + '\n')

        # Step 1: Recovery Check
        if not self._check_recovery_needed():
            return False

        # Step 2: Validate Configuration
        if not self._validate_configuration(settings):
            return False

        # Step 3: Run System Diagnostics
        if not self._run_diagnostics(settings):
            return False

        # Step 4: Display Startup Summary
        self._display_startup_summary(settings, headless)

        # Step 5: Confirmation (if interactive)
        if not headless and not self._get_user_confirmation():
            print('\nStartup cancelled by user.\n')
            return False

        print('\n✓ All startup checks passed. Launching bot...\n')
        return True

    def _check_recovery_needed(self) -> bool:
        """Check if system needs recovery from previous shutdown"""
        print('Step 1: Checking for recovery conditions...')

        recovery_manager = RecoveryManager(self.logger)

        # Create temporary state manager to check
        try:
            from persistence.state_manager import StateManager

            temp_state_mgr = StateManager(None, None, None, logger=self.logger)
        except Exception:
            # If can't create state manager, skip recovery check
            print('  ℹ️  No previous state found (first run)\n')
            return True

        needs_recovery, reason = recovery_manager.check_recovery_needed(temp_state_mgr)

        if needs_recovery:
            print(f'  ⚠️  Recovery condition detected: {reason}')
            print('\n' + '-' * 70)
            print(' RECOVERY INFORMATION')
            print('-' * 70)
            print(f'\n{reason}\n')
            print('The system detected a previous shutdown or recovery condition.')
            print('You can continue, but please review the details above.\n')

            response = input('Continue with startup? [Y/n]: ').strip().lower()
            if response and response not in ['y', 'yes']:
                print('\nStartup aborted.\n')
                return False

        print('  ✓ Recovery check passed\n')
        return True

    def _validate_configuration(self, settings) -> bool:
        """Validate all configuration settings"""
        print('Step 2: Validating configuration...')

        errors = ConfigValidator.validate_settings(settings)

        # Separate critical errors from warnings
        critical_errors = [e for e in errors if 'CRITICAL' in e.message or 'cannot' in e.message.lower()]
        warnings = [e for e in errors if e not in critical_errors]

        # Display warnings
        if warnings:
            print(f'\n  ⚠️  Configuration Warnings ({len(warnings)}):')
            for warning in warnings:
                print(f'\n{warning.format_message()}')

        # Display critical errors
        if critical_errors:
            print(f'\n  ✗ Configuration Errors ({len(critical_errors)}):')
            for error in critical_errors:
                print(f'\n{error.format_message()}')
            print('\n' + '=' * 70)
            print(' ✗ STARTUP FAILED - Configuration Issues')
            print('=' * 70)
            print('\nPlease fix the configuration errors above before starting the bot.')
            print('Refer to CLAUDE.md for configuration guidance.\n')
            return False

        print('  ✓ Configuration validation passed\n')
        return True

    def _run_diagnostics(self, settings) -> bool:
        """Run comprehensive system diagnostics"""
        print('Step 3: Running system diagnostics...\n')

        # Run diagnostics
        all_passed = run_diagnostics(settings, self.logger)

        if not all_passed:
            print('\n' + '=' * 70)
            print(' ✗ STARTUP FAILED - System Diagnostics')
            print('=' * 70)
            print('\nPlease fix the issues above before starting the bot.\n')
            return False

        return True

    def _display_startup_summary(self, settings, headless: bool):
        """Display summary of bot configuration"""
        print('\n' + '=' * 70)
        print(' 📋 STARTUP CONFIGURATION SUMMARY')
        print('=' * 70 + '\n')

        # Trading Configuration
        print('Trading Configuration:')
        print(f'  • Mode: {settings.TRADING_MODE.upper()}')
        print(f'  • Instruments: {", ".join(settings.TRADE_INSTRUMENTS)}')
        print(f'  • Timeframe: {settings.TIMEFRAME}')
        print(f'  • Autonomous Mode: {"✓ Enabled" if settings.AUTONOMOUS_MODE else "✗ Disabled"}')

        # Risk Configuration
        print('\nRisk Management:')
        print(f'  • Risk Per Trade: {settings.RISK_PER_TRADE:.2%}')
        print(f'  • Max Daily Loss: {settings.MAX_DAILY_LOSS:.2%}')
        print(f'  • Max Drawdown: {settings.MAX_DRAWDOWN_LIMIT:.2%}')

        # Stop Loss / Take Profit
        print('\nStop Loss / Take Profit:')
        print(f'  • SL Type: {settings.STOP_LOSS_TYPE}')
        if settings.STOP_LOSS_TYPE == 'PERCENT':
            print(f'    - Distance: {settings.STOP_LOSS_PERCENT:.2%}')
        elif settings.STOP_LOSS_TYPE == 'ATR':
            print(f'    - ATR Multiplier: {settings.STOP_LOSS_ATR_MULTIPLIER}x')

        print(f'  • TP Type: {settings.TAKE_PROFIT_TYPE}')
        if settings.TAKE_PROFIT_TYPE == 'PERCENT':
            print(f'    - Distance: {settings.TAKE_PROFIT_PERCENT:.2%}')
        elif settings.TAKE_PROFIT_TYPE == 'ATR':
            print(f'    - ATR Multiplier: {settings.TAKE_PROFIT_ATR_MULTIPLIER}x')
        elif settings.TAKE_PROFIT_TYPE == 'RATIO':
            print(f'    - Risk/Reward Ratio: {settings.TAKE_PROFIT_RR_RATIO}:1')

        # Advanced Features
        if settings.AUTONOMOUS_MODE:
            print('\nAutonomous Features:')
            if settings.ENABLE_ADAPTIVE_RISK:
                print('  • ✓ Adaptive Risk (volatility-based SL/TP)')
            if settings.ENABLE_AUTO_RETRAINING:
                print('  • ✓ Automated ML Retraining')
            if settings.ENABLE_DYNAMIC_STRATEGY_WEIGHTING:
                print('  • ✓ Dynamic Strategy Weighting')

        # Enabled Strategies
        enabled_strategies = [name for name, enabled in settings.ENABLED_STRATEGIES.items() if enabled]
        print('\nEnabled Strategies:')
        for strategy in enabled_strategies:
            print(f'  • {strategy.replace("_", " ").title()}')

        # Connection Info
        try:
            from config.credentials import IBKR

            port = IBKR.get('TWS_PORT', 7497)
            port_type = 'Paper Trading' if port in [7497, 4002] else '⚠️  LIVE TRADING'
            print('\nConnection:')
            print(f'  • TWS/Gateway Port: {port} ({port_type})')
        except Exception:
            pass

        print('\n' + '=' * 70 + '\n')

    def _get_user_confirmation(self) -> bool:
        """Get user confirmation to proceed"""
        print('⚠️  IMPORTANT: Review the configuration above carefully.')
        print('   This bot will execute real trades with real money.\n')

        response = input('Proceed with bot startup? [Y/n]: ').strip().lower()

        return bool(not response or response in ['y', 'yes'])

    def display_welcome_banner(self):
        """Display welcome banner with helpful information"""
        print('\n' + '=' * 70)
        print(' 🤖 AIStocker - AI-Powered Automated Trading System')
        print('=' * 70)
        print('\nBeginner-Friendly Production Trading Bot')
        print('Version: 1.0.0 | Documentation: CLAUDE.md\n')

        print('Quick Help:')
        print('  • Press Ctrl+C at any time to safely stop the bot')
        print('  • Logs are saved to: logs/app.log and logs/error_logs/errors.log')
        print('  • Trade history: logs/trade_logs/trades.log')
        print('  • State is auto-saved every 5 minutes')
        print('\nFor help: Review CLAUDE.md or check /help\n')
        print('=' * 70 + '\n')


def run_startup_checks(settings, headless: bool = False) -> bool:
    """
    Convenience function to run all startup checks

    Args:
        settings: Settings object
        headless: Whether running in headless mode

    Returns:
        True if startup should proceed
    """
    helper = StartupHelper()

    if not headless:
        helper.display_welcome_banner()

    return helper.perform_startup_sequence(settings, headless)
