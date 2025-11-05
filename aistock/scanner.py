"""
IBKR Market Scanner - Discover tradeable stocks dynamically

Scans the live stock market using IBKR's scanner API to discover
stocks matching specific criteria (liquidity, price range, volume).
"""
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

try:
    from typing import Unpack  # Python 3.11+
except ImportError:
    from typing_extensions import Unpack  # Python 3.9-3.10

from .logging import configure_logger

IBAPI_AVAILABLE = False
if TYPE_CHECKING:
    # For type checking only
    from ibapi.client import EClient as _EClient
    from ibapi.contract import ContractDetails as _ContractDetails
    from ibapi.wrapper import EWrapper as _EWrapper

    BaseClient = _EClient
    BaseWrapper = _EWrapper
    ContractDetails = _ContractDetails
else:  # runtime imports guarded
    try:  # pragma: no cover - import at runtime when ibapi installed
        from ibapi.client import EClient as BaseClient  # type: ignore
        from ibapi.contract import ContractDetails as ContractDetails  # type: ignore
        from ibapi.wrapper import EWrapper as BaseWrapper  # type: ignore

        IBAPI_AVAILABLE = True
    except Exception:

        class BaseWrapper:  # type: ignore[misc]
            pass

        class BaseClient:  # type: ignore[misc]
            def __init__(self, *args, **kwargs):
                pass

            def connect(self, host: str, port: int, client_id: int) -> None:
                pass

            def disconnect(self) -> None:
                pass

            def run(self) -> None:
                pass

            def reqScannerSubscription(
                self, reqId: int, subscription, scannerSubscriptionOptions, scannerSubscriptionFilterOptions
            ) -> None:
                pass

            def cancelScannerSubscription(self, reqId: int) -> None:
                pass

        ContractDetails = Any  # type: ignore[misc]


class ContractLike(Protocol):
    symbol: str
    conId: int  # noqa: N815 - IBKR API convention
    exchange: str
    currency: str


class ContractDetailsLike(Protocol):
    contract: ContractLike


# Ensure public names exist for tests/mocking regardless of IBAPI availability
EClient = BaseClient  # type: ignore[misc]
EWrapper = BaseWrapper  # type: ignore[misc]


@dataclass
class ScannerFilter:
    """
    Filter criteria for market scanner.

    Designed to match FSD requirements:
    - Liquidity filters ensure tradeable stocks
    - Price range matches FSD config
    - Instrument filters ensure stocks only (no options/futures)
    """

    # Price range
    min_price: float = 1.0
    max_price: float = 10000.0

    # Liquidity (average daily volume)
    min_volume: int = 100000  # 100K shares/day minimum

    # Market cap filters
    min_market_cap: float | None = None  # In millions, e.g., 100 = $100M

    # Sector filters (optional)
    include_sectors: list[str] = field(default_factory=list)  # e.g., ["Technology", "Healthcare"]
    exclude_sectors: list[str] = field(default_factory=list)

    # Stock type filters
    stock_types: list[str] = field(default_factory=lambda: ['STOCK'])  # STOCK, ETF, etc.

    # Exchange filters
    exchanges: list[str] = field(default_factory=lambda: ['SMART'])  # SMART, NYSE, NASDAQ, etc.

    # Maximum results
    max_results: int = 100

    # Scanner parameters
    instrument: str = 'STK'  # Stock
    location_code: str = 'STK.US'  # US stocks
    scan_code: str = 'TOP_PERC_GAIN'  # Most active, top gainers, etc.

    # Additional filters
    above_price: float | None = None
    below_price: float | None = None
    above_volume: int | None = None
    market_cap_above: float | None = None
    market_cap_below: float | None = None


@dataclass
class ScannedStock:
    """Result from market scanner."""

    symbol: str
    contract_id: int
    exchange: str
    currency: str

    # Market data
    price: float | None = None
    volume: int | None = None
    market_cap: float | None = None

    # Ranking
    rank: int = 0
    distance: str = ''  # Distance from filter criteria

    # Additional info
    sector: str | None = None
    industry: str | None = None


