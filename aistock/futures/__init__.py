"""
Futures contract management and rollover support.

This module provides:
- Extended contract specifications with expiration tracking
- Pre-flight validation to block expired contracts
- Symbol mapping from logical symbols to actual contracts
- Rollover detection and alert generation
- Position rollover order generation (manual execution)

Example usage:
    from aistock.futures import (
        FuturesContractSpec,
        RolloverConfig,
        RolloverManager,
        FuturesPreflightChecker,
    )

    # Create a futures contract spec
    es_contract = FuturesContractSpec(
        symbol='ESH26',
        sec_type='FUT',
        exchange='CME',
        multiplier=50,
        expiration_date='20260320',
        underlying='ES',
    )

    # Run pre-flight checks
    checker = FuturesPreflightChecker(warn_threshold_days=7)
    result = checker.run_preflight(broker, {'ESH26': es_contract})
    if not result.passed:
        raise RuntimeError(f'Preflight failed: {result.errors}')

    # Monitor for rollover needs
    manager = RolloverManager(RolloverConfig())
    alerts = manager.check_rollover_needed({'ESH26': es_contract})
"""

from __future__ import annotations

from .contracts import (
    ContractValidationResult,
    FuturesContractSpec,
    SymbolMapping,
)
from .preflight import (
    FuturesPreflightChecker,
    PreflightResult,
)
from .rollover import (
    RolloverConfig,
    RolloverEvent,
    RolloverManager,
    RolloverStatus,
)

__all__ = [
    # Contracts
    'ContractValidationResult',
    'FuturesContractSpec',
    'SymbolMapping',
    # Preflight
    'FuturesPreflightChecker',
    'PreflightResult',
    # Rollover
    'RolloverConfig',
    'RolloverEvent',
    'RolloverManager',
    'RolloverStatus',
]
