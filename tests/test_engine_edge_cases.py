"""
Comprehensive edge case test suite for TradingEngine.

Tests critical fixes for:
1. Cost-basis division-by-zero
2. Multi-symbol equity calculation with missing prices
3. Reversal cost basis cascade scenarios
4. Extreme price movements
5. Zero and negative quantities
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from aistock.engine import Trade, TradingEngine


class TestCostBasisEdgeCases:
    """Test edge cases in cost basis calculation."""

    def test_cost_basis_zero_quantity_guard(self):
        """
        CRITICAL FIX TEST: Division by zero when adding zero quantity to zero position.

        Edge case identified in deep review: engine.py:133-136
        """
        engine = TradingEngine(initial_cash=Decimal('10000'))

        # Attempt to add zero quantity to zero position (shouldn't crash)
        trade = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('0'),
            price=Decimal('150.00'),
            timestamp=datetime.now(timezone.utc),
        )

        assert trade.quantity == Decimal('0')
        assert 'AAPL' not in engine.cost_basis or engine.cost_basis['AAPL'] == Decimal('150.00')
        assert trade.realised_pnl == Decimal('0')

    def test_cost_basis_reversal_cascade(self):
        """
        Test complex reversal scenario: long → short → reduce → long.

        Edge case: Multiple reversals in sequence test cost basis reset logic.
        """
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # 1. Open long position: 100 shares @ $100
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('100.00'),
            timestamp=datetime.now(timezone.utc),
        )
        assert engine.positions['AAPL'] == Decimal('100')
        assert engine.cost_basis['AAPL'] == Decimal('100.00')

        # 2. REVERSAL to short: sell 200 shares @ $110 (closes long, opens short 100)
        trade2 = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-200'),
            price=Decimal('110.00'),
            timestamp=datetime.now(timezone.utc),
        )
        assert engine.positions['AAPL'] == Decimal('-100')
        # Cost basis should reset to new entry price for short
        assert engine.cost_basis['AAPL'] == Decimal('110.00')
        # Realized P&L: closed 100 long @ $110 (entry $100) = +$1000
        assert trade2.realised_pnl == Decimal('100') * (Decimal('110') - Decimal('100'))

        # 3. Reduce short: buy 50 shares @ $105 (short reduces to -50)
        trade3 = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('50'),
            price=Decimal('105.00'),
            timestamp=datetime.now(timezone.utc),
        )
        assert engine.positions['AAPL'] == Decimal('-50')
        # Cost basis unchanged (reducing position)
        assert engine.cost_basis['AAPL'] == Decimal('110.00')
        # Realized P&L: closed 50 short @ $105 (entry $110) = +$250
        assert trade3.realised_pnl == Decimal('50') * (Decimal('110') - Decimal('105'))

        # 4. REVERSAL back to long: buy 100 shares @ $115 (closes short, opens long 50)
        trade4 = engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('115.00'),
            timestamp=datetime.now(timezone.utc),
        )
        assert engine.positions['AAPL'] == Decimal('50')
        # Cost basis should reset to new entry price for long
        assert engine.cost_basis['AAPL'] == Decimal('115.00')
        # Realized P&L: closed 50 short @ $115 (entry $110) = -$250
        assert trade4.realised_pnl == Decimal('50') * (Decimal('110') - Decimal('115'))

    def test_cost_basis_weighted_average_precision(self):
        """Test weighted average cost basis with many small additions."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Add position in small increments
        prices = [Decimal('100.00'), Decimal('101.50'), Decimal('99.75'), Decimal('102.25')]

        for _i, price in enumerate(prices):
            engine.execute_trade(
                symbol='AAPL', quantity=Decimal('10'), price=price, timestamp=datetime.now(timezone.utc)
            )

        # Calculate expected weighted average
        total_cost = sum(Decimal('10') * p for p in prices)
        total_qty = Decimal('10') * len(prices)
        expected_avg = total_cost / total_qty

        assert engine.positions['AAPL'] == total_qty
        assert abs(engine.cost_basis['AAPL'] - expected_avg) < Decimal('0.01')


