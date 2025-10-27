"""
Run Mode Configuration & Safety Controls

This module enforces strict run mode separation and provides safety guardrails
for live trading. Live trading is DISABLED by default and requires explicit opt-in.
"""

import os
from enum import Enum
from typing import Optional


class RunMode(Enum):
    """Trading system run modes with increasing risk levels."""

    RESEARCH = 'research'  # Offline analysis, no broker connection
    BACKTEST = 'backtest'  # Historical simulation, deterministic
    PAPER = 'paper'  # Live data, simulated orders
    LIVE = 'live'  # REAL MONEY - requires explicit enable


class LiveTradingGuard:
    """
    Safety mechanism to prevent accidental live trading.

    Live trading requires:
    1. Explicit environment variable: ENABLE_LIVE_TRADING=true
    2. Port verification (must not be paper trading port)
    3. Account ID verification
    4. User confirmation (if interactive)
    """

    # Ports that indicate paper trading
    PAPER_TRADING_PORTS = [7497, 4002]

    # Ports that indicate live trading
    LIVE_TRADING_PORTS = [7496, 4001]

    @classmethod
    def is_live_trading_enabled(cls) -> bool:
        """Check if live trading is explicitly enabled via environment."""
        return os.getenv('ENABLE_LIVE_TRADING', '').lower() in ['true', '1', 'yes']

    @classmethod
    def verify_live_trading_config(cls, port: int, account_id: str) -> tuple[bool, str]:
        """
        Verify live trading configuration is safe and intentional.

        Returns:
            (is_valid, error_message)
        """
        # Check 1: Environment variable must be set
        if not cls.is_live_trading_enabled():
            return False, (
                'Live trading is DISABLED by default. '
                'To enable, set environment variable: ENABLE_LIVE_TRADING=true'
            )

        # Check 2: Port must be a live trading port
        if port in cls.PAPER_TRADING_PORTS:
            return False, (
                f'Port {port} is configured for PAPER TRADING, but live trading is enabled. '
                f'Use live trading port ({cls.LIVE_TRADING_PORTS}) or disable ENABLE_LIVE_TRADING.'
            )

        if port not in cls.LIVE_TRADING_PORTS:
            return False, (
                f'Port {port} is not recognized as a standard IB port. '
                f'Expected live ports: {cls.LIVE_TRADING_PORTS}, paper ports: {cls.PAPER_TRADING_PORTS}'
            )

        # Check 3: Account ID must be set and not a placeholder
        if not account_id or account_id in ['YOUR_ACCOUNT_ID', 'YOUR_ACCOUNT_ID_HERE', 'TEST_ACCOUNT']:
            return False, 'Account ID is not properly configured for live trading.'

        return True, ''

    @classmethod
    def get_run_mode_from_port(cls, port: int) -> RunMode:
        """Determine run mode from TWS/Gateway port."""
        if port in cls.PAPER_TRADING_PORTS:
            return RunMode.PAPER
        elif port in cls.LIVE_TRADING_PORTS:
            if cls.is_live_trading_enabled():
                return RunMode.LIVE
            else:
                # Safety: Even if live port is configured, default to paper if not explicitly enabled
                return RunMode.PAPER
        else:
            # Unknown port, assume paper for safety
            return RunMode.PAPER

    @classmethod
    def get_safety_message(cls, run_mode: RunMode, port: int, account_id: str) -> str:
        """Generate a safety message for the current run mode."""
        if run_mode == RunMode.LIVE:
            return f"""
╔══════════════════════════════════════════════════════════════════════╗
║                    ⚠️  LIVE TRADING MODE ACTIVE ⚠️                    ║
╠══════════════════════════════════════════════════════════════════════╣
║  This bot will place REAL ORDERS with REAL MONEY.                   ║
║  Port: {port:<4}  |  Account: {account_id[:10]:<10}                          ║
║                                                                      ║
║  Safety Checklist:                                                   ║
║  ✓ Risk limits are configured and tested                            ║
║  ✓ Position sizing is appropriate for account                       ║
║  ✓ Kill switch mechanism is understood                              ║
║  ✓ You have reviewed recent code changes                            ║
║  ✓ Backtests show acceptable performance                            ║
╚══════════════════════════════════════════════════════════════════════╝
"""
        elif run_mode == RunMode.PAPER:
            return f"""
╔══════════════════════════════════════════════════════════════════════╗
║                    📝 PAPER TRADING MODE ACTIVE                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  Orders are simulated. No real money at risk.                       ║
║  Port: {port:<4}  |  Account: {account_id[:10]:<10}                          ║
║                                                                      ║
║  Use paper trading to:                                               ║
║  • Test strategies with live data                                    ║
║  • Verify order execution logic                                      ║
║  • Practice risk management                                          ║
║  • Build confidence before live trading                             ║
╚══════════════════════════════════════════════════════════════════════╝
"""
        else:
            return f'Run Mode: {run_mode.value.upper()}'


def validate_run_mode_safety(port: int, account_id: str, interactive: bool = True) -> tuple[bool, RunMode]:
    """
    Validate run mode configuration and get user confirmation if needed.

    Args:
        port: TWS/Gateway port number
        account_id: IB account ID
        interactive: Whether to prompt user for confirmation

    Returns:
        (is_safe_to_proceed, run_mode)
    """
    guard = LiveTradingGuard()
    run_mode = guard.get_run_mode_from_port(port)

    # Print safety message
    print(guard.get_safety_message(run_mode, port, account_id))

    # If live trading, perform additional checks
    if run_mode == RunMode.LIVE:
        is_valid, error_msg = guard.verify_live_trading_config(port, account_id)

        if not is_valid:
            print(f'\n❌ LIVE TRADING BLOCKED: {error_msg}\n')
            return False, run_mode

        # Require explicit user confirmation in interactive mode
        if interactive:
            print('\n⚠️  LIVE TRADING CONFIRMATION REQUIRED ⚠️')
            print('Type "I UNDERSTAND THE RISKS" (exactly) to proceed with live trading:')
            confirmation = input('> ').strip()

            if confirmation != 'I UNDERSTAND THE RISKS':
                print('\n❌ Live trading cancelled. Confirmation not received.\n')
                return False, run_mode

            print('\n✓ Live trading confirmed. Proceeding...\n')

    return True, run_mode


# Expose key functions at module level
__all__ = ['RunMode', 'LiveTradingGuard', 'validate_run_mode_safety']
