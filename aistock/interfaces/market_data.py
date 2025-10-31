"""Market data provider protocol interface."""

from __future__ import annotations

from typing import Protocol

from ..data import Bar


class MarketDataProviderProtocol(Protocol):
    """Protocol defining the market data provider interface.

    This allows swapping data sources (live, historical, simulated)
    without changing the trading logic.
    """

    def get_bars(
        self,
        symbol: str,
        timeframe: str = '1m',
        lookback: int = 100,
    ) -> list[Bar]:
        """Get historical bars for a symbol."""
        ...

    def has_sufficient_data(self, symbol: str, min_bars: int = 20) -> bool:
        """Check if sufficient data is available."""
        ...

    def add_bar(self, symbol: str, timeframe: str, bar: Bar) -> None:
        """Add a new bar to the data store."""
        ...

    def get_latest_bar(self, symbol: str, timeframe: str = '1m') -> Bar | None:
        """Get the most recent bar."""
        ...