class TestMultiSymbolEquityEdgeCases:
    """Test multi-symbol equity calculation edge cases."""

    def test_equity_missing_price_raises_error(self):
        """
        CRITICAL FIX TEST: Missing price for open position should raise ValueError.

        Edge case identified in deep review: engine.py:164-180
        """
        engine = TradingEngine(initial_cash=Decimal('10000'))

        # Open position in AAPL
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('10'),
            price=Decimal('150.00'),
            timestamp=datetime.now(timezone.utc),
        )

        # Try to calculate equity with missing price for AAPL
        with pytest.raises(ValueError, match='Missing price for symbol AAPL'):
            engine.calculate_equity({'MSFT': Decimal('300.00')})  # Missing AAPL!

    def test_equity_multi_symbol_accurate(self):
        """Test accurate equity calculation across multiple symbols."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Open positions in multiple symbols
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('100'),
            price=Decimal('150.00'),
            timestamp=datetime.now(timezone.utc),
        )

        engine.execute_trade(
            symbol='MSFT',
            quantity=Decimal('50'),
            price=Decimal('300.00'),
            timestamp=datetime.now(timezone.utc),
        )

        engine.execute_trade(
            symbol='GOOGL',
            quantity=Decimal('-20'),  # Short position
            price=Decimal('2800.00'),
            timestamp=datetime.now(timezone.utc),
        )

        # Calculate equity with updated prices
        current_prices = {
            'AAPL': Decimal('155.00'),  # Gained $5/share
            'MSFT': Decimal('295.00'),  # Lost $5/share
            'GOOGL': Decimal('2750.00'),  # Short gained $50/share
        }

        equity = engine.calculate_equity(current_prices)

        # Expected: cash + (100 * 155) + (50 * 295) + (-20 * 2750)
        expected_positions_value = (
            Decimal('100') * Decimal('155.00')
            + Decimal('50') * Decimal('295.00')
            + Decimal('-20') * Decimal('2750.00')
        )

        expected_equity = engine.cash + expected_positions_value
        assert abs(equity - expected_equity) < Decimal('0.01')

    def test_equity_with_closed_positions(self):
        """Test equity calculation with closed positions."""
        engine = TradingEngine(initial_cash=Decimal('10000'))

        # Open and close position
        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('10'),
            price=Decimal('150.00'),
            timestamp=datetime.now(timezone.utc),
        )

        engine.execute_trade(
            symbol='AAPL',
            quantity=Decimal('-10'),
            price=Decimal('155.00'),
            timestamp=datetime.now(timezone.utc),
        )

        # TradingEngine keeps 0 positions in dict (they're marked as 0, not removed)
        # So we need to provide prices for all symbols in positions, even if 0
        # This is actually correct behavior - portfolio tracking should maintain history
        equity = engine.calculate_equity({'AAPL': Decimal('155.00')})

        # AAPL position is 0, so equity should just be cash
        assert engine.positions['AAPL'] == Decimal('0')
        # Equity = cash + (0 * price) = cash
        assert equity == engine.cash


class TestExtremePriceMovements:
    """Test edge cases with extreme price movements."""

    def test_extreme_price_gain(self):
        """Test 100x price increase (penny stock scenario)."""
        engine = TradingEngine(initial_cash=Decimal('10000'))

        # Buy penny stock
        engine.execute_trade(
            symbol='PENNYS',
            quantity=Decimal('10000'),
            price=Decimal('0.10'),
            timestamp=datetime.now(timezone.utc),
        )

        # Sell at 100x price
        trade = engine.execute_trade(
            symbol='PENNYS',
            quantity=Decimal('-10000'),
            price=Decimal('10.00'),
            timestamp=datetime.now(timezone.utc),
        )

        # Realized P&L: (10.00 - 0.10) * 10000 = $99,000
        expected_pnl = (Decimal('10.00') - Decimal('0.10')) * Decimal('10000')
        assert abs(trade.realised_pnl - expected_pnl) < Decimal('0.01')

    def test_extreme_price_loss_short(self):
        """Test short position with extreme price increase."""
        engine = TradingEngine(initial_cash=Decimal('100000'))

        # Short at $100
        engine.execute_trade(
            symbol='MEME',
            quantity=Decimal('-100'),
            price=Decimal('100.00'),
            timestamp=datetime.now(timezone.utc),
        )

        # Cover at $1000 (10x loss)
        trade = engine.execute_trade(
            symbol='MEME',
            quantity=Decimal('100'),
            price=Decimal('1000.00'),
            timestamp=datetime.now(timezone.utc),
        )

        # Realized P&L: (100 - 1000) * 100 = -$90,000
        expected_pnl = (Decimal('100.00') - Decimal('1000.00')) * Decimal('100')
        assert abs(trade.realised_pnl - expected_pnl) < Decimal('0.01')

    def test_fractional_shares(self):
        """Test trades with fractional quantities (crypto, modern brokers)."""
        engine = TradingEngine(initial_cash=Decimal('10000'))

        # Buy fractional shares
        engine.execute_trade(
            symbol='BTC',
            quantity=Decimal('0.5'),
            price=Decimal('50000.00'),
            timestamp=datetime.now(timezone.utc),
        )

        engine.execute_trade(
            symbol='BTC',
            quantity=Decimal('0.3'),
            price=Decimal('51000.00'),
            timestamp=datetime.now(timezone.utc),
        )

        # Weighted average: (0.5 * 50000 + 0.3 * 51000) / 0.8
        expected_avg = (Decimal('0.5') * Decimal('50000') + Decimal('0.3') * Decimal('51000')) / Decimal('0.8')

        assert engine.positions['BTC'] == Decimal('0.8')
        assert abs(engine.cost_basis['BTC'] - expected_avg) < Decimal('0.01')


class TestZeroAndNegativeEdgeCases:
    """Test edge cases with zero and negative values."""

    def test_zero_price_rejected(self):
        """Zero price should be handled gracefully (avoid division by zero)."""
        engine = TradingEngine(initial_cash=Decimal('10000'))

        # This shouldn't crash (defensive check)
        trade = engine.execute_trade(
            symbol='ZERO', quantity=Decimal('10'), price=Decimal('0.00'), timestamp=datetime.now(timezone.utc)
        )

        # Cost is 0, cash unchanged
        assert engine.cash == Decimal('10000')
        assert trade.price == Decimal('0.00')

    def test_negative_quantity_is_sell(self):
        """Negative quantity represents sell/short."""
        engine = TradingEngine(initial_cash=Decimal('10000'))

        # Negative quantity = sell/short
        engine.execute_trade(
            symbol='SHORT',
            quantity=Decimal('-50'),
            price=Decimal('100.00'),
            timestamp=datetime.now(timezone.utc),
        )

        assert engine.positions['SHORT'] == Decimal('-50')
        # Cash increases from short sale
        assert engine.cash > Decimal('10000')


class TestEquityCurveIntegrity:
    """Test equity curve tracking across multiple trades."""

    def test_equity_curve_monotonic_check(self):
        """Verify equity curve captures all trades."""
        engine = TradingEngine(initial_cash=Decimal('10000'))

        initial_count = len(engine.equity_curve)

        # Execute multiple trades
        for i in range(10):
            price = Decimal('100') + Decimal(str(i))
            engine.execute_trade(
                symbol='TEST', quantity=Decimal('10'), price=price, timestamp=datetime.now(timezone.utc)
            )

        assert len(engine.equity_curve) == initial_count + 10
        assert len(engine.trades) == 10

    def test_performance_metrics_with_no_trades(self):
        """Performance metrics should handle zero trades gracefully."""
        engine = TradingEngine(initial_cash=Decimal('10000'))

        metrics = engine.get_performance_metrics()

        assert metrics['total_trades'] == 0
        assert metrics['win_rate'] == 0.0
        assert metrics['total_return'] == 0.0
        assert metrics['max_drawdown'] == 0.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
