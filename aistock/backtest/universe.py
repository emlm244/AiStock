"""
Historical universe manager for survivorship bias protection.

This module ensures backtests only trade symbols that were actually
available on each historical date, preventing survivorship bias.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..providers.massive import MassiveDataProvider

logger = logging.getLogger(__name__)


class TickerEventType(str, Enum):
    """Types of ticker lifecycle events."""

    IPO = 'ipo'
    DELISTED = 'delisted'
    TICKER_CHANGE = 'ticker_change'
    MERGER = 'merger'
    SPINOFF = 'spinoff'
    ACQUISITION = 'acquisition'


@dataclass
class TickerEvent:
    """Record of a ticker lifecycle event."""

    symbol: str
    event_type: TickerEventType
    event_date: date
    old_symbol: str | None = None  # For ticker changes
    new_symbol: str | None = None  # For ticker changes
    related_symbol: str | None = None  # For mergers/spinoffs
    description: str = ''


@dataclass
class TickerLifecycle:
    """
    Complete lifecycle information for a ticker.

    Tracks when a symbol was available for trading.
    """

    symbol: str
    ipo_date: date | None = None
    delisting_date: date | None = None
    ticker_changes: list[TickerEvent] = field(default_factory=list)
    is_active: bool = True

    def was_tradeable_on(self, check_date: date) -> bool:
        """Check if symbol was tradeable on a specific date."""
        return (not self.ipo_date or check_date >= self.ipo_date) and (
            not self.delisting_date or check_date <= self.delisting_date
        )

    def was_tradeable_during(self, start_date: date, end_date: date) -> tuple[bool, str]:
        """
        Check if symbol was tradeable throughout a date range.

        Returns:
            Tuple of (is_tradeable, reason_if_not).
        """
        # Check IPO date
        if self.ipo_date and start_date < self.ipo_date:
            return (False, f'IPO date {self.ipo_date} is after start_date {start_date}')

        # Check delisting date
        if self.delisting_date and end_date > self.delisting_date:
            return (False, f'Delisted on {self.delisting_date} before end_date {end_date}')

        # Check for ticker changes during period
        for event in self.ticker_changes:
            if start_date <= event.event_date <= end_date:
                return (
                    False,
                    f'Ticker changed on {event.event_date}: {event.old_symbol} -> {event.new_symbol}',
                )

        return (True, '')


@dataclass
class SymbolValidation:
    """Validation result for a single symbol."""

    symbol: str
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    lifecycle: TickerLifecycle | None = None


@dataclass
class UniverseValidationResult:
    """Result of validating a backtest universe."""

    is_valid: bool
    total_symbols: int = 0
    valid_symbols: int = 0
    invalid_symbols: int = 0
    symbols_with_warnings: int = 0

    validations: dict[str, SymbolValidation] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # Recommended actions
    symbols_to_exclude: list[str] = field(default_factory=list)
    symbols_to_adjust: dict[str, dict[str, date]] = field(default_factory=dict)

    def get_valid_symbols(self) -> list[str]:
        """Get list of symbols that passed validation."""
        return [symbol for symbol, v in self.validations.items() if v.is_valid and not v.errors]


class HistoricalUniverseManager:
    """
    Manages point-in-time universe reconstruction.

    This class prevents survivorship bias by:
    1. Tracking IPO dates - excluding symbols that didn't exist yet
    2. Tracking delistings - excluding symbols that no longer trade
    3. Tracking ticker changes - handling symbol renames (FB -> META)
    4. Validating symbol availability for any historical period
    """

    def __init__(self, include_unknown_symbols: bool = False) -> None:
        """Initialize the universe manager."""
        self._lifecycles: dict[str, TickerLifecycle] = {}
        self._events: list[TickerEvent] = []
        self._loaded = False
        self._include_unknown_symbols = include_unknown_symbols

    def load_from_massive(
        self,
        provider: MassiveDataProvider,
        force_refresh: bool = False,
    ) -> None:
        """
        Load lifecycle data from Massive.com corporate actions.

        Args:
            provider: MassiveDataProvider instance.
            force_refresh: Force reload even if already loaded.
        """
        if self._loaded and not force_refresh:
            return

        logger.info('Loading universe lifecycle data from Massive.com...')

        # Load IPOs
        ipos_result = provider.fetch_corporate_actions('ipos')
        if ipos_result.success:
            for ipo in ipos_result.data:
                symbol = ipo.get('ticker', '')
                if not symbol:
                    continue

                listing_date_str = ipo.get('listing_date', ipo.get('ipo_date', ''))
                if listing_date_str:
                    try:
                        ipo_date = date.fromisoformat(listing_date_str)
                        if symbol not in self._lifecycles:
                            self._lifecycles[symbol] = TickerLifecycle(symbol=symbol)
                        self._lifecycles[symbol].ipo_date = ipo_date

                        self._events.append(
                            TickerEvent(
                                symbol=symbol,
                                event_type=TickerEventType.IPO,
                                event_date=ipo_date,
                                description=ipo.get('name', ''),
                            )
                        )
                    except ValueError:
                        logger.warning(f'Invalid IPO date for {symbol}: {listing_date_str}')

            logger.info(f'Loaded {len(ipos_result.data)} IPO records')

        # Load ticker events (symbol changes, delistings)
        events_result = provider.fetch_corporate_actions('ticker_events')
        if events_result.success:
            for event in events_result.data:
                ticker = event.get('ticker', '')
                event_type = event.get('type', '').lower()
                event_date_str = event.get('date', '')

                if not ticker or not event_date_str:
                    continue

                try:
                    event_date = date.fromisoformat(event_date_str)
                except ValueError:
                    continue

                if ticker not in self._lifecycles:
                    self._lifecycles[ticker] = TickerLifecycle(symbol=ticker)

                lifecycle = self._lifecycles[ticker]

                if event_type == 'delisted':
                    lifecycle.delisting_date = event_date
                    lifecycle.is_active = False
                    self._events.append(
                        TickerEvent(
                            symbol=ticker,
                            event_type=TickerEventType.DELISTED,
                            event_date=event_date,
                        )
                    )

                elif event_type == 'ticker_change':
                    new_ticker = event.get('new_ticker', '')
                    ticker_event = TickerEvent(
                        symbol=ticker,
                        event_type=TickerEventType.TICKER_CHANGE,
                        event_date=event_date,
                        old_symbol=ticker,
                        new_symbol=new_ticker,
                    )
                    lifecycle.ticker_changes.append(ticker_event)
                    self._events.append(ticker_event)

            logger.info(f'Loaded {len(events_result.data)} ticker event records')

        self._loaded = True
        logger.info(f'Universe manager loaded {len(self._lifecycles)} symbol lifecycles')

    def add_manual_lifecycle(self, lifecycle: TickerLifecycle) -> None:
        """
        Add or update a lifecycle manually.

        Useful for adding custom data not available from Massive.com.
        """
        self._lifecycles[lifecycle.symbol] = lifecycle

    def get_lifecycle(self, symbol: str) -> TickerLifecycle | None:
        """Get lifecycle information for a symbol."""
        return self._lifecycles.get(symbol)

    def validate_symbol(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> SymbolValidation:
        """
        Validate a single symbol for a date range.

        Args:
            symbol: Ticker symbol to validate.
            start_date: Backtest start date.
            end_date: Backtest end date.

        Returns:
            SymbolValidation with results.
        """
        validation = SymbolValidation(symbol=symbol, is_valid=True)

        lifecycle = self._lifecycles.get(symbol)
        if not lifecycle:
            # No lifecycle data - warn but don't invalidate
            validation.warnings.append(f'No lifecycle data for {symbol}. Cannot verify survivorship bias.')
            return validation

        validation.lifecycle = lifecycle

        # Check tradeability
        is_tradeable, reason = lifecycle.was_tradeable_during(start_date, end_date)
        if not is_tradeable:
            validation.is_valid = False
            validation.errors.append(reason)

        # Additional warnings
        if lifecycle.ipo_date:
            days_since_ipo = (start_date - lifecycle.ipo_date).days
            if 0 < days_since_ipo < 30:
                validation.warnings.append(
                    f'{symbol} IPO was only {days_since_ipo} days before start_date. Limited historical data available.'
                )

        if lifecycle.delisting_date:
            days_until_delist = (lifecycle.delisting_date - end_date).days
            if 0 < days_until_delist < 30:
                validation.warnings.append(
                    f'{symbol} delisted {days_until_delist} days after end_date. Company may have been in distress.'
                )

        return validation

    def validate_backtest_universe(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> UniverseValidationResult:
        """
        Validate an entire backtest universe.

        Args:
            symbols: List of symbols to validate.
            start_date: Backtest start date.
            end_date: Backtest end date.

        Returns:
            UniverseValidationResult with comprehensive validation results.
        """
        result = UniverseValidationResult(
            is_valid=True,
            total_symbols=len(symbols),
        )

        for symbol in symbols:
            validation = self.validate_symbol(symbol, start_date, end_date)
            result.validations[symbol] = validation

            if validation.is_valid:
                result.valid_symbols += 1
            else:
                result.invalid_symbols += 1
                result.symbols_to_exclude.append(symbol)
                for error in validation.errors:
                    result.errors.append(f'{symbol}: {error}')

            if validation.warnings:
                result.symbols_with_warnings += 1
                for warning in validation.warnings:
                    result.warnings.append(f'{symbol}: {warning}')

        # Overall validation status
        if result.invalid_symbols > 0:
            result.is_valid = False

        if result.invalid_symbols > 0:
            logger.warning(
                f'Universe validation: {result.invalid_symbols}/{result.total_symbols} symbols failed validation'
            )

        return result

    def reconstruct_universe_at_time(
        self,
        timestamp: datetime | date,
        candidate_symbols: list[str] | None = None,
    ) -> frozenset[str]:
        """
        Reconstruct the universe of tradeable symbols at a specific point in time.

        Args:
            timestamp: Historical timestamp or date.
            candidate_symbols: Optional list of symbols to filter from.
                             If None, uses all known symbols.
            include_unknown_symbols: Whether to include symbols without lifecycle data.

        Returns:
            Frozen set of symbols that were tradeable at the timestamp.
        """
        check_date = timestamp.date() if isinstance(timestamp, datetime) else timestamp
        candidates = candidate_symbols or list(self._lifecycles.keys())

        active_symbols: set[str] = set()

        for symbol in candidates:
            lifecycle = self._lifecycles.get(symbol)
            if lifecycle is None:
                if self._include_unknown_symbols:
                    active_symbols.add(symbol)
                else:
                    logger.warning('Skipping %s due to missing lifecycle data', symbol)
                continue

            if lifecycle.was_tradeable_on(check_date):
                active_symbols.add(symbol)

        return frozenset(active_symbols)

    def get_events_in_period(
        self,
        start_date: date,
        end_date: date,
        event_types: list[TickerEventType] | None = None,
    ) -> list[TickerEvent]:
        """
        Get all ticker events in a date range.

        Args:
            start_date: Start of period.
            end_date: End of period.
            event_types: Optional filter for specific event types.

        Returns:
            List of TickerEvent objects in the period.
        """
        events = [e for e in self._events if start_date <= e.event_date <= end_date]

        if event_types:
            events = [e for e in events if e.event_type in event_types]

        return sorted(events, key=lambda e: e.event_date)

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about loaded lifecycle data."""
        active_count = sum(1 for lc in self._lifecycles.values() if lc.is_active)
        with_ipo_date = sum(1 for lc in self._lifecycles.values() if lc.ipo_date)
        delisted_count = sum(1 for lc in self._lifecycles.values() if lc.delisting_date)

        event_counts: dict[str, int] = {}
        for event in self._events:
            event_counts[event.event_type.value] = event_counts.get(event.event_type.value, 0) + 1

        return {
            'total_symbols': len(self._lifecycles),
            'active_symbols': active_count,
            'delisted_symbols': delisted_count,
            'with_ipo_date': with_ipo_date,
            'total_events': len(self._events),
            'event_counts': event_counts,
            'is_loaded': self._loaded,
        }