class MarketScanner(BaseWrapper, BaseClient):  # pragma: no cover - requires IBKR connection
    """
    IBKR Market Scanner for dynamic stock discovery.

    Usage:
        scanner = MarketScanner(host="127.0.0.1", port=7497, client_id=2)
        scanner.connect_and_scan(filter_criteria)
        results = scanner.get_results()
        scanner.disconnect()
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 2):
        if not IBAPI_AVAILABLE:
            raise RuntimeError('ibapi is not installed. Install via: pip install ibapi')

        BaseWrapper.__init__(self)
        BaseClient.__init__(self, self)

        self.host = host
        self.port = port
        self.client_id = client_id

        self.logger = configure_logger('MarketScanner', structured=True)

        # State
        self._connected = threading.Event()
        self._scan_complete = threading.Event()
        self._thread: threading.Thread | None = None

        # Results
        self._scanned_stocks: list[ScannedStock] = []
        self._req_id = 7000  # Scanner request ID

        # Contract details cache
        self._contract_details: dict[int, ContractDetails] = {}
        self._details_complete = threading.Event()

    # --- Connection Management ---

    def connect_and_scan(self, scanner_filter: ScannerFilter, timeout: float = 30.0) -> list[ScannedStock]:
        """
        Connect to IBKR, perform scan, and return results.

        Args:
            scanner_filter: Filter criteria for scanning
            timeout: Maximum time to wait for results (seconds)

        Returns:
            List of scanned stocks matching criteria
        """
        try:
            self._connect(timeout=10.0)
            self._perform_scan(scanner_filter, timeout=timeout)
            return self._scanned_stocks
        finally:
            self.disconnect()

    def _connect(self, timeout: float = 10.0) -> None:
        """Connect to IBKR."""
        self.logger.info('scanner_connecting', extra={'host': self.host, 'port': self.port})

        self.connect(self.host, self.port, self.client_id)  # type: ignore

        # Start message processing thread
        self._thread = threading.Thread(target=self.run, daemon=True, name='ScannerThread')
        self._thread.start()

        # Wait for connection
        if not self._connected.wait(timeout):
            raise TimeoutError(f'Failed to connect to IBKR within {timeout}s')

        self.logger.info('scanner_connected')

    def _perform_scan(self, scanner_filter: ScannerFilter, timeout: float = 30.0) -> None:
        """Perform market scan with given filter."""
        self.logger.info(
            'scanner_starting',
            extra={
                'min_price': scanner_filter.min_price,
                'max_price': scanner_filter.max_price,
                'min_volume': scanner_filter.min_volume,
                'max_results': scanner_filter.max_results,
                'scan_code': scanner_filter.scan_code,
            },
        )

        # Build scanner subscription
        try:
            from ibapi.scanner import ScannerSubscription
        except Exception as exc:  # pragma: no cover - when ibapi missing
            raise RuntimeError('ibapi.scanner not available') from exc

        subscription = ScannerSubscription()
        subscription.instrument = scanner_filter.instrument
        subscription.locationCode = scanner_filter.location_code
        subscription.scanCode = scanner_filter.scan_code

        # Apply price filters
        if scanner_filter.above_price or scanner_filter.min_price:
            subscription.abovePrice = scanner_filter.above_price or scanner_filter.min_price
        if scanner_filter.below_price or scanner_filter.max_price:
            subscription.belowPrice = scanner_filter.below_price or scanner_filter.max_price

        # Apply volume filter
        if scanner_filter.above_volume or scanner_filter.min_volume:
            subscription.aboveVolume = scanner_filter.above_volume or scanner_filter.min_volume

        # Apply market cap filters (guard Nones for type safety)
        if scanner_filter.market_cap_above is not None:
            subscription.marketCapAbove = scanner_filter.market_cap_above
        elif scanner_filter.min_market_cap is not None:
            subscription.marketCapAbove = scanner_filter.min_market_cap
        if scanner_filter.market_cap_below is not None:
            subscription.marketCapBelow = scanner_filter.market_cap_below

        # Number of results
        subscription.numberOfRows = scanner_filter.max_results

        # Request scan
        self._scan_complete.clear()
        self._scanned_stocks.clear()

        self.reqScannerSubscription(self._req_id, subscription, [], [])  # type: ignore

        # Wait for results
        if not self._scan_complete.wait(timeout):
            self.logger.warning('scanner_timeout', extra={'timeout': timeout})

        self.logger.info(
            'scanner_complete',
            extra={'stocks_found': len(self._scanned_stocks)},
        )

    # --- EWrapper Callbacks ---

    def connectAck(self) -> None:
        """Connection acknowledged."""
        self._connected.set()

    def scannerData(
        self,
        reqId: int,
        rank: int,
        contractDetails: ContractDetailsLike | Any,
        distance: str,
        benchmark: str,
        projection: str,
        legsStr: str,
    ) -> None:
        """Scanner data received."""
        if reqId != self._req_id:
            return

        contract = getattr(contractDetails, 'contract', None)
        if not contract:
            return

        c: ContractLike = contract  # type: ignore[assignment]
        stock = ScannedStock(
            symbol=c.symbol,
            contract_id=c.conId,
            exchange=c.exchange,
            currency=c.currency,
            rank=rank,
            distance=distance,
        )

        self._scanned_stocks.append(stock)

        self.logger.debug(
            'scanner_result',
            extra={
                'rank': rank,
                'symbol': stock.symbol,
                'exchange': stock.exchange,
            },
        )

    def scannerDataEnd(self, reqId: int) -> None:
        """Scanner data complete."""
        if reqId != self._req_id:
            return

        self.cancelScannerSubscription(reqId)
        self._scan_complete.set()

        self.logger.info('scanner_data_complete', extra={'results': len(self._scanned_stocks)})

    def error(self, reqId: int, errorCode: int, errorString: str, advanced_order_reject_json: str = '') -> None:
        """Error handling."""
        self.logger.error(
            'scanner_error',
            extra={
                'req_id': reqId,
                'error_code': errorCode,
                'error_string': errorString,
            },
        )

        # Critical errors
        if errorCode in (502, 503, 504):  # Connection errors
            self._connected.clear()

        # Scanner-specific errors
        if reqId == self._req_id:
            self._scan_complete.set()  # Unblock waiting thread

    # --- Utility Methods ---

    def get_results(self) -> list[ScannedStock]:
        """Get scan results."""
        return self._scanned_stocks.copy()

    def get_symbols(self) -> list[str]:
        """Get list of symbols from scan results."""
        return [stock.symbol for stock in self._scanned_stocks]


# --- Convenience Functions ---


def scan_market(
    scanner_filter: ScannerFilter | None = None,
    host: str = '127.0.0.1',
    port: int = 7497,
    client_id: int = 2,
    timeout: float = 30.0,
) -> list[ScannedStock]:
    """
    Convenience function to scan market with default or custom filters.

    Args:
        scanner_filter: Filter criteria (uses defaults if None)
        host: IBKR host
        port: IBKR port (7497 for paper, 7496 for live)
        client_id: Unique client ID
        timeout: Scan timeout in seconds

    Returns:
        List of scanned stocks

    Example:
        # Scan for liquid, mid-priced stocks
        results = scan_market(ScannerFilter(
            min_price=10.0,
            max_price=500.0,
            min_volume=500000,
            max_results=50
        ))

        symbols = [stock.symbol for stock in results]
        print(f"Found {len(symbols)} stocks: {symbols}")
    """
    if scanner_filter is None:
        scanner_filter = ScannerFilter()

    scanner = MarketScanner(host=host, port=port, client_id=client_id)

    try:
        results = scanner.connect_and_scan(scanner_filter, timeout=timeout)
        return results
    except Exception as e:
        scanner.logger.error('scan_market_failed', extra={'error': str(e)})
        return []


class ScannerExtra(TypedDict, total=False):
    above_price: float
    below_price: float
    above_volume: int
    market_cap_above: float
    market_cap_below: float
    include_sectors: list[str]
    exclude_sectors: list[str]
    stock_types: list[str]
    exchanges: list[str]
    instrument: str
    location_code: str
    scan_code: str


def scan_for_fsd(
    min_price: float = 1.0,
    max_price: float = 10000.0,
    min_volume: int = 100000,
    max_results: int = 100,
    **kwargs: Unpack[ScannerExtra],
) -> list[str]:
    """
    Scan market with FSD-optimized filters.

    Returns symbols ready for FSD trading.

    Args:
        min_price: Minimum stock price
        max_price: Maximum stock price
        min_volume: Minimum daily volume
        max_results: Maximum number of stocks to return
        **kwargs: Additional ScannerFilter parameters

    Returns:
        List of stock symbols

    Example:
        symbols = scan_for_fsd(
            min_price=5.0,
            max_price=500.0,
            min_volume=500000,
            max_results=50
        )
    """
    scanner_filter = ScannerFilter(
        min_price=min_price,
        max_price=max_price,
        min_volume=min_volume,
        max_results=max_results,
        **kwargs,
    )

    results = scan_market(scanner_filter)
    return [stock.symbol for stock in results]


__all__ = [
    'MarketScanner',
    'ScannerFilter',
    'ScannedStock',
    'scan_market',
    'scan_for_fsd',
]
