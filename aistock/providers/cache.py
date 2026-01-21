"""
Disk caching layer for Massive.com data.

Stores fetched data locally to avoid repeated API calls and respect rate limits.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..data import Bar


logger = logging.getLogger(__name__)


@dataclass
class CacheMetadata:
    """Metadata for a cached data file."""

    symbol: str
    start_date: str  # ISO format
    end_date: str  # ISO format
    timespan: str
    fetch_timestamp: str  # ISO format
    record_count: int


class MassiveCache:
    """
    Local disk cache for Massive.com data.

    Cache structure:
        {cache_dir}/
            stocks/
                AAPL/
                    2024-01_minute.json
                    2024-02_minute.json
            futures/
                ESH26/
                    2024-01_minute.json
            corporate_actions/
                ipos.json
                splits.json
                dividends.json
                ticker_events.json
            metadata/
                cache_index.json
    """

    def __init__(self, cache_dir: str | Path = 'data/massive_cache') -> None:
        """
        Initialize the cache.

        Args:
            cache_dir: Directory to store cached data.
        """
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self._cache_dir / 'stocks').mkdir(exist_ok=True)
        (self._cache_dir / 'futures').mkdir(exist_ok=True)
        (self._cache_dir / 'corporate_actions').mkdir(exist_ok=True)
        (self._cache_dir / 'metadata').mkdir(exist_ok=True)

        self._index_path = self._cache_dir / 'metadata' / 'cache_index.json'
        self._index: dict[str, CacheMetadata] = self._load_index()

    def _load_index(self) -> dict[str, CacheMetadata]:
        """Load cache index from disk."""
        if not self._index_path.exists():
            return {}

        try:
            with open(self._index_path) as f:
                data = json.load(f)
            return {k: CacheMetadata(**v) for k, v in data.items()}
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f'Failed to load cache index: {e}')
            return {}

    def _save_index(self) -> None:
        """Save cache index to disk."""
        data = {k: asdict(v) for k, v in self._index.items()}
        with open(self._index_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _rebuild_index(self) -> None:
        """Rebuild the cache index from cached files on disk."""
        self._index.clear()
        for asset_type in ('stocks', 'futures'):
            asset_dir = self._cache_dir / asset_type
            if not asset_dir.exists():
                continue
            for symbol_dir in asset_dir.iterdir():
                if not symbol_dir.is_dir():
                    continue
                for cache_path in symbol_dir.glob('*.json'):
                    name = cache_path.stem
                    if '_' not in name:
                        continue
                    _, timespan = name.split('_', 1)
                    try:
                        with open(cache_path) as f:
                            month_data = json.load(f)
                    except (OSError, json.JSONDecodeError) as e:
                        logger.warning(f'Failed to rebuild cache index from {cache_path}: {e}')
                        continue
                    if not month_data:
                        continue

                    timestamps: list[datetime] = []
                    for bar_dict in month_data:
                        try:
                            ts = datetime.fromisoformat(bar_dict['timestamp'])
                        except (KeyError, ValueError, TypeError):
                            continue
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        else:
                            ts = ts.astimezone(timezone.utc)
                        timestamps.append(ts)
                    if not timestamps:
                        continue

                    start_ts = min(timestamps)
                    end_ts = max(timestamps)
                    symbol = month_data[0].get('symbol', symbol_dir.name)
                    key = self._get_cache_key(symbol, start_ts.date(), end_ts.date(), timespan, asset_type)
                    self._index[key] = CacheMetadata(
                        symbol=symbol,
                        start_date=start_ts.date().isoformat(),
                        end_date=end_ts.date().isoformat(),
                        timespan=timespan,
                        fetch_timestamp=datetime.now(timezone.utc).isoformat(),
                        record_count=len(month_data),
                    )

        self._save_index()

    def _get_cache_key(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timespan: str,
        asset_type: str = 'stocks',
    ) -> str:
        """Generate a unique cache key."""
        key_str = f'{asset_type}:{symbol}:{start_date.isoformat()}:{end_date.isoformat()}:{timespan}'
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def _get_cache_path(
        self,
        symbol: str,
        year_month: str,
        timespan: str,
        asset_type: str = 'stocks',
    ) -> Path:
        """Get the file path for cached data."""
        # Sanitize symbol for filesystem (e.g., ES/H26 -> ES_H26)
        safe_symbol = symbol.replace('/', '_').replace('\\', '_')
        return self._cache_dir / asset_type / safe_symbol / f'{year_month}_{timespan}.json'

    def has_cached_data(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timespan: str = 'minute',
        asset_type: str = 'stocks',
    ) -> bool:
        """
        Check if data is cached for the given parameters.

        Args:
            symbol: Ticker symbol.
            start_date: Start date of data range.
            end_date: End date of data range.
            timespan: Data timespan (minute, day, etc.).
            asset_type: Asset type (stocks, futures).

        Returns:
            True if all required data is cached.
        """
        # Check each month in the range
        current = date(start_date.year, start_date.month, 1)
        while current <= end_date:
            year_month = current.strftime('%Y-%m')
            cache_path = self._get_cache_path(symbol, year_month, timespan, asset_type)
            if not cache_path.exists():
                return False

            # Move to next month
            current = (
                date(current.year + 1, 1, 1)
                if current.month == 12
                else date(current.year, current.month + 1, 1)
            )

        return True

    def get_missing_ranges(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timespan: str = 'minute',
        asset_type: str = 'stocks',
    ) -> list[tuple[date, date]]:
        """
        Get date ranges that are not cached.

        Returns:
            List of (start, end) date tuples for missing ranges.
        """
        missing: list[tuple[date, date]] = []
        current_missing_start: date | None = None

        current = date(start_date.year, start_date.month, 1)
        while current <= end_date:
            year_month = current.strftime('%Y-%m')
            cache_path = self._get_cache_path(symbol, year_month, timespan, asset_type)

            if not cache_path.exists():
                if current_missing_start is None:
                    current_missing_start = current
            elif current_missing_start is not None:
                # End of missing range
                # Previous month end
                if current.month == 1:
                    prev_month_end = date(current.year - 1, 12, 31)
                else:
                    from calendar import monthrange

                    prev_year, prev_month = current.year, current.month - 1
                    _, last_day = monthrange(prev_year, prev_month)
                    prev_month_end = date(prev_year, prev_month, last_day)

                missing.append((current_missing_start, min(prev_month_end, end_date)))
                current_missing_start = None

            # Move to next month
            current = (
                date(current.year + 1, 1, 1)
                if current.month == 12
                else date(current.year, current.month + 1, 1)
            )

        # Handle trailing missing range
        if current_missing_start is not None:
            missing.append((current_missing_start, end_date))

        return missing

    def store_bars(
        self,
        symbol: str,
        bars: list[Bar],
        timespan: str = 'minute',
        asset_type: str = 'stocks',
    ) -> None:
        """
        Store bars to cache, organized by month.

        Args:
            symbol: Ticker symbol.
            bars: List of Bar objects to cache.
            timespan: Data timespan.
            asset_type: Asset type (stocks, futures).
        """
        if not bars:
            return

        # Group bars by year-month
        bars_by_month: dict[str, list[dict[str, object]]] = {}
        for bar in bars:
            year_month = bar.timestamp.strftime('%Y-%m')
            if year_month not in bars_by_month:
                bars_by_month[year_month] = []

            bars_by_month[year_month].append(
                {
                    'symbol': bar.symbol,
                    'timestamp': bar.timestamp.isoformat(),
                    'open': str(bar.open),
                    'high': str(bar.high),
                    'low': str(bar.low),
                    'close': str(bar.close),
                    'volume': bar.volume,
                }
            )

        # Write each month's data
        safe_symbol = symbol.replace('/', '_').replace('\\', '_')
        symbol_dir = self._cache_dir / asset_type / safe_symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)

        for year_month, month_bars in bars_by_month.items():
            cache_path = self._get_cache_path(symbol, year_month, timespan, asset_type)
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            with open(cache_path, 'w') as f:
                json.dump(month_bars, f)

            logger.debug(f'Cached {len(month_bars)} bars for {symbol} {year_month}')

        # Update index
        if bars:
            start_ts = min(bar.timestamp for bar in bars)
            end_ts = max(bar.timestamp for bar in bars)
            key = self._get_cache_key(
                symbol,
                start_ts.date(),
                end_ts.date(),
                timespan,
                asset_type,
            )
            self._index[key] = CacheMetadata(
                symbol=symbol,
                start_date=start_ts.date().isoformat(),
                end_date=end_ts.date().isoformat(),
                timespan=timespan,
                fetch_timestamp=datetime.now(timezone.utc).isoformat(),
                record_count=len(bars),
            )
            self._save_index()

    def load_bars(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timespan: str = 'minute',
        asset_type: str = 'stocks',
    ) -> list[Bar]:
        """
        Load bars from cache.

        Args:
            symbol: Ticker symbol.
            start_date: Start date.
            end_date: End date.
            timespan: Data timespan.
            asset_type: Asset type.

        Returns:
            List of Bar objects, sorted by timestamp.
        """
        from ..data import Bar

        all_bars: list[Bar] = []

        current = date(start_date.year, start_date.month, 1)
        while current <= end_date:
            year_month = current.strftime('%Y-%m')
            cache_path = self._get_cache_path(symbol, year_month, timespan, asset_type)

            if cache_path.exists():
                try:
                    with open(cache_path) as f:
                        month_data = json.load(f)

                    for bar_dict in month_data:
                        ts = datetime.fromisoformat(bar_dict['timestamp'])
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        else:
                            ts = ts.astimezone(timezone.utc)
                        if start_date <= ts.date() <= end_date:
                            all_bars.append(
                                Bar(
                                    symbol=bar_dict['symbol'],
                                    timestamp=ts,
                                    open=Decimal(bar_dict['open']),
                                    high=Decimal(bar_dict['high']),
                                    low=Decimal(bar_dict['low']),
                                    close=Decimal(bar_dict['close']),
                                    volume=int(bar_dict['volume']),
                                )
                            )
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f'Failed to load cache {cache_path}: {e}')

            # Move to next month
            current = (
                date(current.year + 1, 1, 1)
                if current.month == 12
                else date(current.year, current.month + 1, 1)
            )

        # Sort by timestamp
        all_bars.sort(key=lambda b: b.timestamp)
        return all_bars

    def store_corporate_actions(
        self,
        action_type: str,
        actions: list[dict[str, object]],
    ) -> None:
        """
        Store corporate actions to cache.

        Args:
            action_type: Type of action (ipos, splits, dividends, ticker_events).
            actions: List of action dictionaries.
        """
        cache_path = self._cache_dir / 'corporate_actions' / f'{action_type}.json'
        with open(cache_path, 'w') as f:
            json.dump(actions, f, indent=2)
        logger.debug(f'Cached {len(actions)} {action_type} corporate actions')

    def load_corporate_actions(self, action_type: str) -> list[dict[str, object]]:
        """
        Load corporate actions from cache.

        Args:
            action_type: Type of action (ipos, splits, dividends, ticker_events).

        Returns:
            List of action dictionaries.
        """
        cache_path = self._cache_dir / 'corporate_actions' / f'{action_type}.json'
        if not cache_path.exists():
            return []

        try:
            with open(cache_path) as f:
                data = json.load(f)
                return cast(list[dict[str, object]], data)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f'Failed to load corporate actions cache: {e}')
            return []

    def clear_cache(self, symbol: str | None = None, asset_type: str | None = None) -> None:
        """
        Clear cached data.

        Args:
            symbol: If provided, only clear data for this symbol.
            asset_type: If provided, only clear data for this asset type.
        """
        import shutil

        if symbol and asset_type:
            safe_symbol = symbol.replace('/', '_').replace('\\', '_')
            target_dir = self._cache_dir / asset_type / safe_symbol
            if target_dir.exists():
                shutil.rmtree(target_dir)
                logger.info(f'Cleared cache for {symbol} ({asset_type})')
                self._rebuild_index()
        elif asset_type:
            target_dir = self._cache_dir / asset_type
            if target_dir.exists():
                shutil.rmtree(target_dir)
                target_dir.mkdir()
                logger.info(f'Cleared all {asset_type} cache')
                self._rebuild_index()
        else:
            # Clear everything except metadata
            for subdir in ['stocks', 'futures', 'corporate_actions']:
                target_dir = self._cache_dir / subdir
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                    target_dir.mkdir()
            self._index.clear()
            self._save_index()
            logger.info('Cleared entire cache')

    def get_cache_stats(self) -> dict[str, int]:
        """Get cache statistics."""
        stats = {
            'stocks_symbols': 0,
            'stocks_files': 0,
            'futures_symbols': 0,
            'futures_files': 0,
            'total_size_bytes': 0,
        }

        stocks_dir = self._cache_dir / 'stocks'
        if stocks_dir.exists():
            stats['stocks_symbols'] = len(list(stocks_dir.iterdir()))
            for symbol_dir in stocks_dir.iterdir():
                if symbol_dir.is_dir():
                    files = list(symbol_dir.glob('*.json'))
                    stats['stocks_files'] += len(files)
                    stats['total_size_bytes'] += sum(f.stat().st_size for f in files)

        futures_dir = self._cache_dir / 'futures'
        if futures_dir.exists():
            stats['futures_symbols'] = len(list(futures_dir.iterdir()))
            for symbol_dir in futures_dir.iterdir():
                if symbol_dir.is_dir():
                    files = list(symbol_dir.glob('*.json'))
                    stats['futures_files'] += len(files)
                    stats['total_size_bytes'] += sum(f.stat().st_size for f in files)

        return stats
