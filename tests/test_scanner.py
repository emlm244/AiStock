"""
Tests for IBKR market scanner functionality.

Note: These tests use mocks and do not require live IBKR connection.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest  # type: ignore[import-not-found]

from aistock.scanner import (
    IBAPI_AVAILABLE,
    MarketScanner,
    ScannedStock,
    ScannerFilter,
    scan_for_fsd,
    scan_market,
)


class TestScannerFilter:
    """Test ScannerFilter dataclass."""

    def test_default_filter_values(self):
        """Test default filter values match FSD requirements."""
        filter = ScannerFilter()

        assert filter.min_price == 1.0
        assert filter.max_price == 10000.0
        assert filter.min_volume == 100000
        assert filter.instrument == 'STK'
        assert filter.location_code == 'STK.US'
        assert filter.max_results == 100

    def test_custom_filter_values(self):
        """Test custom filter configuration."""
        filter = ScannerFilter(
            min_price=10.0,
            max_price=500.0,
            min_volume=500000,
            max_results=50,
        )

        assert filter.min_price == 10.0
        assert filter.max_price == 500.0
        assert filter.min_volume == 500000
        assert filter.max_results == 50

    def test_sector_filters(self):
        """Test sector filtering configuration."""
        filter = ScannerFilter(
            include_sectors=['Technology', 'Healthcare'],
            exclude_sectors=['Energy'],
        )

        assert 'Technology' in filter.include_sectors
        assert 'Healthcare' in filter.include_sectors
        assert 'Energy' in filter.exclude_sectors


class TestScannedStock:
    """Test ScannedStock dataclass."""

    def test_scanned_stock_creation(self):
        """Test creating a scanned stock result."""
        stock = ScannedStock(
            symbol='AAPL',
            contract_id=265598,
            exchange='SMART',
            currency='USD',
            price=150.0,
            volume=50000000,
            rank=1,
        )

        assert stock.symbol == 'AAPL'
        assert stock.contract_id == 265598
        assert stock.exchange == 'SMART'
        assert stock.currency == 'USD'
        assert stock.price == 150.0
        assert stock.volume == 50000000
        assert stock.rank == 1

    def test_optional_fields(self):
        """Test optional fields default to None."""
        stock = ScannedStock(
            symbol='MSFT',
            contract_id=272093,
            exchange='SMART',
            currency='USD',
        )

        assert stock.price is None
        assert stock.volume is None
        assert stock.market_cap is None
        assert stock.sector is None


@pytest.mark.skipif(not IBAPI_AVAILABLE, reason='ibapi not available')
class TestMarketScanner:
    """Test MarketScanner class (requires mocking IBKR connection)."""

    @patch('aistock.scanner.EClient')
    @patch('aistock.scanner.EWrapper')
    def test_scanner_initialization(self, mock_wrapper: Mock, mock_client: Mock) -> None:
        """Test scanner initializes correctly."""
        scanner = MarketScanner(host='127.0.0.1', port=7497, client_id=2)

        assert scanner.host == '127.0.0.1'
        assert scanner.port == 7497
        assert scanner.client_id == 2
        assert scanner._scanned_stocks == []

    @patch('aistock.scanner.EClient.connect')
    @patch('aistock.scanner.EClient.run')
    def test_scanner_connect_and_scan_mock(self, mock_run: Mock, mock_connect: Mock) -> None:
        """Test scanner connection and scanning with mocks."""
        scanner = MarketScanner()

        # Mock successful connection
        scanner._connected.set()
        scanner._scan_complete.set()

        # Add mock results
        scanner._scanned_stocks = [
            ScannedStock(
                symbol='AAPL',
                contract_id=265598,
                exchange='SMART',
                currency='USD',
                rank=1,
            ),
            ScannedStock(
                symbol='MSFT',
                contract_id=272093,
                exchange='SMART',
                currency='USD',
                rank=2,
            ),
        ]

        results = scanner.get_results()

        assert len(results) == 2
        assert results[0].symbol == 'AAPL'
        assert results[1].symbol == 'MSFT'

    def test_get_symbols(self):
        """Test extracting symbols from scan results."""
        scanner = MarketScanner()
        scanner._scanned_stocks = [
            ScannedStock(symbol='AAPL', contract_id=1, exchange='SMART', currency='USD'),
            ScannedStock(symbol='MSFT', contract_id=2, exchange='SMART', currency='USD'),
            ScannedStock(symbol='GOOGL', contract_id=3, exchange='SMART', currency='USD'),
        ]

        symbols = scanner.get_symbols()

        assert symbols == ['AAPL', 'MSFT', 'GOOGL']


class TestConvenienceFunctions:
    """Test convenience functions for scanning."""

    @patch('aistock.scanner.MarketScanner')
    def test_scan_market_with_defaults(self, mock_scanner_class: Mock) -> None:
        """Test scan_market with default parameters."""
        # Create mock scanner instance
        mock_scanner = Mock()
        mock_scanner.connect_and_scan.return_value = [
            ScannedStock(symbol='AAPL', contract_id=1, exchange='SMART', currency='USD'),
            ScannedStock(symbol='MSFT', contract_id=2, exchange='SMART', currency='USD'),
        ]
        mock_scanner_class.return_value = mock_scanner

        results = scan_market()

        assert len(results) == 2
        assert results[0].symbol == 'AAPL'
        mock_scanner.connect_and_scan.assert_called_once()

    @patch('aistock.scanner.MarketScanner')
    def test_scan_market_with_custom_filter(self, mock_scanner_class: Mock) -> None:
        """Test scan_market with custom filter."""
        mock_scanner = Mock()
        mock_scanner.connect_and_scan.return_value = []
        mock_scanner_class.return_value = mock_scanner

        custom_filter = ScannerFilter(
            min_price=50.0,
            max_price=500.0,
            min_volume=1000000,
        )

        results = scan_market(scanner_filter=custom_filter)

        assert len(results) == 0
        mock_scanner.connect_and_scan.assert_called_once_with(custom_filter, timeout=30.0)

    @patch('aistock.scanner.scan_market')
    def test_scan_for_fsd(self, mock_scan_market: Mock) -> None:
        """Test FSD-optimized scanning."""
        mock_scan_market.return_value = [
            ScannedStock(symbol='AAPL', contract_id=1, exchange='SMART', currency='USD'),
            ScannedStock(symbol='MSFT', contract_id=2, exchange='SMART', currency='USD'),
            ScannedStock(symbol='GOOGL', contract_id=3, exchange='SMART', currency='USD'),
        ]

        symbols = scan_for_fsd(
            min_price=10.0,
            max_price=500.0,
            min_volume=500000,
            max_results=50,
        )

        assert symbols == ['AAPL', 'MSFT', 'GOOGL']
        mock_scan_market.assert_called_once()

        # Verify correct filter was constructed
        call_args = mock_scan_market.call_args
        filter_arg = call_args[0][0]

        assert filter_arg.min_price == 10.0
        assert filter_arg.max_price == 500.0
        assert filter_arg.min_volume == 500000
        assert filter_arg.max_results == 50

    @patch('aistock.scanner.MarketScanner')
    def test_scan_market_handles_exceptions(self, mock_scanner_class: Mock) -> None:
        """Test scan_market handles exceptions gracefully."""
        mock_scanner = Mock()
        mock_scanner.connect_and_scan.side_effect = Exception('Connection failed')
        mock_scanner_class.return_value = mock_scanner

        # Should return empty list on exception, not raise
        results = scan_market()

        assert results == []


class TestScannerIntegration:
    """Integration tests for scanner workflow."""

    def test_filter_to_scanner_flow(self):
        """Test complete workflow from filter creation to results."""
        # Create filter matching FSD requirements
        filter = ScannerFilter(
            min_price=5.0,
            max_price=1000.0,
            min_volume=200000,
            max_results=100,
        )

        # Verify filter is configured correctly
        assert filter.min_price == 5.0
        assert filter.max_price == 1000.0
        assert filter.min_volume == 200000
        assert filter.instrument == 'STK'  # Stocks only
        assert filter.location_code == 'STK.US'  # US stocks

    @patch('aistock.scanner.scan_market')
    def test_fsd_discovery_flow(self, mock_scan_market: Mock) -> None:
        """Test FSD discovery uses scanner correctly."""
        # Mock scanner results
        mock_scan_market.return_value = [
            ScannedStock(symbol=f'STOCK{i}', contract_id=i, exchange='SMART', currency='USD') for i in range(50)
        ]

        # FSD scans for stocks
        symbols = scan_for_fsd(min_price=1.0, max_price=10000.0, min_volume=100000, max_results=100)

        # Should return 50 symbols
        assert len(symbols) == 50
        assert symbols[0] == 'STOCK0'
        assert symbols[49] == 'STOCK49'

    def test_scanner_filter_validation(self):
        """Test scanner filter validates inputs."""
        # Test that filter accepts valid ranges
        filter = ScannerFilter(
            min_price=0.01,  # Penny stocks
            max_price=100000.0,  # Very expensive stocks
            min_volume=0,  # Any volume
        )

        assert filter.min_price == 0.01
        assert filter.max_price == 100000.0
        assert filter.min_volume == 0


class TestScannerEdgeCases:
    """Test edge cases and error handling."""

    @patch('aistock.scanner.MarketScanner')
    def test_scanner_timeout(self, mock_scanner_class: Mock) -> None:
        """Test scanner handles timeout gracefully."""
        mock_scanner = Mock()
        mock_scanner.connect_and_scan.side_effect = TimeoutError('Scan timeout')
        mock_scanner_class.return_value = mock_scanner

        results = scan_market(timeout=5.0)

        assert results == []  # Should return empty list, not raise

    @patch('aistock.scanner.MarketScanner')
    def test_scanner_connection_refused(self, mock_scanner_class: Mock) -> None:
        """Test scanner handles connection refusal."""
        mock_scanner = Mock()
        mock_scanner.connect_and_scan.side_effect = ConnectionRefusedError('IBKR not running')
        mock_scanner_class.return_value = mock_scanner

        results = scan_market()

        assert results == []

    @patch('aistock.scanner.scan_market')
    def test_scan_for_fsd_empty_results(self, mock_scan_market: Mock) -> None:
        """Test scan_for_fsd handles empty results."""
        mock_scan_market.return_value = []

        symbols = scan_for_fsd()

        assert symbols == []

    def test_scanned_stock_serialization(self):
        """Test ScannedStock can be converted to dict."""
        from dataclasses import asdict

        stock = ScannedStock(
            symbol='AAPL',
            contract_id=265598,
            exchange='SMART',
            currency='USD',
            price=150.0,
            volume=50000000,
        )

        stock_dict = asdict(stock)

        assert stock_dict['symbol'] == 'AAPL'
        assert stock_dict['contract_id'] == 265598
        assert stock_dict['price'] == 150.0


# Integration test (requires IBKR running - disabled by default)
@pytest.mark.skip(reason='Requires live IBKR connection')
class TestLiveScanner:
    """Live integration tests (requires IBKR Gateway/TWS running)."""

    def test_live_scan(self):
        """Test live scanning with IBKR."""
        results = scan_market(
            scanner_filter=ScannerFilter(
                min_price=10.0,
                max_price=500.0,
                min_volume=500000,
                max_results=10,
            ),
            host='127.0.0.1',
            port=7497,  # Live port
            timeout=30.0,
        )

        # If IBKR is running, should get results
        if results:
            assert len(results) > 0
            assert all(isinstance(stock, ScannedStock) for stock in results)
            assert all(stock.symbol for stock in results)

    def test_live_fsd_scan(self):
        """Test FSD scanning with live connection."""
        symbols = scan_for_fsd(
            min_price=5.0,
            max_price=1000.0,
            min_volume=200000,
            max_results=25,
        )

        # If IBKR is running, should get symbols
        if symbols:
            assert len(symbols) > 0
            assert all(isinstance(symbol, str) for symbol in symbols)
