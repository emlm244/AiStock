"""
Futures rollover management and position migration.

This module provides rollover detection, alert generation, and order
generation for futures contract transitions. Execution is manual only.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict

from ..log_config import configure_logger
from .contracts import FuturesContractSpec, SymbolMapping

if TYPE_CHECKING:
    from ..config import ContractSpec


class PositionProtocol(Protocol):
    """Protocol for position data."""

    @property
    def quantity(self) -> Decimal: ...


class PortfolioProtocol(Protocol):
    """Protocol for portfolio with position access."""

    def position(self, symbol: str) -> PositionProtocol: ...


class RolloverStatus(str, Enum):
    """Status of a rollover event."""

    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class RolloverOrder(TypedDict):
    """Order information for rollover."""

    symbol: str
    side: str  # 'BUY' or 'SELL'
    quantity: str  # Decimal as string
    contract_symbol: str


class RolloverAlert(TypedDict):
    """Alert for contract nearing expiry."""

    symbol: str
    underlying: str
    expiration_date: str | None
    days_to_expiry: int
    urgency: str  # 'critical' or 'warning'
    recommendation: str


@dataclass
class RolloverConfig:
    """
    Configuration for futures rollover behavior.

    Attributes:
        warn_days_before_expiry: Days before expiry to start warning
        auto_detect_front_month: Query IBKR for front-month contract
        persist_mappings: Save symbol mappings to disk
        mappings_path: Path for symbol mappings persistence

    Example:
        >>> config = RolloverConfig(
        ...     warn_days_before_expiry=7,
        ...     persist_mappings=True,
        ... )
    """

    warn_days_before_expiry: int = 7
    auto_detect_front_month: bool = True
    persist_mappings: bool = True
    mappings_path: str = 'state/futures_mappings.json'

    def validate(self) -> None:
        """
        Validate rollover configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        if self.warn_days_before_expiry < 1:
            raise ValueError(
                f'warn_days_before_expiry must be >= 1, got {self.warn_days_before_expiry}'
            )


@dataclass
class RolloverEvent:
    """
    Record of a rollover event for audit trail.

    Tracks the transition from one contract to another,
    including position details and execution status.

    Attributes:
        event_id: Unique identifier for this rollover
        timestamp: When the rollover was initiated
        logical_symbol: Underlying symbol (e.g., 'ES')
        from_contract: Old contract symbol (e.g., 'ESZ25')
        to_contract: New contract symbol (e.g., 'ESH26')
        position_quantity: Position size to roll
        status: Current status of the rollover
        close_order_id: Order ID for closing old position
        open_order_id: Order ID for opening new position
        close_fill_price: Fill price for close order
        open_fill_price: Fill price for open order
        error_message: Error message if rollover failed
        completed_at: When the rollover completed
    """

    event_id: str
    timestamp: datetime
    logical_symbol: str
    from_contract: str
    to_contract: str
    position_quantity: Decimal
    status: RolloverStatus
    close_order_id: int | None = None
    open_order_id: int | None = None
    close_fill_price: Decimal | None = None
    open_fill_price: Decimal | None = None
    error_message: str | None = None
    completed_at: datetime | None = None


