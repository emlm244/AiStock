"""Tests for analytics module."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from aistock.analytics import (
    DrawdownMetrics,
    SymbolPerformance,
    calculate_drawdown_metrics,
    calculate_symbol_performance,
    export_drawdown_csv,
    export_symbol_performance_csv,
    generate_capital_sizing_report,
)


class TestSymbolPerformance:
    """Test per-symbol performance calculations."""

    def test_calculate_symbol_performance_basic(self):
        """Test basic performance calculation."""
        trade_log = [
            {
                'symbol': 'AAPL',
                'realised_pnl': 100.0,
                'quantity': 10,
                'timestamp': datetime.now(timezone.utc),
            },
            {
                'symbol': 'AAPL',
                'realised_pnl': -50.0,
                'quantity': -5,
                'timestamp': datetime.now(timezone.utc),
            },
            {
                'symbol': 'AAPL',
                'realised_pnl': 75.0,
                'quantity': 8,
                'timestamp': datetime.now(timezone.utc),
            },
        ]

        perf = calculate_symbol_performance(trade_log, 'AAPL')

        assert perf is not None
        assert perf.symbol == 'AAPL'
        assert perf.total_trades == 3
        assert perf.winning_trades == 2
        assert perf.losing_trades == 1
        assert perf.win_rate == pytest.approx(66.67, rel=0.1)
        assert perf.total_pnl == Decimal('125.0')
        assert perf.expectancy > 0

    def test_calculate_symbol_performance_no_trades(self):
        """Test performance with no trades."""
        trade_log = []
        perf = calculate_symbol_performance(trade_log, 'AAPL')
        assert perf is None

    def test_calculate_symbol_performance_all_winners(self):
        """Test performance with all winning trades."""
        trade_log = [
            {'symbol': 'AAPL', 'realised_pnl': 100.0},
            {'symbol': 'AAPL', 'realised_pnl': 50.0},
        ]

        perf = calculate_symbol_performance(trade_log, 'AAPL')

        assert perf.winning_trades == 2
        assert perf.losing_trades == 0
        assert perf.win_rate == 100.0
        assert perf.avg_loss == Decimal('0')

    def test_calculate_symbol_performance_all_losers(self):
        """Test performance with all losing trades."""
        trade_log = [
            {'symbol': 'AAPL', 'realised_pnl': -100.0},
            {'symbol': 'AAPL', 'realised_pnl': -50.0},
        ]

        perf = calculate_symbol_performance(trade_log, 'AAPL')

        assert perf.winning_trades == 0
        assert perf.losing_trades == 2
        assert perf.win_rate == 0.0
        assert perf.avg_win == Decimal('0')
        assert perf.profit_factor == 0.0

    def test_calculate_symbol_performance_decimal_precision(self):
        """Test that Decimal precision is maintained."""
        trade_log = [
            {'symbol': 'AAPL', 'realised_pnl': 100.123456789},
        ]

        perf = calculate_symbol_performance(trade_log, 'AAPL')

        # Verify Decimal type maintained
        assert isinstance(perf.total_pnl, Decimal)
        assert isinstance(perf.expectancy, Decimal)


class TestDrawdownMetrics:
    """Test drawdown calculations."""

    def test_calculate_drawdown_metrics_basic(self):
        """Test basic drawdown calculation."""
        equity_curve = [
            (datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal('10000')),
            (datetime(2024, 1, 2, tzinfo=timezone.utc), Decimal('10500')),  # +5% peak
            (datetime(2024, 1, 3, tzinfo=timezone.utc), Decimal('9975')),  # -5% from peak
            (datetime(2024, 1, 4, tzinfo=timezone.utc), Decimal('10200')),
        ]

        metrics = calculate_drawdown_metrics(equity_curve)

        assert metrics is not None
        assert metrics.peak_equity == Decimal('10500')
        assert metrics.current_equity == Decimal('10200')
        assert metrics.max_drawdown_pct > 0
        assert metrics.max_drawdown_pct == pytest.approx(5.0, rel=0.1)

    def test_calculate_drawdown_metrics_no_drawdown(self):
        """Test with monotonically increasing equity."""
        equity_curve = [
            (datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal('10000')),
            (datetime(2024, 1, 2, tzinfo=timezone.utc), Decimal('10500')),
            (datetime(2024, 1, 3, tzinfo=timezone.utc), Decimal('11000')),
        ]

        metrics = calculate_drawdown_metrics(equity_curve)

        assert metrics.max_drawdown_pct == 0.0
        assert metrics.current_drawdown_pct == 0.0

    def test_calculate_drawdown_metrics_insufficient_data(self):
        """Test with insufficient data."""
        equity_curve = [(datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal('10000'))]

        metrics = calculate_drawdown_metrics(equity_curve)

        assert metrics is None

    def test_calculate_drawdown_metrics_duration(self):
        """Test drawdown duration calculation."""
        equity_curve = [
            (datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal('10000')),
            (datetime(2024, 1, 2, tzinfo=timezone.utc), Decimal('10000')),  # Peak
            (datetime(2024, 1, 5, tzinfo=timezone.utc), Decimal('9500')),  # 3 days later
            (datetime(2024, 1, 10, tzinfo=timezone.utc), Decimal('9500')),  # 5 days later
        ]

        metrics = calculate_drawdown_metrics(equity_curve)

        assert metrics.max_drawdown_duration_days > 0
        # Should be approximately 8 days (Jan 2 to Jan 10)


class TestCapitalSizing:
    """Test capital sizing guidance."""

    def test_generate_capital_sizing_report_basic(self):
        """Test basic capital sizing calculation."""
        report = generate_capital_sizing_report(
            current_capital=Decimal('10000'), target_monthly_return_pct=10.0, avg_monthly_return_pct=2.0
        )

        assert 'current_capital' in report
        assert report['current_capital'] == 10000.0
        assert 'target_monthly_return_pct' in report
        assert 'required_capital' in report
        assert 'capital_gap' in report
        assert 'recommendation' in report

    def test_generate_capital_sizing_report_no_history(self):
        """Test capital sizing with no historical data."""
        report = generate_capital_sizing_report(
            current_capital=Decimal('10000'), target_monthly_return_pct=10.0, avg_monthly_return_pct=None
        )

        # Should use conservative 1.5% estimate
        assert report['required_capital'] > report['current_capital']
        assert report['avg_monthly_return_pct'] is None

    def test_generate_capital_sizing_report_high_target(self):
        """Test capital sizing with high target return."""
        report = generate_capital_sizing_report(
            current_capital=Decimal('5000'), target_monthly_return_pct=20.0, avg_monthly_return_pct=2.0
        )

        # Should require 10x capital (2% actual vs 20% target)
        assert report['required_capital'] == pytest.approx(50000.0, rel=0.01)
        assert report['capital_gap'] == pytest.approx(45000.0, rel=0.01)


class TestCSVExport:
    """Test CSV export functions."""

    def test_export_symbol_performance_csv(self, tmp_path):
        """Test exporting symbol performance to CSV."""
        trade_log = [
            {'symbol': 'AAPL', 'realised_pnl': 100.0},
            {'symbol': 'AAPL', 'realised_pnl': -50.0},
            {'symbol': 'MSFT', 'realised_pnl': 75.0},
        ]

        output_path = str(tmp_path / 'performance.csv')
        export_symbol_performance_csv(trade_log, ['AAPL', 'MSFT'], output_path)

        # Verify file created
        assert (tmp_path / 'performance.csv').exists()

        # Verify content
        with open(output_path) as f:
            content = f.read()
            assert 'AAPL' in content
            assert 'MSFT' in content
            assert 'win_rate_pct' in content

    def test_export_drawdown_csv(self, tmp_path):
        """Test exporting drawdown analysis to CSV."""
        equity_curve = [
            (datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal('10000')),
            (datetime(2024, 1, 2, tzinfo=timezone.utc), Decimal('10500')),
            (datetime(2024, 1, 3, tzinfo=timezone.utc), Decimal('9975')),
        ]

        output_path = str(tmp_path / 'drawdown.csv')
        export_drawdown_csv(equity_curve, output_path)

        # Verify file created
        assert (tmp_path / 'drawdown.csv').exists()

        # Verify content
        with open(output_path) as f:
            content = f.read()
            assert 'current_drawdown_pct' in content
            assert 'max_drawdown_pct' in content
