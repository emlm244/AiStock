"""
Massive.com (formerly Polygon.io) data provider.

Rate-limited client with disk caching for historical market data.

CRITICAL: Free tier limit is 5 API calls per minute.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..data import Bar


logger = logging.getLogger(__name__)


@dataclass
class MassiveConfig:
    """
    Configuration for Massive.com API access.

    Attributes:
        api_key: Massive.com API key.
        s3_access_key: S3 access key for flat files (optional).
        s3_secret_key: S3 secret key for flat files (optional).
        cache_dir: Directory for local disk cache.
        rate_limit_per_minute: Maximum API calls per minute (5 for free tier).
        max_retries: Maximum retry attempts for failed requests.
        retry_backoff_seconds: Initial backoff time for retries.
        s3_endpoint: S3 endpoint for flat files.
        s3_bucket: S3 bucket name for flat files.
    """

    api_key: str
    s3_access_key: str = ''
    s3_secret_key: str = ''
    cache_dir: str = 'data/massive_cache'
    rate_limit_per_minute: int = 5  # FREE TIER LIMIT - DO NOT EXCEED
    max_retries: int = 3
    retry_backoff_seconds: float = 15.0
    s3_endpoint: str = 'https://files.massive.com'
    s3_bucket: str = 'flatfiles'

    def __post_init__(self) -> None:
        """Validate configuration."""
        self.validate()

    def validate(self) -> None:
        """Validate configuration."""
        if not self.api_key:
            raise ValueError('API key is required')
        if self.rate_limit_per_minute < 1:
            raise ValueError('Rate limit must be at least 1')
        if self.rate_limit_per_minute > 5:
            logger.warning(
                f'Rate limit {self.rate_limit_per_minute} exceeds free tier (5). '
                'Ensure you have an appropriate subscription.'
            )


class RateLimiter:
    """
    Token bucket rate limiter for API calls.

    Strictly enforces the rate limit by blocking until a slot is available.
    This is critical for respecting Massive.com's 5 calls/minute free tier limit.
    """

    def __init__(
        self,
        max_calls: int = 5,
        window_seconds: int = 60,
    ) -> None:
        """
        Initialize rate limiter.

        Args:
            max_calls: Maximum calls allowed in window.
            window_seconds: Time window in seconds.
        """
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._call_times: deque[float] = deque()
        self._lock = threading.Lock()
        self._total_calls = 0
        self._total_waits = 0
        self._total_wait_time = 0.0

    def acquire(self) -> None:
        """
        Acquire a rate limit slot, blocking if necessary.

        This method will sleep if the rate limit has been reached,
        waiting until a slot becomes available.
        """
        while True:
            wait_time = 0.0
            with self._lock:
                now = time.time()

                # Remove calls outside the window
                while self._call_times and now - self._call_times[0] > self._window_seconds:
                    self._call_times.popleft()

                if len(self._call_times) < self._max_calls:
                    self._call_times.append(now)
                    self._total_calls += 1
                    return

                oldest_call = self._call_times[0]
                wait_time = self._window_seconds - (now - oldest_call) + 0.5  # Add buffer
                if wait_time > 0:
                    logger.info(
                        f'Rate limit reached ({self._max_calls}/{self._window_seconds}s). Sleeping {wait_time:.1f}s...'
                    )
                    self._total_waits += 1
                    self._total_wait_time += wait_time

            if wait_time > 0:
                time.sleep(wait_time)

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                'total_calls': self._total_calls,
                'total_waits': self._total_waits,
                'total_wait_time_seconds': self._total_wait_time,
                'current_window_calls': len(self._call_times),
                'max_calls_per_window': self._max_calls,
                'window_seconds': self._window_seconds,
            }

    def reset_stats(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._total_calls = 0
            self._total_waits = 0
            self._total_wait_time = 0.0


@dataclass
class FetchResult:
    """Result of a data fetch operation."""

    success: bool
    data: list[Any] = field(default_factory=list)
    error: str | None = None
    api_calls_used: int = 0
    from_cache: bool = False


class MassiveDataProvider:
    """
    Rate-limited data provider for Massive.com API.

    Implements MarketDataProviderProtocol for integration with the trading system.
    Uses disk caching to minimize API calls.

    IMPORTANT: Free tier is limited to 5 API calls per minute.
    This provider strictly respects that limit.
    """

    def __init__(self, config: MassiveConfig) -> None:
        """
        Initialize the data provider.

        Args:
            config: Massive.com configuration.
        """
        self._config = config
        self._rate_limiter = RateLimiter(
            max_calls=config.rate_limit_per_minute,
            window_seconds=60,
        )

        # Lazy import to avoid dependency if not using Massive
        self._client: Any = None
        self._cache: Any = None

    def _get_client(self) -> Any:
        """Get or create the Massive REST client."""
        if self._client is None:
            try:
                from massive import RESTClient

                self._client = RESTClient(api_key=self._config.api_key)
            except ImportError as e:
                raise ImportError('massive package not installed. Run: pip install massive') from e
        return self._client

    def _get_cache(self) -> Any:
        """Get or create the cache instance."""
        if self._cache is None:
            from .cache import MassiveCache

            self._cache = MassiveCache(self._config.cache_dir)
        return self._cache

    def load_cached_bars(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timespan: str = 'minute',
        asset_type: str = 'stocks',
    ) -> list[Bar]:
        """Load cached bars without hitting the Massive API."""
        cache = self._get_cache()
        return cache.load_bars(symbol, start_date, end_date, timespan, asset_type)

    def fetch_bars(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timespan: Literal['minute', 'day'] = 'minute',
        multiplier: int = 1,
        use_cache: bool = True,
    ) -> FetchResult:
        """
        Fetch historical bars for a symbol.

        Args:
            symbol: Ticker symbol (e.g., 'AAPL').
            start_date: Start date for data.
            end_date: End date for data.
            timespan: Bar timespan ('minute' or 'day').
            multiplier: Timespan multiplier (e.g., 5 for 5-minute bars).
            use_cache: Whether to use disk cache.

        Returns:
            FetchResult with list of Bar objects.
        """
        from ..data import Bar

        cache = self._get_cache()

        # Check cache first
        if use_cache and cache.has_cached_data(symbol, start_date, end_date, timespan):
            bars = cache.load_bars(symbol, start_date, end_date, timespan)
            logger.debug(f'Loaded {len(bars)} bars for {symbol} from cache')
            return FetchResult(
                success=True,
                data=bars,
                from_cache=True,
                api_calls_used=0,
            )

        # Get missing ranges
        missing_ranges = cache.get_missing_ranges(symbol, start_date, end_date, timespan)
        if not missing_ranges and use_cache:
            bars = cache.load_bars(symbol, start_date, end_date, timespan)
            return FetchResult(
                success=True,
                data=bars,
                from_cache=True,
                api_calls_used=0,
            )

        # Fetch from API
        client = self._get_client()
        all_bars: list[Bar] = []
        api_calls = 0
        errors: list[str] = []

        for range_start, range_end in missing_ranges or [(start_date, end_date)]:
            try:
                # Rate limit before API call
                self._rate_limiter.acquire()
                api_calls += 1

                logger.info(f'Fetching {symbol} {timespan} bars: {range_start} to {range_end}')

                # Call Massive API
                aggs = []
                for agg in client.list_aggs(
                    ticker=symbol,
                    multiplier=multiplier,
                    timespan=timespan,
                    from_=range_start.strftime('%Y-%m-%d'),
                    to=range_end.strftime('%Y-%m-%d'),
                    limit=50000,
                ):
                    aggs.append(agg)

                # Convert to Bar objects
                for agg in aggs:
                    # Massive returns timestamp in milliseconds
                    ts = datetime.fromtimestamp(agg.timestamp / 1000, tz=timezone.utc)
                    bar = Bar(
                        symbol=symbol,
                        timestamp=ts,
                        open=Decimal(str(agg.open)),
                        high=Decimal(str(agg.high)),
                        low=Decimal(str(agg.low)),
                        close=Decimal(str(agg.close)),
                        volume=int(agg.volume),
                    )
                    all_bars.append(bar)

                logger.info(f'Fetched {len(aggs)} bars for {symbol}')

            except Exception as e:
                error_msg = f'Failed to fetch {symbol} ({range_start} to {range_end}): {e}'
                logger.error(error_msg)
                errors.append(error_msg)

                # Retry with backoff
                for retry in range(self._config.max_retries):
                    backoff = self._config.retry_backoff_seconds * (2**retry)
                    logger.info(f'Retry {retry + 1}/{self._config.max_retries} in {backoff}s')
                    time.sleep(backoff)

                    try:
                        self._rate_limiter.acquire()
                        api_calls += 1

                        aggs = list(
                            client.list_aggs(
                                ticker=symbol,
                                multiplier=multiplier,
                                timespan=timespan,
                                from_=range_start.strftime('%Y-%m-%d'),
                                to=range_end.strftime('%Y-%m-%d'),
                                limit=50000,
                            )
                        )

                        for agg in aggs:
                            ts = datetime.fromtimestamp(agg.timestamp / 1000, tz=timezone.utc)
                            bar = Bar(
                                symbol=symbol,
                                timestamp=ts,
                                open=Decimal(str(agg.open)),
                                high=Decimal(str(agg.high)),
                                low=Decimal(str(agg.low)),
                                close=Decimal(str(agg.close)),
                                volume=int(agg.volume),
                            )
                            all_bars.append(bar)

                        errors.pop()  # Remove error on success
                        break

                    except Exception as retry_error:
                        logger.error(f'Retry {retry + 1} failed: {retry_error}')

        # Sort bars by timestamp
        all_bars.sort(key=lambda b: b.timestamp)

        # Cache the results
        if all_bars and use_cache:
            cache.store_bars(symbol, all_bars, timespan)

        # Also load any previously cached data for the full range
        if use_cache:
            all_bars = cache.load_bars(symbol, start_date, end_date, timespan)

        return FetchResult(
            success=len(errors) == 0,
            data=all_bars,
            error='; '.join(errors) if errors else None,
            api_calls_used=api_calls,
            from_cache=False,
        )

    def _list_futures_aggs(
        self,
        client: Any,
        ticker: str,
        start_date: date,
        end_date: date,
        resolution: str,
    ) -> list[Any]:
        params = {
            'resolution': resolution,
            'window_start.gte': start_date.strftime('%Y-%m-%d'),
            'window_start.lte': end_date.strftime('%Y-%m-%d'),
            'limit': 50000,
        }

        futures_client = getattr(client, 'futures', None)
        if futures_client is not None:
            for method_name in ('list_aggs', 'get_aggs', 'aggs'):
                method = getattr(futures_client, method_name, None)
                if method is None:
                    continue
                try:
                    return list(method(ticker=ticker, **params))
                except TypeError:
                    return list(method(ticker=ticker, params=params))

        for method_name in ('list_futures_aggs', 'get_futures_aggs'):
            method = getattr(client, method_name, None)
            if method is None:
                continue
            try:
                return list(method(ticker=ticker, **params))
            except TypeError:
                return list(method(ticker=ticker, params=params))

        raise AttributeError('Massive REST client does not expose a public futures aggregates API')

    def fetch_futures(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        resolution: str = '1min',
        use_cache: bool = True,
    ) -> FetchResult:
        """
        Fetch historical futures data.

        Args:
            ticker: Futures contract ticker (e.g., 'ESH26').
            start_date: Start date.
            end_date: End date.
            resolution: Bar resolution (e.g., '1min', '1day').
            use_cache: Whether to use disk cache.

        Returns:
            FetchResult with list of Bar objects.
        """
        from ..data import Bar

        cache = self._get_cache()

        # Check cache
        if use_cache and cache.has_cached_data(ticker, start_date, end_date, 'minute', 'futures'):
            bars = cache.load_bars(ticker, start_date, end_date, 'minute', 'futures')
            return FetchResult(
                success=True,
                data=bars,
                from_cache=True,
                api_calls_used=0,
            )

        # Fetch from API
        client = self._get_client()
        all_bars: list[Bar] = []
        api_calls = 0
        attempts = 0
        while True:
            try:
                self._rate_limiter.acquire()
                api_calls += 1

                logger.info(f'Fetching futures {ticker}: {start_date} to {end_date}')

                aggs = self._list_futures_aggs(client, ticker, start_date, end_date, resolution)

                for agg in aggs:
                    window_start = getattr(agg, 'window_start', None)
                    if window_start is None:
                        window_start = getattr(agg, 'timestamp', None)
                    if isinstance(window_start, (int, float)):
                        ts = datetime.fromtimestamp(window_start / 1000000000, tz=timezone.utc)
                    else:
                        ts = datetime.fromisoformat(str(window_start).replace('Z', '+00:00'))

                    bar = Bar(
                        symbol=ticker,
                        timestamp=ts,
                        open=Decimal(str(agg.open)),
                        high=Decimal(str(agg.high)),
                        low=Decimal(str(agg.low)),
                        close=Decimal(str(agg.close)),
                        volume=int(agg.volume),
                    )
                    all_bars.append(bar)

                logger.info(f'Fetched {len(all_bars)} futures bars for {ticker}')

                # Cache results
                if all_bars and use_cache:
                    cache.store_bars(ticker, all_bars, 'minute', 'futures')
                break

            except Exception as e:
                if attempts >= self._config.max_retries:
                    logger.error(f'Failed to fetch futures {ticker}: {e}')
                    return FetchResult(
                        success=False,
                        error=str(e),
                        api_calls_used=api_calls,
                    )

                backoff = self._config.retry_backoff_seconds * (2**attempts)
                attempts += 1
                logger.info(f'Retry {attempts}/{self._config.max_retries} in {backoff}s')
                time.sleep(backoff)

        return FetchResult(
            success=True,
            data=all_bars,
            api_calls_used=api_calls,
        )

    @staticmethod
    def _action_date(action: dict[str, object]) -> date | None:
        raw_date = action.get('ex_date') or action.get('listing_date')
        if not raw_date:
            return None
        try:
            return date.fromisoformat(str(raw_date))
        except (TypeError, ValueError):
            return None

    def fetch_corporate_actions(
        self,
        action_type: Literal['ipos', 'splits', 'dividends', 'ticker_events'],
        symbol: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        use_cache: bool = True,
    ) -> FetchResult:
        """
        Fetch corporate actions data.

        Args:
            action_type: Type of corporate action to fetch.
            symbol: Optional ticker symbol to filter by.
            start_date: Optional start date.
            end_date: Optional end date.
            use_cache: Whether to use disk cache.

        Returns:
            FetchResult with list of corporate action dictionaries.
        """
        cache = self._get_cache()

        # Check cache
        if use_cache:
            cached_data = cache.load_corporate_actions(action_type)
            if cached_data:
                # Filter by symbol and date if needed
                filtered = cached_data
                if symbol:
                    filtered = [a for a in filtered if a.get('ticker') == symbol]
                if start_date:
                    filtered = [a for a in filtered if (d := self._action_date(a)) and d >= start_date]
                if end_date:
                    filtered = [a for a in filtered if (d := self._action_date(a)) and d <= end_date]
                return FetchResult(
                    success=True,
                    data=filtered,
                    from_cache=True,
                    api_calls_used=0,
                )

        # Fetch from API
        client = self._get_client()
        api_calls = 0

        try:
            self._rate_limiter.acquire()
            api_calls += 1

            logger.info(f'Fetching corporate actions: {action_type}')

            # Build endpoint based on action type
            endpoint_map = {
                'ipos': '/vX/reference/ipos',
                'splits': '/v3/reference/splits',
                'dividends': '/v3/reference/dividends',
                'ticker_events': '/vX/reference/ticker-events',
            }

            endpoint = endpoint_map.get(action_type)
            if not endpoint:
                return FetchResult(
                    success=False,
                    error=f'Unknown action type: {action_type}',
                    api_calls_used=api_calls,
                )

            params: dict[str, Any] = {'limit': 1000}
            if symbol:
                params['ticker'] = symbol

            # Fetch with pagination
            all_actions: list[dict[str, object]] = []
            has_more = True

            while has_more:
                response = client._get(endpoint, params=params)

                if hasattr(response, 'results'):
                    for action in response.results:
                        all_actions.append(action.__dict__ if hasattr(action, '__dict__') else dict(action))

                # Check for pagination
                if hasattr(response, 'next_url') and response.next_url:
                    self._rate_limiter.acquire()
                    api_calls += 1
                    params['cursor'] = response.next_url.split('cursor=')[-1]
                else:
                    has_more = False

            logger.info(f'Fetched {len(all_actions)} {action_type} records')

            # Cache results
            if use_cache:
                cache.store_corporate_actions(action_type, all_actions)

            # Filter by date if needed
            if start_date or end_date:
                filtered = all_actions
                if start_date:
                    filtered = [a for a in filtered if (d := self._action_date(a)) and d >= start_date]
                if end_date:
                    filtered = [a for a in filtered if (d := self._action_date(a)) and d <= end_date]
                all_actions = filtered

            return FetchResult(
                success=True,
                data=all_actions,
                api_calls_used=api_calls,
            )

        except Exception as e:
            logger.error(f'Failed to fetch {action_type}: {e}')
            return FetchResult(
                success=False,
                error=str(e),
                api_calls_used=api_calls,
            )

    def list_tickers(
        self,
        market: Literal['stocks', 'futures'] = 'stocks',
        active: bool = True,
        ticker_type: str | None = None,
    ) -> FetchResult:
        """
        List available tickers.

        Args:
            market: Market type.
            active: Only include active tickers.
            ticker_type: Filter by ticker type (e.g., 'CS' for common stock).

        Returns:
            FetchResult with list of ticker information dictionaries.
        """
        client = self._get_client()
        api_calls = 0

        try:
            self._rate_limiter.acquire()
            api_calls += 1

            logger.info(f'Listing {market} tickers (active={active})')

            tickers: list[dict[str, object]] = []

            for ticker in client.list_tickers(
                market=market,
                active=active,
                type=ticker_type,
                limit=1000,
            ):
                tickers.append(
                    {
                        'ticker': ticker.ticker,
                        'name': getattr(ticker, 'name', ''),
                        'market': getattr(ticker, 'market', market),
                        'type': getattr(ticker, 'type', ''),
                        'active': getattr(ticker, 'active', active),
                        'currency_name': getattr(ticker, 'currency_name', 'USD'),
                        'primary_exchange': getattr(ticker, 'primary_exchange', ''),
                    }
                )

            logger.info(f'Found {len(tickers)} tickers')

            return FetchResult(
                success=True,
                data=tickers,
                api_calls_used=api_calls,
            )

        except Exception as e:
            logger.error(f'Failed to list tickers: {e}')
            return FetchResult(
                success=False,
                error=str(e),
                api_calls_used=api_calls,
            )

    def get_rate_limiter_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        return self._rate_limiter.get_stats()

    def estimate_fetch_time(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        timespan: str = 'minute',
    ) -> dict[str, Any]:
        """
        Estimate time to fetch data for given parameters.

        Args:
            symbols: List of symbols to fetch.
            start_date: Start date.
            end_date: End date.
            timespan: Bar timespan.

        Returns:
            Dictionary with estimate details.
        """
        cache = self._get_cache()

        # Count missing data
        total_api_calls = 0
        cached_symbols = 0
        missing_ranges: dict[str, list[tuple[date, date]]] = {}

        for symbol in symbols:
            if cache.has_cached_data(symbol, start_date, end_date, timespan):
                cached_symbols += 1
            else:
                ranges = cache.get_missing_ranges(symbol, start_date, end_date, timespan)
                if ranges:
                    missing_ranges[symbol] = ranges
                    total_api_calls += len(ranges)
                else:
                    total_api_calls += 1

        # Calculate time estimate
        # 5 calls per minute = 12 seconds per call on average
        estimated_seconds = (total_api_calls / self._config.rate_limit_per_minute) * 60
        estimated_minutes = estimated_seconds / 60

        return {
            'total_symbols': len(symbols),
            'cached_symbols': cached_symbols,
            'symbols_to_fetch': len(missing_ranges),
            'estimated_api_calls': total_api_calls,
            'estimated_minutes': round(estimated_minutes, 1),
            'rate_limit_per_minute': self._config.rate_limit_per_minute,
            'missing_ranges': missing_ranges,
        }

    # MarketDataProviderProtocol implementation

    def get_bars(
        self,
        symbol: str,
        timeframe: str = '1m',
        lookback: int | None = None,
    ) -> list[Bar]:
        """
        Get historical bars for a symbol.

        This is the MarketDataProviderProtocol interface method.
        For backtesting, data should be prefetched using fetch_bars().
        """
        # This method is for live trading integration
        # For backtesting, use fetch_bars() to prefetch data
        cache = self._get_cache()

        # Try to load from cache
        from datetime import timedelta

        end_date = date.today()
        start_date = end_date - timedelta(days=lookback or 30)

        bars = cache.load_bars(symbol, start_date, end_date, 'minute')
        return bars

    def has_sufficient_data(self, symbol: str, min_bars: int = 20) -> bool:
        """Check if sufficient data is available in cache."""
        bars = self.get_bars(symbol, lookback=min_bars * 2)
        return len(bars) >= min_bars

    def add_bar(self, symbol: str, timeframe: str, bar: Bar) -> None:
        """Add a new bar to the data store (not used in backtest mode)."""
        raise NotImplementedError('add_bar not supported in backtest provider')

    def get_latest_bar(self, symbol: str, timeframe: str = '1m') -> Bar | None:
        """Get the most recent bar from cache."""
        bars = self.get_bars(symbol, timeframe, lookback=1)
        return bars[-1] if bars else None
