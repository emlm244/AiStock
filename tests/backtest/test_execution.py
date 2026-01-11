"""Tests for the realistic execution model."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from aistock.backtest.config import RealisticExecutionConfig
from aistock.backtest.execution import ExecutionCosts, FillResult, RealisticExecutionModel
from aistock.data import Bar


def make_bar(
    symbol: str = 'AAPL',
    close: Decimal = Decimal('150.00'),
    volume: int = 1000000,
    high: Decimal | None = None,
    low: Decimal | None = None,
) -> Bar:
    """Helper to create a test bar."""
    return Bar(
        symbol=symbol,
        timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
        open=close - Decimal('1'),
        high=high or close + Decimal('2'),
        low=low or close - Decimal('2'),
        close=close,
        volume=volume,
    )


class TestRealisticExecutionConfig:
    """Tests for RealisticExecutionConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = RealisticExecutionConfig()
        assert config.base_slippage_bps == 5.0
        assert config.max_volume_participation == 0.05
        assert config.enable_market_impact is True

    def test_invalid_slippage(self) -> None:
        """Test validation of slippage parameters."""
        with pytest.raises(ValueError, match='base_slippage_bps cannot be negative'):
            RealisticExecutionConfig(base_slippage_bps=-1.0)

    def test_invalid_volume_participation(self) -> None:
        """Test validation of volume participation."""
        with pytest.raises(ValueError, match='max_volume_participation must be in'):
            RealisticExecutionConfig(max_volume_participation=1.5)


