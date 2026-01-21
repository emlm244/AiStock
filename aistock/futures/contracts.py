"""
Futures contract specification with expiration tracking.

This module provides extended contract specifications for futures trading,
including expiration date tracking, symbol mapping, and validation results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import TypedDict

from ..config import ContractSpec


class ContractValidationResult(TypedDict):
    """
    Result of contract validation against IBKR or offline data.

    Attributes:
        symbol: Contract symbol
        valid: Whether the contract is valid for trading
        expired: Whether the contract has expired
        days_to_expiry: Days until expiration (negative if expired)
        expiration_date: Expiration date in YYYYMMDD format
        con_id: IBKR unique contract identifier
        error: Error message if validation failed
        warning: Warning message (e.g., near expiry)
    """

    symbol: str
    valid: bool
    expired: bool
    days_to_expiry: int | None
    expiration_date: str | None
    con_id: int | None
    error: str | None
    warning: str | None


@dataclass(frozen=True)
class FuturesContractSpec(ContractSpec):
    """
    Extended contract specification for futures with expiration tracking.

    Inherits from ContractSpec and provides futures-specific functionality
    including expiration calculations and validation.

    Attributes:
        symbol: Contract symbol (e.g., 'ESH26')
        sec_type: Security type (should be 'FUT' for futures)
        exchange: Exchange (e.g., 'CME', 'NYMEX', 'COMEX')
        currency: Currency (default 'USD')
        local_symbol: Local symbol if different from symbol
        multiplier: Contract multiplier (required for futures)
        expiration_date: Expiration date in YYYYMMDD format
        con_id: IBKR unique contract identifier
        underlying: Underlying symbol (e.g., 'ES' for ES futures)

    Example:
        >>> spec = FuturesContractSpec(
        ...     symbol='ESH26',
        ...     sec_type='FUT',
        ...     exchange='CME',
        ...     multiplier=50,
        ...     expiration_date='20260320',
        ...     underlying='ES',
        ... )
        >>> spec.days_to_expiry()
        42  # days until expiry
        >>> spec.is_near_expiry(threshold_days=7)
        False
    """

    def __post_init__(self) -> None:
        """Validate futures contract fields."""
        if self.sec_type == 'FUT' and not self.multiplier:
            raise ValueError(f'Futures contract {self.symbol} requires multiplier')

    def days_to_expiry(self, reference_date: date | None = None) -> int | None:
        """
        Calculate days until contract expiration.

        Args:
            reference_date: Date to calculate from (default: today UTC)

        Returns:
            Days until expiry (negative if expired), or None if expiration unknown
        """
        if not self.expiration_date:
            return None

        ref = reference_date or datetime.now(timezone.utc).date()
        try:
            exp = datetime.strptime(self.expiration_date, '%Y%m%d').date()
            return (exp - ref).days
        except ValueError:
            return None

    def is_expired(self, reference_date: date | None = None) -> bool:
        """
        Check if contract is expired.

        Args:
            reference_date: Date to check against (default: today UTC)

        Returns:
            True if contract is expired, False otherwise
        """
        days = self.days_to_expiry(reference_date)
        return days is not None and days < 0

    def is_near_expiry(
        self,
        threshold_days: int = 7,
        reference_date: date | None = None,
    ) -> bool:
        """
        Check if contract is within rollover window.

        Args:
            threshold_days: Number of days before expiry to consider "near"
            reference_date: Date to check against (default: today UTC)

        Returns:
            True if contract expires within threshold_days
        """
        days = self.days_to_expiry(reference_date)
        return days is not None and 0 <= days <= threshold_days


@dataclass
class SymbolMapping:
    """
    Mapping from logical symbol to actual futures contract.

    Used to map user-friendly symbols (e.g., 'ES') to specific
    contract months (e.g., 'ESH26' for March 2026).

    Attributes:
        logical_symbol: User-friendly symbol (e.g., 'ES')
        actual_contract: Actual contract symbol (e.g., 'ESH26')
        contract_spec: Full contract specification
        is_front_month: Whether this is the front-month contract
        updated_at: When this mapping was last updated

    Example:
        >>> mapping = SymbolMapping(
        ...     logical_symbol='ES',
        ...     actual_contract='ESH26',
        ...     contract_spec=es_spec,
        ...     is_front_month=True,
        ... )
    """

    logical_symbol: str  # e.g., 'ES'
    actual_contract: str  # e.g., 'ESH26'
    contract_spec: FuturesContractSpec
    is_front_month: bool = False
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Common futures contract configurations for reference
FUTURES_DEFAULTS: dict[str, dict[str, int | str]] = {
    # CME Index Futures
    'ES': {'multiplier': 50, 'exchange': 'CME'},  # E-mini S&P 500
    'NQ': {'multiplier': 20, 'exchange': 'CME'},  # E-mini Nasdaq-100
    'RTY': {'multiplier': 50, 'exchange': 'CME'},  # E-mini Russell 2000
    'YM': {'multiplier': 5, 'exchange': 'CME'},  # E-mini Dow
    'MES': {'multiplier': 5, 'exchange': 'CME'},  # Micro E-mini S&P 500
    'MNQ': {'multiplier': 2, 'exchange': 'CME'},  # Micro E-mini Nasdaq-100
    # NYMEX Energy
    'CL': {'multiplier': 1000, 'exchange': 'NYMEX'},  # Crude Oil
    'NG': {'multiplier': 10000, 'exchange': 'NYMEX'},  # Natural Gas
    'RB': {'multiplier': 42000, 'exchange': 'NYMEX'},  # RBOB Gasoline
    # COMEX Metals
    'GC': {'multiplier': 100, 'exchange': 'COMEX'},  # Gold
    'SI': {'multiplier': 5000, 'exchange': 'COMEX'},  # Silver
    'HG': {'multiplier': 25000, 'exchange': 'COMEX'},  # Copper
    # CBOT Grains
    'ZC': {'multiplier': 50, 'exchange': 'CBOT'},  # Corn
    'ZS': {'multiplier': 50, 'exchange': 'CBOT'},  # Soybeans
    'ZW': {'multiplier': 50, 'exchange': 'CBOT'},  # Wheat
}
