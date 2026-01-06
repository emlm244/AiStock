"""
Pre-flight validation for futures contracts before trading.

This module provides validation checks that run at session startup to
ensure no expired contracts are configured and warn about contracts
approaching expiry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..log_config import configure_logger
from .contracts import ContractValidationResult, FuturesContractSpec
from .validator import FuturesContractValidator, IBKRBrokerProtocol

if TYPE_CHECKING:
    from ..config import ContractSpec


@dataclass
class PreflightResult:
    """
    Result of pre-flight validation.

    Attributes:
        passed: Whether all checks passed (no blocking errors)
        errors: List of blocking errors (expired contracts)
        warnings: List of warnings (contracts near expiry)
        validated_contracts: Per-contract validation results

    Example:
        >>> result = checker.run_preflight(broker, contracts)
        >>> if not result.passed:
        ...     raise RuntimeError(f"Preflight failed: {result.errors}")
        >>> for warning in result.warnings:
        ...     print(f"Warning: {warning}")
    """

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validated_contracts: dict[str, ContractValidationResult] = field(default_factory=dict)


class FuturesPreflightChecker:
    """
    Pre-flight checker that validates all futures contracts before trading.

    Called during session startup to ensure:
    1. No expired contracts are configured (BLOCKS trading)
    2. Contracts approaching expiry are flagged (warnings)
    3. Contract details are refreshed from IBKR if available

    The checker will BLOCK trading completely if any futures contract
    has expired. This is a safety measure to prevent trading on
    invalid contracts.

    Attributes:
        warn_threshold_days: Days before expiry to trigger warning
        block_on_expired: Whether to block trading on expired contracts

    Example:
        >>> checker = FuturesPreflightChecker(
        ...     warn_threshold_days=7,
        ...     block_on_expired=True,
        ... )
        >>> result = checker.run_preflight(broker, contracts)
        >>> if not result.passed:
        ...     raise RuntimeError(f"Preflight failed: {result.errors}")
    """

    def __init__(
        self,
        warn_threshold_days: int = 7,
        block_on_expired: bool = True,
    ):
        """
        Initialize the preflight checker.

        Args:
            warn_threshold_days: Days before expiry to trigger warning
            block_on_expired: Whether to block trading on expired contracts
        """
        self._warn_days = warn_threshold_days
        self._block_expired = block_on_expired
        self._logger = configure_logger('FuturesPreflightChecker', structured=True)
        self._validator = FuturesContractValidator(
            timeout=10.0,
            warn_days_threshold=warn_threshold_days,
        )

    def run_preflight(
        self,
        broker: IBKRBrokerProtocol | None,
        contracts: dict[str, FuturesContractSpec | ContractSpec],
    ) -> PreflightResult:
        """
        Run pre-flight validation on all futures contracts.

        This method validates all configured futures contracts and:
        - BLOCKS trading if any contract is expired (when block_on_expired=True)
        - Logs warnings for contracts approaching expiry
        - Records validation results for all contracts

        Args:
            broker: Connected IBKR broker (or None for offline validation)
            contracts: Symbol -> contract spec mapping

        Returns:
            PreflightResult with pass/fail status and details
        """
        errors: list[str] = []
        warnings: list[str] = []
        validated: dict[str, ContractValidationResult] = {}

        # Filter to futures contracts only
        futures_contracts = {symbol: spec for symbol, spec in contracts.items() if spec.sec_type == 'FUT'}

        if not futures_contracts:
            self._logger.info(
                'preflight_no_futures',
                extra={'detail': 'No futures contracts to validate'},
            )
            return PreflightResult(
                passed=True,
                errors=[],
                warnings=[],
                validated_contracts={},
            )

        self._logger.info(
            'preflight_starting',
            extra={
                'contract_count': len(futures_contracts),
                'symbols': list(futures_contracts.keys()),
            },
        )

        # Validate each contract
        for symbol, spec in futures_contracts.items():
            # Convert to FuturesContractSpec if needed
            if isinstance(spec, FuturesContractSpec):
                futures_spec = spec
            else:
                futures_spec = FuturesContractSpec(
                    symbol=spec.symbol,
                    sec_type=spec.sec_type,
                    exchange=spec.exchange,
                    currency=spec.currency,
                    local_symbol=spec.local_symbol,
                    multiplier=spec.multiplier,
                    expiration_date=spec.expiration_date,
                    con_id=spec.con_id,
                    underlying=spec.underlying,
                )

            result = self._validator.validate_contract(broker, futures_spec)
            validated[symbol] = result

            # Collect errors and warnings
            if result['error']:
                if result['expired'] and self._block_expired:
                    errors.append(result['error'])
                else:
                    warnings.append(result['error'])

            if result['warning']:
                warnings.append(result['warning'])

        # Determine pass/fail
        passed = len(errors) == 0

        self._logger.info(
            'preflight_completed',
            extra={
                'passed': passed,
                'error_count': len(errors),
                'warning_count': len(warnings),
                'validated_count': len(validated),
            },
        )

        # Log all errors
        for error in errors:
            self._logger.error('preflight_error', extra={'error': error})

        # Log all warnings
        for warning in warnings:
            self._logger.warning('preflight_warning', extra={'warning': warning})

        return PreflightResult(
            passed=passed,
            errors=errors,
            warnings=warnings,
            validated_contracts=validated,
        )

    def check_single_contract(
        self,
        broker: IBKRBrokerProtocol | None,
        spec: FuturesContractSpec | ContractSpec,
    ) -> tuple[bool, str | None]:
        """
        Quick check for a single contract.

        Args:
            broker: Connected IBKR broker (or None for offline)
            spec: Contract spec to check

        Returns:
            Tuple of (is_valid, error_message)
        """
        if spec.sec_type != 'FUT':
            return (True, None)

        # Convert to FuturesContractSpec if needed
        if isinstance(spec, FuturesContractSpec):
            futures_spec = spec
        else:
            futures_spec = FuturesContractSpec(
                symbol=spec.symbol,
                sec_type=spec.sec_type,
                exchange=spec.exchange,
                currency=spec.currency,
                local_symbol=spec.local_symbol,
                multiplier=spec.multiplier,
                expiration_date=spec.expiration_date,
                con_id=spec.con_id,
                underlying=spec.underlying,
            )

        result = self._validator.validate_contract(broker, futures_spec)

        if result['expired'] and self._block_expired:
            return (False, result['error'])

        return (result['valid'], result['error'])


def run_futures_preflight(
    broker: IBKRBrokerProtocol | None,
    contracts: dict[str, FuturesContractSpec | ContractSpec],
    warn_threshold_days: int = 7,
    block_on_expired: bool = True,
) -> PreflightResult:
    """
    Convenience function to run futures preflight checks.

    Args:
        broker: Connected IBKR broker (or None for offline validation)
        contracts: Symbol -> contract spec mapping
        warn_threshold_days: Days before expiry to trigger warning
        block_on_expired: Whether to block trading on expired contracts

    Returns:
        PreflightResult with pass/fail status and details

    Raises:
        RuntimeError: If preflight fails and block_on_expired is True

    Example:
        >>> result = run_futures_preflight(broker, contracts)
        >>> # Raises RuntimeError if any futures contract is expired
    """
    checker = FuturesPreflightChecker(
        warn_threshold_days=warn_threshold_days,
        block_on_expired=block_on_expired,
    )
    result = checker.run_preflight(broker, contracts)

    if not result.passed:
        error_msg = '; '.join(result.errors)
        raise RuntimeError(f'Futures preflight failed: {error_msg}')

    return result