class TestRealisticExecutionModel:
    """Tests for RealisticExecutionModel."""

    def test_calculate_slippage_small_order(self) -> None:
        """Test slippage calculation for small orders."""
        config = RealisticExecutionConfig(
            base_slippage_bps=5.0,
            size_impact_factor=0.5,
        )
        model = RealisticExecutionModel(config)
        bar = make_bar(close=Decimal('100.00'), volume=1000000)

        # Small order (100 shares out of 1M volume = 0.01%)
        slippage = model.calculate_slippage(Decimal('100'), bar, is_buy=True)

        # Should be close to base slippage (5 bps = 0.05%)
        expected_base = Decimal('100.00') * Decimal('5') / Decimal('10000')
        assert abs(slippage - expected_base) < Decimal('0.01')

    def test_calculate_slippage_large_order(self) -> None:
        """Test slippage calculation for large orders."""
        config = RealisticExecutionConfig(
            base_slippage_bps=5.0,
            size_impact_factor=0.5,
            max_slippage_bps=50.0,
        )
        model = RealisticExecutionModel(config)
        bar = make_bar(close=Decimal('100.00'), volume=1000000)

        # Large order (100,000 shares = 10% of volume)
        slippage = model.calculate_slippage(Decimal('100000'), bar, is_buy=True)

        # Should be larger than small order slippage
        small_slippage = model.calculate_slippage(Decimal('100'), bar, is_buy=True)
        assert slippage > small_slippage

    def test_calculate_slippage_max_cap(self) -> None:
        """Test that slippage is capped at max_slippage_bps."""
        config = RealisticExecutionConfig(
            base_slippage_bps=5.0,
            size_impact_factor=10.0,  # High impact factor
            max_slippage_bps=50.0,
        )
        model = RealisticExecutionModel(config)
        bar = make_bar(close=Decimal('100.00'), volume=100)  # Low volume

        # Huge order relative to volume
        slippage = model.calculate_slippage(Decimal('100'), bar, is_buy=True)

        # Should be capped at max (50 bps)
        max_slippage = Decimal('100.00') * Decimal('50') / Decimal('10000')
        assert slippage == max_slippage

    def test_calculate_slippage_direction(self) -> None:
        """Test slippage direction (adverse)."""
        model = RealisticExecutionModel()
        bar = make_bar(close=Decimal('100.00'))

        buy_slip = model.calculate_slippage(Decimal('100'), bar, is_buy=True)
        sell_slip = model.calculate_slippage(Decimal('100'), bar, is_buy=False)

        # Buy should have positive slippage (higher price)
        assert buy_slip > 0
        # Sell should have negative slippage (lower price)
        assert sell_slip < 0

    def test_calculate_fill_quantity_within_limit(self) -> None:
        """Test fill quantity when within volume limit."""
        config = RealisticExecutionConfig(
            max_volume_participation=0.05,
            enable_volume_fill_limits=True,
        )
        model = RealisticExecutionModel(config)
        bar = make_bar(volume=1000000)

        # Order for 10,000 shares (1% of volume, under 5% limit)
        qty, is_partial = model.calculate_fill_quantity(Decimal('10000'), bar)

        assert qty == Decimal('10000')
        assert is_partial is False

    def test_calculate_fill_quantity_exceeds_limit(self) -> None:
        """Test fill quantity when exceeding volume limit."""
        config = RealisticExecutionConfig(
            max_volume_participation=0.05,
            enable_volume_fill_limits=True,
        )
        model = RealisticExecutionModel(config)
        bar = make_bar(volume=1000000)

        # Order for 100,000 shares (10% of volume, exceeds 5% limit)
        qty, is_partial = model.calculate_fill_quantity(Decimal('100000'), bar)

        assert qty == Decimal('50000')  # 5% of 1M
        assert is_partial is True

    def test_calculate_fill_quantity_low_volume(self) -> None:
        """Test fill quantity with low bar volume."""
        config = RealisticExecutionConfig(
            min_bar_volume=100,
            enable_volume_fill_limits=True,
        )
        model = RealisticExecutionModel(config)
        bar = make_bar(volume=50)  # Below min

        qty, is_partial = model.calculate_fill_quantity(Decimal('100'), bar)

        assert qty == Decimal('0')
        assert is_partial is True

    def test_estimate_spread(self) -> None:
        """Test bid-ask spread estimation."""
        config = RealisticExecutionConfig(
            spread_estimate_bps=10.0,
            use_dynamic_spread=True,
            spread_volatility_factor=0.1,
        )
        model = RealisticExecutionModel(config)
        bar = make_bar(
            close=Decimal('100.00'),
            high=Decimal('102.00'),
            low=Decimal('98.00'),
        )

        spread = model.estimate_spread(bar)

        # Should be based on bar range (4) * factor (0.1) = 0.4
        # But minimum is 10 bps of close = 0.10
        assert spread >= Decimal('0.10')

    def test_calculate_market_impact(self) -> None:
        """Test market impact calculation."""
        config = RealisticExecutionConfig(
            temporary_impact_factor=0.1,
            permanent_impact_factor=0.01,
            enable_market_impact=True,
        )
        model = RealisticExecutionModel(config)
        bar = make_bar(close=Decimal('100.00'), volume=1000000)

        temp, perm = model.calculate_market_impact(Decimal('10000'), bar)

        # Should have non-zero impact
        assert temp > 0
        assert perm > 0
        # Temporary should be larger than permanent
        assert temp > perm

    def test_calculate_commission(self) -> None:
        """Test commission calculation."""
        config = RealisticExecutionConfig(
            commission_per_share=Decimal('0.005'),
            min_commission=Decimal('1.00'),
        )
        model = RealisticExecutionModel(config)

        # Large order
        comm_large = model.calculate_commission(Decimal('1000'))
        assert comm_large == Decimal('5.00')

        # Small order (hits minimum)
        comm_small = model.calculate_commission(Decimal('10'))
        assert comm_small == Decimal('1.00')


class TestExecutionCosts:
    """Tests for ExecutionCosts."""

    def test_total_calculation(self) -> None:
        """Test total cost calculation."""
        costs = ExecutionCosts(
            slippage=Decimal('10.00'),
            spread_cost=Decimal('5.00'),
            temporary_impact=Decimal('3.00'),
            permanent_impact=Decimal('1.00'),
            commission=Decimal('2.00'),
        )

        # Total should exclude permanent impact
        expected = Decimal('10.00') + Decimal('5.00') + Decimal('3.00') + Decimal('2.00')
        assert costs.total == expected


class TestFillResult:
    """Tests for FillResult."""

    def test_fill_result_creation(self) -> None:
        """Test creating a fill result."""
        costs = ExecutionCosts(commission=Decimal('5.00'))
        result = FillResult(
            fill_price=Decimal('150.05'),
            fill_quantity=Decimal('100'),
            is_partial=False,
            costs=costs,
            reason='full_fill',
        )

        assert result.fill_price == Decimal('150.05')
        assert result.fill_quantity == Decimal('100')
        assert result.is_partial is False