class RolloverManager:
    """
    Manages futures contract rollover detection and order generation.

    This class provides:
    - Symbol-to-contract mapping management
    - Rollover detection based on expiration dates
    - Alert generation for contracts nearing expiry
    - Rollover order generation (manual execution only)
    - Audit trail for rollover events

    Example:
        >>> config = RolloverConfig(warn_days_before_expiry=7)
        >>> manager = RolloverManager(config)

        >>> # Register contract mapping
        >>> manager.register_mapping('ES', es_spec, is_front_month=True)

        >>> # Check for rollover needs
        >>> alerts = manager.check_rollover_needed({'ESH26': es_spec})
        >>> for alert in alerts:
        ...     if alert['days_to_expiry'] <= 3:
        ...         close_order, open_order = manager.generate_rollover_orders(
        ...             alert['symbol'], next_contract, portfolio
        ...         )
    """

    def __init__(
        self,
        config: RolloverConfig,
        state_dir: str = 'state',
    ):
        """
        Initialize the rollover manager.

        Args:
            config: Rollover configuration
            state_dir: Directory for state persistence
        """
        config.validate()
        self.config = config
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)

        self._logger = configure_logger('RolloverManager', structured=True)

        # Symbol mappings: logical_symbol -> SymbolMapping
        self._mappings: dict[str, SymbolMapping] = {}

        # Rollover history for audit
        self._events: list[RolloverEvent] = []

        # Load persisted state
        if config.persist_mappings:
            self._load_mappings()

    def register_mapping(
        self,
        logical_symbol: str,
        contract_spec: FuturesContractSpec | ContractSpec,
        is_front_month: bool = False,
    ) -> None:
        """
        Register a symbol-to-contract mapping.

        Args:
            logical_symbol: Logical symbol (e.g., 'ES')
            contract_spec: Actual futures contract spec
            is_front_month: Whether this is the front-month contract
        """
        # Convert ContractSpec to FuturesContractSpec if needed
        if not isinstance(contract_spec, FuturesContractSpec):
            futures_spec = FuturesContractSpec(
                symbol=contract_spec.symbol,
                sec_type=contract_spec.sec_type,
                exchange=contract_spec.exchange,
                currency=contract_spec.currency,
                local_symbol=contract_spec.local_symbol,
                multiplier=contract_spec.multiplier,
                expiration_date=contract_spec.expiration_date,
                con_id=contract_spec.con_id,
                underlying=contract_spec.underlying,
            )
        else:
            futures_spec = contract_spec

        mapping = SymbolMapping(
            logical_symbol=logical_symbol.upper(),
            actual_contract=futures_spec.symbol,
            contract_spec=futures_spec,
            is_front_month=is_front_month,
        )
        self._mappings[logical_symbol.upper()] = mapping

        self._logger.info(
            'symbol_mapping_registered',
            extra={
                'logical_symbol': logical_symbol,
                'actual_contract': futures_spec.symbol,
                'expiration': futures_spec.expiration_date,
                'is_front_month': is_front_month,
            },
        )

        if self.config.persist_mappings:
            self._save_mappings()

    def get_contract(self, logical_symbol: str) -> FuturesContractSpec | None:
        """
        Get the actual contract for a logical symbol.

        Args:
            logical_symbol: Logical symbol (e.g., 'ES')

        Returns:
            FuturesContractSpec or None if not registered
        """
        mapping = self._mappings.get(logical_symbol.upper())
        return mapping.contract_spec if mapping else None

    def get_mapping(self, logical_symbol: str) -> SymbolMapping | None:
        """
        Get the full mapping for a logical symbol.

        Args:
            logical_symbol: Logical symbol (e.g., 'ES')

        Returns:
            SymbolMapping or None if not registered
        """
        return self._mappings.get(logical_symbol.upper())

    def all_mappings(self) -> dict[str, SymbolMapping]:
        """Get all registered symbol mappings."""
        return dict(self._mappings)

    def check_rollover_needed(
        self,
        contracts: dict[str, FuturesContractSpec | ContractSpec],
    ) -> list[RolloverAlert]:
        """
        Check which contracts need rollover.

        Args:
            contracts: Symbol -> contract spec mapping

        Returns:
            List of rollover alerts for contracts within warning window
        """
        alerts: list[RolloverAlert] = []

        for symbol, spec in contracts.items():
            if spec.sec_type != 'FUT':
                continue

            # Get days to expiry
            if isinstance(spec, FuturesContractSpec):
                days = spec.days_to_expiry()
            elif spec.expiration_date:
                from datetime import datetime, timezone

                try:
                    exp = datetime.strptime(spec.expiration_date, '%Y%m%d').date()
                    today = datetime.now(timezone.utc).date()
                    days = (exp - today).days
                except ValueError:
                    continue
            else:
                continue

            if days is None:
                continue

            if days <= self.config.warn_days_before_expiry:
                urgency = 'critical' if days <= 2 else 'warning'
                alert: RolloverAlert = {
                    'symbol': symbol,
                    'underlying': spec.underlying or symbol,
                    'expiration_date': spec.expiration_date,
                    'days_to_expiry': days,
                    'urgency': urgency,
                    'recommendation': f'Roll {symbol} to next contract within {days} days',
                }
                alerts.append(alert)

                self._logger.warning(
                    'rollover_alert',
                    extra={
                        'symbol': symbol,
                        'days_to_expiry': days,
                        'urgency': urgency,
                    },
                )

        return alerts

    def generate_rollover_orders(
        self,
        symbol: str,
        next_contract: FuturesContractSpec,
        portfolio: PortfolioProtocol,
    ) -> tuple[RolloverOrder | None, RolloverOrder | None]:
        """
        Generate orders to roll a position from current to next contract.

        Note: This only generates order specifications. Execution must be
        performed manually by the user.

        Args:
            symbol: Symbol to roll
            next_contract: Next contract specification
            portfolio: Portfolio with current position

        Returns:
            Tuple of (close_order, open_order) or (None, None) if no position
        """
        position = portfolio.position(symbol)
        if position.quantity == 0:
            self._logger.info(
                'no_position_to_roll',
                extra={'symbol': symbol},
            )
            return (None, None)

        current_spec = self.get_contract(symbol)
        current_symbol = current_spec.symbol if current_spec else symbol

        # Close order: opposite side of current position
        close_side = 'SELL' if position.quantity > 0 else 'BUY'
        close_order: RolloverOrder = {
            'symbol': current_symbol,
            'side': close_side,
            'quantity': str(abs(position.quantity)),
            'contract_symbol': current_symbol,
        }

        # Open order: same direction as original position in new contract
        open_side = 'BUY' if position.quantity > 0 else 'SELL'
        open_order: RolloverOrder = {
            'symbol': next_contract.symbol,
            'side': open_side,
            'quantity': str(abs(position.quantity)),
            'contract_symbol': next_contract.symbol,
        }

        self._logger.info(
            'rollover_orders_generated',
            extra={
                'symbol': symbol,
                'from_contract': current_symbol,
                'to_contract': next_contract.symbol,
                'quantity': str(position.quantity),
                'close_side': close_side,
                'open_side': open_side,
            },
        )

        return (close_order, open_order)

    def create_rollover_event(
        self,
        logical_symbol: str,
        from_contract: str,
        to_contract: str,
        position_quantity: Decimal,
    ) -> RolloverEvent:
        """
        Create a new rollover event for tracking.

        Args:
            logical_symbol: Underlying symbol (e.g., 'ES')
            from_contract: Old contract symbol
            to_contract: New contract symbol
            position_quantity: Position size to roll

        Returns:
            New RolloverEvent with PENDING status
        """
        event = RolloverEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            logical_symbol=logical_symbol.upper(),
            from_contract=from_contract,
            to_contract=to_contract,
            position_quantity=position_quantity,
            status=RolloverStatus.PENDING,
        )
        self._events.append(event)

        self._logger.info(
            'rollover_event_created',
            extra={
                'event_id': event.event_id,
                'from': from_contract,
                'to': to_contract,
                'quantity': str(position_quantity),
            },
        )

        return event

    def update_rollover_status(
        self,
        event_id: str,
        status: RolloverStatus,
        error_message: str | None = None,
        close_fill_price: Decimal | None = None,
        open_fill_price: Decimal | None = None,
    ) -> bool:
        """
        Update the status of a rollover event.

        Args:
            event_id: Event ID to update
            status: New status
            error_message: Error message if failed
            close_fill_price: Fill price for close order
            open_fill_price: Fill price for open order

        Returns:
            True if event was found and updated
        """
        for event in self._events:
            if event.event_id == event_id:
                event.status = status
                if error_message:
                    event.error_message = error_message
                if close_fill_price is not None:
                    event.close_fill_price = close_fill_price
                if open_fill_price is not None:
                    event.open_fill_price = open_fill_price
                if status in (RolloverStatus.COMPLETED, RolloverStatus.FAILED):
                    event.completed_at = datetime.now(timezone.utc)

                self._logger.info(
                    'rollover_status_updated',
                    extra={
                        'event_id': event_id,
                        'status': status.value,
                        'error': error_message,
                    },
                )
                return True

        return False

    def get_rollover_history(self) -> list[RolloverEvent]:
        """Get rollover event history."""
        return list(self._events)

    def get_pending_rollovers(self) -> list[RolloverEvent]:
        """Get rollovers that are pending or in progress."""
        return [
            event
            for event in self._events
            if event.status in (RolloverStatus.PENDING, RolloverStatus.IN_PROGRESS)
        ]

    def _load_mappings(self) -> None:
        """Load symbol mappings from disk."""
        path = Path(self.config.mappings_path)
        if not path.exists():
            return

        try:
            with path.open('r', encoding='utf-8') as f:
                data = json.load(f)

            for symbol, mapping_data in data.get('mappings', {}).items():
                if not isinstance(mapping_data, dict):
                    continue

                spec = FuturesContractSpec(
                    symbol=mapping_data.get('actual_contract', symbol),
                    sec_type='FUT',
                    exchange=mapping_data.get('exchange', 'CME'),
                    currency=mapping_data.get('currency', 'USD'),
                    multiplier=mapping_data.get('multiplier'),
                    expiration_date=mapping_data.get('expiration_date'),
                    con_id=mapping_data.get('con_id'),
                    underlying=symbol,
                )

                updated_at_str = mapping_data.get('updated_at')
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str)
                    except ValueError:
                        updated_at = datetime.now(timezone.utc)
                else:
                    updated_at = datetime.now(timezone.utc)

                self._mappings[symbol] = SymbolMapping(
                    logical_symbol=symbol,
                    actual_contract=spec.symbol,
                    contract_spec=spec,
                    is_front_month=mapping_data.get('is_front_month', False),
                    updated_at=updated_at,
                )

            self._logger.info(
                'mappings_loaded',
                extra={'count': len(self._mappings)},
            )

        except Exception as exc:
            self._logger.warning(
                'failed_to_load_mappings',
                extra={'error': str(exc)},
            )

    def _save_mappings(self) -> None:
        """Save symbol mappings to disk."""
        data: dict[str, object] = {
            'version': '1.0',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'mappings': {},
        }

        mappings_dict: dict[str, dict[str, object]] = {}
        for symbol, mapping in self._mappings.items():
            mappings_dict[symbol] = {
                'actual_contract': mapping.actual_contract,
                'expiration_date': mapping.contract_spec.expiration_date,
                'con_id': mapping.contract_spec.con_id,
                'exchange': mapping.contract_spec.exchange,
                'currency': mapping.contract_spec.currency,
                'multiplier': mapping.contract_spec.multiplier,
                'is_front_month': mapping.is_front_month,
                'updated_at': mapping.updated_at.isoformat(),
            }
        data['mappings'] = mappings_dict

        path = Path(self.config.mappings_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            self._logger.info(
                'mappings_saved',
                extra={'count': len(self._mappings), 'path': str(path)},
            )
        except Exception as exc:
            self._logger.error(
                'failed_to_save_mappings',
                extra={'error': str(exc)},
            )
