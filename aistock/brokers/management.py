"""
Broker configuration reconciliation and capital allocation utilities.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeAlias, cast

from ..audit import AuditLogger, JSONValue
from ..config import ContractSpec, RiskLimits
from ..log_config import configure_logger

if TYPE_CHECKING:
    from .base import BaseBroker


JSONDict: TypeAlias = dict[str, object]


def _load_json_dict(path: Path) -> JSONDict | None:
    with path.open('r', encoding='utf-8') as handle:
        payload = cast(object, json.load(handle))
    if not isinstance(payload, dict):
        return None
    return cast(JSONDict, payload)


def _parse_optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _build_contract_spec(symbol: str, payload: dict[str, object]) -> ContractSpec:
    symbol_value = payload.get('symbol')
    sec_type_value = payload.get('sec_type')
    exchange_value = payload.get('exchange')
    currency_value = payload.get('currency')
    local_symbol_value = payload.get('local_symbol')
    multiplier = _parse_optional_int(payload.get('multiplier'))
    return ContractSpec(
        symbol=symbol_value if isinstance(symbol_value, str) else symbol,
        sec_type=sec_type_value if isinstance(sec_type_value, str) else 'STK',
        exchange=exchange_value if isinstance(exchange_value, str) else 'SMART',
        currency=currency_value if isinstance(currency_value, str) else 'USD',
        local_symbol=local_symbol_value if isinstance(local_symbol_value, str) else '',
        multiplier=multiplier,
    )


def _serialize_contract_spec(spec: ContractSpec) -> dict[str, JSONValue]:
    return {
        'symbol': spec.symbol,
        'sec_type': spec.sec_type,
        'exchange': spec.exchange,
        'currency': spec.currency,
        'local_symbol': spec.local_symbol,
        'multiplier': spec.multiplier,
    }


@dataclass
class AllocationResult:
    symbol: str
    max_notional: float
    max_units: float
    per_trade_risk: float


class ContractRegistry:
    """
    Persistent registry of broker contracts keyed by symbol.
    """

    def __init__(self, path: str = 'state/contracts.json'):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._contracts: dict[str, ContractSpec] = {}
        self._load()

    def register(self, spec: ContractSpec) -> None:
        self._contracts[spec.symbol.upper()] = spec
        self._save()

    def update_many(self, specs: Iterable[ContractSpec]) -> None:
        for spec in specs:
            self._contracts[spec.symbol.upper()] = spec
        self._save()

    def get(self, symbol: str) -> ContractSpec | None:
        return self._contracts.get(symbol.upper())

    def __contains__(self, symbol: str) -> bool:
        return symbol.upper() in self._contracts

    def symbols(self) -> list[str]:
        return sorted(self._contracts)

    def snapshot(self) -> dict[str, dict[str, JSONValue]]:
        return {symbol: _serialize_contract_spec(spec) for symbol, spec in self._contracts.items()}

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        data = _load_json_dict(self.path)
        if not data:
            return
        for symbol, payload in data.items():
            if not isinstance(payload, dict):
                continue
            self._contracts[symbol.upper()] = _build_contract_spec(symbol, cast(dict[str, object], payload))

    def _save(self) -> None:
        with self.path.open('w', encoding='utf-8') as handle:
            json.dump(self.snapshot(), handle, indent=2)


class CapitalAllocationEngine:
    """
    Compute per-symbol position limits from risk configuration and thresholds.
    """

    def __init__(self, risk: RiskLimits):
        self.risk = risk

    def build_allocations(
        self,
        equity: float,
        prices: dict[str, float],
        thresholds: Mapping[str, float] | None = None,  # Generic dict for thresholds (FSD mode)
    ) -> dict[str, AllocationResult]:
        allocations: dict[str, AllocationResult] = {}
        max_fraction = self.risk.max_position_fraction
        cap_value = thresholds.get('max_position_fraction_cap') if thresholds else None
        if isinstance(cap_value, (int, float)):
            max_fraction = min(max_fraction, float(cap_value))

        for symbol, price in prices.items():
            if price <= 0:
                continue
            per_symbol_cap = self.risk.per_symbol_notional_cap
            fraction_cap = equity * max_fraction
            max_notional = min(per_symbol_cap, fraction_cap)
            max_units = 0.0 if max_notional <= 0 else min(self.risk.max_single_position_units, max_notional / price)
            allocations[symbol.upper()] = AllocationResult(
                symbol=symbol.upper(),
                max_notional=float(max_notional),
                max_units=float(max_units),
                per_trade_risk=float(equity * self.risk.per_trade_risk_pct),
            )
        return allocations


@dataclass
class PositionDrift:
    symbol: str
    current_qty: float
    target_qty: float
    difference: float
    severity: str


@dataclass
class BrokerReconciliationReport:
    missing_contracts: list[str]
    position_drift: list[PositionDrift]
    orphan_positions: list[str]
    recommendations: list[str]


class BrokerReconciliationService:
    """
    Compare desired broker state with the live account and highlight drift.
    """

    def __init__(
        self,
        broker: BaseBroker,
        registry: ContractRegistry,
        audit_logger: AuditLogger | None = None,
        tolerance: float = 1e-6,
    ) -> None:
        self.broker = broker
        self.registry = registry
        self.audit_logger = audit_logger
        self.tolerance = tolerance
        self.logger = configure_logger('BrokerReconciliation', structured=True)

    def reconcile(
        self,
        desired_symbols: Iterable[str],
        allocations: dict[str, AllocationResult],
        *,
        on_action: Callable[[BrokerReconciliationReport], None] | None = None,
    ) -> BrokerReconciliationReport:
        desired_set = {symbol.upper() for symbol in desired_symbols}
        missing_contracts = sorted(symbol for symbol in desired_set if symbol not in self.registry)

        actual_positions = self.broker.get_positions()
        drifts: list[PositionDrift] = []
        orphan_positions: list[str] = []

        for symbol_raw, (quantity, _) in actual_positions.items():
            symbol = symbol_raw.upper()
            target_allocation = allocations.get(symbol)
            target_qty = target_allocation.max_units if target_allocation else 0.0
            diff = float(quantity) - float(target_qty)
            if abs(diff) > self.tolerance:
                severity = 'orphan' if symbol not in desired_set else ('excess' if diff > 0 else 'deficit')
                drifts.append(
                    PositionDrift(
                        symbol=symbol,
                        current_qty=float(quantity),
                        target_qty=float(target_qty),
                        difference=float(diff),
                        severity=severity,
                    )
                )
            if symbol not in desired_set:
                orphan_positions.append(symbol)

        recommendations: list[str] = []
        if missing_contracts:
            recommendations.append(f'Register contracts for: {", ".join(missing_contracts)}')
        for drift in drifts:
            if drift.severity == 'excess':
                recommendations.append(f'Reduce {drift.symbol} by {abs(drift.difference):.2f} units.')
            elif drift.severity == 'deficit':
                recommendations.append(f'Increase {drift.symbol} by {abs(drift.difference):.2f} units.')
            else:
                recommendations.append(f'Close orphan position {drift.symbol}.')

        report = BrokerReconciliationReport(
            missing_contracts=missing_contracts,
            position_drift=drifts,
            orphan_positions=sorted(set(orphan_positions)),
            recommendations=recommendations,
        )

        if self.audit_logger:
            missing_payload: list[JSONValue] = cast(list[JSONValue], list(missing_contracts))
            drift_payloads: list[JSONValue] = [
                {
                    'symbol': drift.symbol,
                    'current_qty': drift.current_qty,
                    'target_qty': drift.target_qty,
                    'difference': drift.difference,
                    'severity': drift.severity,
                }
                for drift in drifts
            ]
            orphan_payloads: list[JSONValue] = cast(list[JSONValue], list(report.orphan_positions))
            self.audit_logger.append(
                'broker_reconciliation',
                actor='auto',
                details={
                    'missing_contracts': missing_payload,
                    'position_drift': drift_payloads,
                    'orphan_positions': orphan_payloads,
                },
                artefacts={'generated_at': datetime.now(timezone.utc).isoformat()},
            )

        if on_action:
            on_action(report)

        self.logger.info(
            'reconciliation_summary',
            extra={
                'missing_contracts': missing_contracts,
                'position_drift': len(drifts),
                'orphan_positions': report.orphan_positions,
            },
        )
        return report


__all__ = [
    'AllocationResult',
    'BrokerReconciliationReport',
    'BrokerReconciliationService',
    'CapitalAllocationEngine',
    'ContractRegistry',
    'PositionDrift',
]
