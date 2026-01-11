"""Tests for the Massive.com data provider."""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from aistock.providers.cache import MassiveCache
from aistock.providers.massive import MassiveConfig, MassiveDataProvider, RateLimiter


class TestMassiveConfig:
    """Tests for MassiveConfig."""

    def test_valid_config(self) -> None:
        """Test creating a valid config."""
        config = MassiveConfig(
            api_key='test_key',
            s3_access_key='access',
            s3_secret_key='secret',
        )
        assert config.api_key == 'test_key'
        assert config.rate_limit_per_minute == 5

    def test_missing_api_key(self) -> None:
        """Test that missing API key raises error."""
        with pytest.raises(ValueError, match='API key is required'):
            MassiveConfig(api_key='')

    def test_invalid_rate_limit(self) -> None:
        """Test that invalid rate limit raises error."""
        with pytest.raises(ValueError, match='Rate limit must be at least 1'):
            MassiveConfig(api_key='test', rate_limit_per_minute=0)


class TestRateLimiter:
    """Tests for RateLimiter."""

    def test_allows_calls_within_limit(self) -> None:
        """Test that calls within limit proceed immediately."""
        limiter = RateLimiter(max_calls=5, window_seconds=60)

        start = time.time()
        for _ in range(5):
            limiter.acquire()
        elapsed = time.time() - start

        # Should complete almost instantly
        assert elapsed < 1.0

    def test_blocks_when_limit_exceeded(self) -> None:
        """Test that exceeding limit causes blocking."""
        limiter = RateLimiter(max_calls=2, window_seconds=1)

        # Use up the limit
        limiter.acquire()
        limiter.acquire()

        start = time.time()
        limiter.acquire()  # Should block
        elapsed = time.time() - start

        # Should have waited approximately 1 second
        assert elapsed >= 0.5

    def test_stats_tracking(self) -> None:
        """Test that statistics are tracked correctly."""
        limiter = RateLimiter(max_calls=5, window_seconds=60)

        for _ in range(3):
            limiter.acquire()

        stats = limiter.get_stats()
        assert stats['total_calls'] == 3
        assert stats['current_window_calls'] == 3

    def test_reset_stats(self) -> None:
        """Test stats reset."""
        limiter = RateLimiter(max_calls=5, window_seconds=60)
        limiter.acquire()
        limiter.reset_stats()

        stats = limiter.get_stats()
        assert stats['total_calls'] == 0


class TestMassiveCache:
    """Tests for MassiveCache."""

    def test_cache_creation(self, tmp_path) -> None:
        """Test cache directory creation."""
        cache_dir = tmp_path / 'cache'
        _cache = MassiveCache(cache_dir)  # noqa: F841

        assert (cache_dir / 'stocks').exists()
        assert (cache_dir / 'futures').exists()
        assert (cache_dir / 'corporate_actions').exists()

    def test_has_cached_data_empty(self, tmp_path) -> None:
        """Test has_cached_data returns False for empty cache."""
        cache = MassiveCache(tmp_path / 'cache')

        result = cache.has_cached_data(
            'AAPL',
            date(2024, 1, 1),
            date(2024, 1, 31),
        )
        assert result is False

    def test_get_missing_ranges(self, tmp_path) -> None:
        """Test get_missing_ranges identifies gaps."""
        cache = MassiveCache(tmp_path / 'cache')

        ranges = cache.get_missing_ranges(
            'AAPL',
            date(2024, 1, 1),
            date(2024, 3, 31),
        )

        # Should identify the entire range as missing
        assert len(ranges) == 1
        assert ranges[0][0] == date(2024, 1, 1)

    def test_store_and_load_bars(self, tmp_path) -> None:
        """Test storing and loading bars."""
        from datetime import datetime, timezone

        from aistock.data import Bar

        cache = MassiveCache(tmp_path / 'cache')

        bars = [
            Bar(
                symbol='AAPL',
                timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
                open=Decimal('150.00'),
                high=Decimal('151.00'),
                low=Decimal('149.00'),
                close=Decimal('150.50'),
                volume=1000000,
            ),
            Bar(
                symbol='AAPL',
                timestamp=datetime(2024, 1, 15, 10, 1, tzinfo=timezone.utc),
                open=Decimal('150.50'),
                high=Decimal('151.50'),
                low=Decimal('150.00'),
                close=Decimal('151.00'),
                volume=1200000,
            ),
        ]

        cache.store_bars('AAPL', bars)

        # Load back
        loaded = cache.load_bars('AAPL', date(2024, 1, 1), date(2024, 1, 31))

        assert len(loaded) == 2
        assert loaded[0].symbol == 'AAPL'
        assert loaded[0].close == Decimal('150.50')

    def test_cache_stats(self, tmp_path) -> None:
        """Test cache statistics."""
        cache = MassiveCache(tmp_path / 'cache')
        stats = cache.get_cache_stats()

        assert 'stocks_symbols' in stats
        assert 'total_size_bytes' in stats


class TestMassiveDataProvider:
    """Tests for MassiveDataProvider."""

    def test_provider_creation(self) -> None:
        """Test creating a provider."""
        config = MassiveConfig(api_key='test_key')
        provider = MassiveDataProvider(config)

        assert provider._config == config

    def test_estimate_fetch_time(self, tmp_path) -> None:
        """Test fetch time estimation."""
        config = MassiveConfig(api_key='test_key', cache_dir=str(tmp_path / 'cache'))
        provider = MassiveDataProvider(config)

        estimate = provider.estimate_fetch_time(
            symbols=['AAPL', 'MSFT', 'GOOGL'],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            timespan='minute',
        )

        assert 'total_symbols' in estimate
        assert estimate['total_symbols'] == 3
        assert 'estimated_api_calls' in estimate
        assert 'estimated_minutes' in estimate

    @patch('aistock.providers.massive.MassiveDataProvider._get_client')
    def test_fetch_bars_uses_cache(self, mock_get_client, tmp_path) -> None:
        """Test that fetch_bars uses cache when available."""
        from datetime import datetime, timezone

        from aistock.data import Bar

        # Pre-populate cache
        cache = MassiveCache(tmp_path / 'cache')
        bars = [
            Bar(
                symbol='AAPL',
                timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
                open=Decimal('150.00'),
                high=Decimal('151.00'),
                low=Decimal('149.00'),
                close=Decimal('150.50'),
                volume=1000000,
            ),
        ]
        cache.store_bars('AAPL', bars)

        # Create provider with same cache
        config = MassiveConfig(api_key='test_key', cache_dir=str(tmp_path / 'cache'))
        provider = MassiveDataProvider(config)

        result = provider.fetch_bars(
            'AAPL',
            date(2024, 1, 1),
            date(2024, 1, 31),
            use_cache=True,
        )

        # Should use cache, not call API
        assert result.from_cache is True
        assert result.api_calls_used == 0
        mock_get_client.assert_not_called()
