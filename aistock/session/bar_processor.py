"""Bar processing and ingestion."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from ..data import Bar

if TYPE_CHECKING:
    from ..interfaces.market_data import MarketDataProviderProtocol


class BarProcessor:
    """Processes incoming market bars and manages history.

    Responsibilities:
    - Bar ingestion and validation
    - Multi-timeframe bar management
    - Price tracking
    - Thread-safe bar storage
    """

    def __init__(
        self,
        timeframe_manager: MarketDataProviderProtocol | None = None,
        warmup_bars: int = 500,
    ):
        self.timeframe_manager = timeframe_manager
        self.warmup_bars = warmup_bars

        # State
        self.history: dict[str, list[Bar]] = defaultdict(list)
        self.last_prices: dict[str, Decimal] = {}
        self._lock = threading.Lock()

        self.logger = logging.getLogger(__name__)

    def process_bar(
        self,
        timestamp: datetime,
        symbol: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        timeframe: str = '1m',
    ) -> Bar:
        """Process and store a new bar."""
        bar = Bar(
            symbol=symbol,
            timestamp=timestamp,
            open=Decimal(str(open_)),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal(str(close)),
            volume=int(volume),
        )

        with self._lock:
            # Add to history
            history = self.history[symbol]
            history.append(bar)

            # Keep bounded
            max_history = self.warmup_bars * 5
            if len(history) > max_history:
                del history[: len(history) - max_history]

            # Update price
            self.last_prices[symbol] = bar.close

        # Feed to timeframe manager
        if self.timeframe_manager:
            self.timeframe_manager.add_bar(symbol, timeframe, bar)

        return bar

    def get_history(self, symbol: str) -> list[Bar]:
        """Get history for a symbol (thread-safe copy)."""
        with self._lock:
            return list(self.history.get(symbol, []))

    def get_last_price(self, symbol: str) -> Decimal | None:
        """Get last price for a symbol."""
        with self._lock:
            return self.last_prices.get(symbol)

    def get_all_prices(self) -> dict[str, Decimal]:
        """Get all last prices (thread-safe copy)."""
        with self._lock:
            return dict(self.last_prices)

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update last price for a symbol (thread-safe).

        Used for fill price updates when fills occur between bars.
        """
        with self._lock:
            self.last_prices[symbol] = price
