"""
Futures contract validation via IBKR API.

This module provides contract validation functionality that can query IBKR
for contract details including expiration dates and conId.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol

from ..log_config import configure_logger
from .contracts import ContractValidationResult, FuturesContractSpec

if TYPE_CHECKING:
    from ..config import ContractSpec


class IBKRBrokerProtocol(Protocol):
    """Protocol for IBKR broker with contract details support."""

    def isConnected(self) -> bool: ...  # noqa: N802 - IBKR API convention

    def request_contract_details(self, symbol: str, timeout: float = 10.0) -> list[object]: ...

    def _build_contract(self, symbol: str) -> object: ...


class FuturesContractValidator:
    """
    Validates futures contracts via IBKR reqContractDetails API.

    Thread-safe validator that queries IBKR for contract details
    including expiration dates and conId. Falls back to offline
    validation using spec data when IBKR is unavailable.

    Attributes:
        timeout: Maximum wait time for IBKR response
        warn_days_threshold: Days before expiry to trigger warning

    Example:
        >>> validator = FuturesContractValidator(timeout=10.0, warn_days_threshold=7)
        >>> result = validator.validate_contract(ibkr_broker, es_spec)
        >>> if not result['valid']:
        ...     print(f"Contract invalid: {result['error']}")
    """

    def __init__(
        self,
        timeout: float = 10.0,
        warn_days_threshold: int = 7,
    ):
        """
        Initialize the validator.

        Args:
            timeout: Maximum wait time for IBKR response (seconds)
            warn_days_threshold: Days before expiry to trigger warning
        """
        self._timeout = timeout
        self._warn_days = warn_days_threshold
        self._logger = configure_logger('FuturesContractValidator', structured=True)
        self._lock = threading.Lock()

    def validate_contract(
        self,
        broker: IBKRBrokerProtocol | None,
        spec: FuturesContractSpec | ContractSpec,
    ) -> ContractValidationResult:
        """
        Validate a futures contract via IBKR or offline.

        Queries reqContractDetails to get:
        - Expiration date
        - conId (unique identifier)
        - Validity status

        Falls back to offline validation using spec data if IBKR unavailable.

        Args:
            broker: Connected IBKR broker instance (or None for offline)
            spec: Contract spec to validate

        Returns:
            ContractValidationResult with validation details
        """
        result: ContractValidationResult = {
            'symbol': spec.symbol,
            'valid': False,
            'expired': False,
            'days_to_expiry': None,
            'expiration_date': spec.expiration_date,
            'con_id': spec.con_id,
            'error': None,
            'warning': None,
        }

        try:
            # Try IBKR validation if broker available
            if broker is not None and broker.isConnected():
                ibkr_result = self._validate_via_ibkr(broker, spec)
                if ibkr_result is not None:
                    return ibkr_result
                # Fall through to offline if IBKR failed

            # Offline validation using spec data
            return self._validate_offline(spec, result)

        except Exception as exc:
            result['error'] = f'Validation failed: {exc}'
            self._logger.error(
                'contract_validation_failed',
                extra={'symbol': spec.symbol, 'error': str(exc)},
            )
            return result

    def validate_batch(
        self,
        broker: IBKRBrokerProtocol | None,
        specs: dict[str, FuturesContractSpec | ContractSpec],
    ) -> dict[str, ContractValidationResult]:
        """
        Validate multiple contracts.

        Args:
            broker: Connected IBKR broker instance (or None for offline)
            specs: Symbol -> contract spec mapping

        Returns:
            Symbol -> validation result mapping
        """
        results: dict[str, ContractValidationResult] = {}
        for symbol, spec in specs.items():
            results[symbol] = self.validate_contract(broker, spec)
        return results

    def _validate_via_ibkr(
        self,
        broker: IBKRBrokerProtocol,
        spec: FuturesContractSpec | ContractSpec,
    ) -> ContractValidationResult | None:
        """
        Validate contract via IBKR API.

        Returns None if IBKR validation fails (caller should fall back to offline).
        """
        result: ContractValidationResult = {
            'symbol': spec.symbol,
            'valid': False,
            'expired': False,
            'days_to_expiry': None,
            'expiration_date': None,
            'con_id': None,
            'error': None,
            'warning': None,
        }

        try:
            # Request contract details from IBKR
            details_list = broker.request_contract_details(spec.symbol, timeout=self._timeout)

            if not details_list:
                self._logger.warning(
                    'no_contract_details',
                    extra={'symbol': spec.symbol, 'message': 'IBKR returned no details'},
                )
                return None  # Fall back to offline

            # Extract first matching contract details
            details = details_list[0]

            # Get expiration date from contract details
            exp_date: str | None = None
            if hasattr(details, 'realExpirationDate'):
                exp_date = getattr(details, 'realExpirationDate', None)
            if not exp_date and hasattr(details, 'lastTradeDate'):
                exp_date = getattr(details, 'lastTradeDate', None)
            if not exp_date and hasattr(details, 'contractMonth'):
                exp_date = getattr(details, 'contractMonth', None)

            # Get conId (using getattr because details is dynamically typed from IBKR)
            con_id: int | None = None
            if hasattr(details, 'contract'):
                contract_obj = getattr(details, 'contract')  # noqa: B009
                if hasattr(contract_obj, 'conId'):
                    con_id = getattr(contract_obj, 'conId', None)  # noqa: B009

            result['expiration_date'] = exp_date
            result['con_id'] = con_id

            # Calculate days to expiry
            if exp_date:
                days = self._calculate_days_to_expiry(exp_date)
                result['days_to_expiry'] = days

                if days < 0:
                    result['expired'] = True
                    result['error'] = f'Contract {spec.symbol} expired {abs(days)} days ago'
                elif days <= self._warn_days:
                    result['warning'] = (
                        f'Contract {spec.symbol} expires in {days} days - rollover recommended'
                    )
                    result['valid'] = True
                else:
                    result['valid'] = True
            else:
                # No expiration info, assume valid (e.g., cash-settled)
                result['valid'] = True
                result['warning'] = f'Contract {spec.symbol} has no expiration date from IBKR'

            self._logger.info(
                'contract_validated_via_ibkr',
                extra={
                    'symbol': spec.symbol,
                    'valid': result['valid'],
                    'days_to_expiry': result['days_to_expiry'],
                    'con_id': result['con_id'],
                },
            )

            return result

        except Exception as exc:
            self._logger.warning(
                'ibkr_validation_failed',
                extra={'symbol': spec.symbol, 'error': str(exc), 'message': 'Falling back to offline'},
            )
            return None  # Fall back to offline

    def _validate_offline(
        self,
        spec: FuturesContractSpec | ContractSpec,
        result: ContractValidationResult,
    ) -> ContractValidationResult:
        """Validate contract using only spec data (no IBKR query)."""
        if not spec.expiration_date:
            result['warning'] = (
                f'Contract {spec.symbol} has no expiration date - IBKR validation recommended'
            )
            result['valid'] = True
            return result

        days = self._calculate_days_to_expiry(spec.expiration_date)
        result['days_to_expiry'] = days
        result['expiration_date'] = spec.expiration_date
        result['con_id'] = spec.con_id

        if days is not None:
            if days < 0:
                result['expired'] = True
                result['error'] = f'Contract {spec.symbol} expired {abs(days)} days ago'
            elif days <= self._warn_days:
                result['warning'] = (
                    f'Contract {spec.symbol} expires in {days} days - rollover recommended'
                )
                result['valid'] = True
            else:
                result['valid'] = True
        else:
            result['valid'] = True

        self._logger.info(
            'contract_validated_offline',
            extra={
                'symbol': spec.symbol,
                'valid': result['valid'],
                'days_to_expiry': result['days_to_expiry'],
            },
        )

        return result

    def _calculate_days_to_expiry(self, exp_date: str) -> int | None:
        """
        Calculate days from today to expiration.

        Args:
            exp_date: Expiration date in YYYYMMDD or YYYYMM format

        Returns:
            Days until expiry (negative if expired), or None if parse fails
        """
        today = datetime.now(timezone.utc).date()
        try:
            # Try YYYYMMDD format first
            if len(exp_date) == 8:
                exp = datetime.strptime(exp_date, '%Y%m%d').date()
            elif len(exp_date) == 6:
                # YYYYMM format - assume last day of month
                from datetime import timedelta

                year = int(exp_date[:4])
                month = int(exp_date[4:6])
                # Get last day of month
                next_month = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
                exp = (next_month - timedelta(days=1)).date()
            else:
                return None

            return (exp - today).days
        except (ValueError, TypeError):
            return None
