"""Market data service for unified data access."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ..data import Bar

if TYPE_CHECKING:
    from ..interfaces.market_data import MarketDataProviderProtocol


class MarketDataService:
    """Unified market data access service.

    Provides a clean API for accessing market data from multiple sources.
    """

    def __init__(self, providers: dict[str, MarketDataProviderProtocol]):
        """Initialize with data providers.

        Args:
            providers: Dict of provider_name -> provider_instance
        """
        self.providers = providers
        self.logger = logging.getLogger(__name__)

    def get_bars(
        self,
        symbol: str,
        timeframe: str = '1m',
        lookback: int = 100,
        provider: str = 'primary',
    ) -> list[Bar]:
        """Get historical bars."""
        if provider not in self.providers:
            self.logger.warning(f'Provider {provider} not found, using first available')
            provider = next(iter(self.providers.keys()))

        provider_instance = self.providers[provider]
        return provider_instance.get_bars(symbol, timeframe, lookback)

    def get_latest_price(self, symbol: str, provider: str = 'primary') -> Decimal | None:
        """Get latest price for a symbol."""
        bars = self.get_bars(symbol, lookback=1, provider=provider)
        if bars:
            return bars[-1].close
        return None

    def get_market_snapshot(
        self,
        symbols: list[str],
        timeframes: list[str] | None = None,
        provider: str = 'primary',
    ) -> dict[str, dict[str, list[Bar]]]:
        """Get multi-symbol, multi-timeframe snapshot.

        Returns:
            Dict of symbol -> timeframe -> bars
        """
        timeframes = timeframes or ['1m']
        snapshot: dict[str, dict[str, list[Bar]]] = {}

        for symbol in symbols:
            snapshot[symbol] = {}
            for tf in timeframes:
                try:
                    bars = self.get_bars(symbol, tf, lookback=100, provider=provider)
                    snapshot[symbol][tf] = bars
                except Exception as exc:
                    self.logger.warning(f'Failed to get {symbol} {tf}: {exc}')
                    snapshot[symbol][tf] = []

        return snapshot

    def check_data_quality(
        self,
        symbol: str,
        timeframe: str = '1m',
        min_bars: int = 20,
        provider: str = 'primary',
    ) -> dict[str, Any]:
        """Check data quality for a symbol.

        Returns:
            Dict with 'sufficient', 'bar_count', 'has_gaps', 'issues'
        """
        provider_instance = self.providers.get(provider)
        if not provider_instance:
            return {'sufficient': False, 'bar_count': 0, 'issues': ['provider_not_found']}

        if not provider_instance.has_sufficient_data(symbol, min_bars):
            return {'sufficient': False, 'bar_count': 0, 'issues': ['insufficient_data']}

        bars = provider_instance.get_bars(symbol, timeframe, lookback=min_bars * 2)

        issues = []
        if len(bars) < min_bars:
            issues.append(f'only_{len(bars)}_bars')

        # Check for gaps
        has_gaps = False
        if len(bars) >= 2:
            expected_interval = 60  # 1 minute for '1m'
            for i in range(1, len(bars)):
                time_diff = (bars[i].timestamp - bars[i - 1].timestamp).total_seconds()
                if time_diff > expected_interval * 2:
                    has_gaps = True
                    issues.append('time_gaps_detected')
                    break

        return {
            'sufficient': len(bars) >= min_bars and not issues,
            'bar_count': len(bars),
            'has_gaps': has_gaps,
            'issues': issues,
        }

    def add_provider(self, name: str, provider: MarketDataProviderProtocol) -> None:
        """Add a new data provider."""
        self.providers[name] = provider
        self.logger.info(f'Added market data provider: {name}')

    def remove_provider(self, name: str) -> None:
        """Remove a data provider."""
        if name in self.providers:
            del self.providers[name]
            self.logger.info(f'Removed market data provider: {name}')
