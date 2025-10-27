"""
Comprehensive Risk Manager Tests

Tests all risk control mechanisms including:
- Daily loss limits
- Max drawdown limits
- Drawdown recovery
- Pre-trade risk checks
- Position sizing limits
- Daily reset behavior
- Edge cases and boundary conditions
"""

import os
import sys
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from managers.portfolio_manager import PortfolioManager
from managers.risk_manager import RiskManager


@pytest.fixture
def settings():
    """Create settings with known risk limits."""
    s = Settings()
    s.MAX_DAILY_LOSS = 0.05  # 5%
    s.MAX_DRAWDOWN_LIMIT = 0.10  # 10%
    s.DRAWDOWN_RECOVERY_THRESHOLD_FACTOR = 0.8  # Recover at 8%
    s.MAX_SINGLE_POSITION_PERCENT = 0.25  # 25%
    s.TIMEZONE = 'America/New_York'
    s.RISK_PER_TRADE = 0.01  # 1%
    return s


@pytest.fixture
def portfolio_manager(settings):
    """Create a portfolio manager with known state."""
    logger = Mock()
    pm = PortfolioManager(settings, logger)
    pm.initial_capital = 10000.0
    pm.total_equity = 10000.0
    pm.peak_equity = 10000.0
    pm.daily_pnl = 0.0
    return pm


@pytest.fixture
def risk_manager(portfolio_manager, settings):
    """Create a risk manager."""
    logger = Mock()
    return RiskManager(portfolio_manager, settings, logger)


class TestDailyLossLimits:
    """Test daily loss limit enforcement."""

    def test_exceeding_daily_loss_halts_trading(self, risk_manager, portfolio_manager, settings):
        """Test that exceeding daily loss limit halts trading."""
        # Simulate 6% daily loss (exceeds 5% limit)
        portfolio_manager.daily_pnl = -600.0  # -6% of 10000
        portfolio_manager.total_equity = 9400.0

        risk_manager.check_portfolio_risk({})

        assert risk_manager.is_trading_halted()
        assert 'daily loss' in risk_manager.get_halt_reason().lower()
        assert not risk_manager._halted_by_drawdown

    def test_exactly_at_daily_loss_limit_no_halt(self, risk_manager, portfolio_manager):
        """Test that being exactly at the limit doesn't halt (uses isclose)."""
        # Exactly at 5% loss
        portfolio_manager.daily_pnl = -500.0
        portfolio_manager.total_equity = 9500.0

        risk_manager.check_portfolio_risk({})

        assert not risk_manager.is_trading_halted()

    def test_within_daily_loss_limit_no_halt(self, risk_manager, portfolio_manager):
        """Test that staying within limit doesn't halt."""
        # 3% daily loss (within 5% limit)
        portfolio_manager.daily_pnl = -300.0
        portfolio_manager.total_equity = 9700.0

        risk_manager.check_portfolio_risk({})

        assert not risk_manager.is_trading_halted()

    def test_positive_daily_pnl_no_halt(self, risk_manager, portfolio_manager):
        """Test that positive PnL doesn't trigger halt."""
        portfolio_manager.daily_pnl = 500.0
        portfolio_manager.total_equity = 10500.0

        risk_manager.check_portfolio_risk({})

        assert not risk_manager.is_trading_halted()


class TestMaxDrawdownLimits:
    """Test maximum drawdown limit enforcement."""

    def test_exceeding_max_drawdown_halts_trading(self, risk_manager, portfolio_manager):
        """Test that exceeding max drawdown halts trading."""
        # 12% drawdown (exceeds 10% limit)
        portfolio_manager.peak_equity = 10000.0
        portfolio_manager.total_equity = 8800.0
        portfolio_manager.daily_pnl = -1200.0

        risk_manager.check_portfolio_risk({})

        assert risk_manager.is_trading_halted()
        assert risk_manager._halted_by_drawdown
        assert 'drawdown' in risk_manager.get_halt_reason().lower()

    def test_exactly_at_drawdown_limit_no_halt(self, risk_manager, portfolio_manager):
        """Test that being exactly at the limit doesn't halt (uses isclose)."""
        # Exactly 10% drawdown
        portfolio_manager.peak_equity = 10000.0
        portfolio_manager.total_equity = 9000.0
        portfolio_manager.daily_pnl = -1000.0

        risk_manager.check_portfolio_risk({})

        assert not risk_manager.is_trading_halted()

    def test_within_drawdown_limit_no_halt(self, risk_manager, portfolio_manager):
        """Test that staying within limit doesn't halt."""
        # 8% drawdown (within 10% limit)
        portfolio_manager.peak_equity = 10000.0
        portfolio_manager.total_equity = 9200.0
        portfolio_manager.daily_pnl = -800.0

        risk_manager.check_portfolio_risk({})

        assert not risk_manager.is_trading_halted()


class TestDrawdownRecovery:
    """Test drawdown recovery mechanism."""

    def test_drawdown_recovery_resumes_trading(self, risk_manager, portfolio_manager, settings):
        """Test that recovering from drawdown resumes trading."""
        # First trigger drawdown halt (12% drawdown)
        portfolio_manager.peak_equity = 10000.0
        portfolio_manager.total_equity = 8800.0
        portfolio_manager.daily_pnl = -1200.0
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()
        assert risk_manager._halted_by_drawdown

        # Recover to 7% drawdown (below 80% of 10% limit = 8%)
        portfolio_manager.total_equity = 9300.0
        portfolio_manager.daily_pnl = -700.0
        risk_manager.check_portfolio_risk({})

        assert not risk_manager.is_trading_halted()
        assert not risk_manager._halted_by_drawdown

    def test_partial_recovery_keeps_halt(self, risk_manager, portfolio_manager):
        """Test that partial recovery doesn't resume trading."""
        # Trigger halt at 12% drawdown
        portfolio_manager.peak_equity = 10000.0
        portfolio_manager.total_equity = 8800.0
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()

        # Partial recovery to 9% (still above 8% threshold)
        portfolio_manager.total_equity = 9100.0
        risk_manager.check_portfolio_risk({})

        assert risk_manager.is_trading_halted()
        assert risk_manager._halted_by_drawdown

    def test_recovery_threshold_boundary(self, risk_manager, portfolio_manager, settings):
        """Test behavior exactly at recovery threshold."""
        # Trigger halt
        portfolio_manager.peak_equity = 10000.0
        portfolio_manager.total_equity = 8800.0
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()

        # Recover to exactly 8% (threshold)
        recovery_threshold = settings.MAX_DRAWDOWN_LIMIT * settings.DRAWDOWN_RECOVERY_THRESHOLD_FACTOR
        portfolio_manager.total_equity = 10000.0 * (1 - recovery_threshold)
        risk_manager.check_portfolio_risk({})

        # Should resume (< threshold due to float comparison)
        assert not risk_manager.is_trading_halted()


class TestDailyReset:
    """Test daily reset behavior."""

    def test_daily_reset_clears_daily_loss_halt(self, risk_manager, portfolio_manager, settings):
        """Test that daily reset clears daily loss halt."""
        # Trigger daily loss halt
        portfolio_manager.daily_pnl = -600.0
        portfolio_manager.total_equity = 9400.0
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()
        assert not risk_manager._halted_by_drawdown

        # Simulate new day
        tz = pytz.timezone(settings.TIMEZONE)
        today = datetime.now(tz).date()
        risk_manager._last_daily_reset_date = today - timedelta(days=1)

        # Reset daily PnL (would happen in PM)
        portfolio_manager.daily_pnl = 0.0

        # Check should reset halt
        risk_manager.check_portfolio_risk({})

        assert not risk_manager.is_trading_halted()

    def test_daily_reset_does_not_clear_drawdown_halt(self, risk_manager, portfolio_manager, settings):
        """Test that daily reset doesn't clear drawdown halt."""
        # Trigger drawdown halt
        portfolio_manager.peak_equity = 10000.0
        portfolio_manager.total_equity = 8800.0
        portfolio_manager.daily_pnl = -1200.0
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()
        assert risk_manager._halted_by_drawdown

        # Simulate new day
        tz = pytz.timezone(settings.TIMEZONE)
        today = datetime.now(tz).date()
        risk_manager._last_daily_reset_date = today - timedelta(days=1)

        # Reset daily PnL
        portfolio_manager.daily_pnl = 0.0

        # Check - drawdown halt should persist
        risk_manager.check_portfolio_risk({})

        assert risk_manager.is_trading_halted()
        assert risk_manager._halted_by_drawdown


class TestPreTradeRiskChecks:
    """Test pre-trade risk validation."""

    def test_pre_trade_check_passes_within_limits(self, risk_manager, portfolio_manager):
        """Test that valid trade passes pre-trade checks."""
        result = risk_manager.check_pre_trade_risk('TEST', 'BUY', 10, 100.0, available_funds=5000.0)

        assert result

    def test_pre_trade_check_fails_when_halted(self, risk_manager, portfolio_manager):
        """Test that pre-trade check fails when trading is halted."""
        # Trigger halt
        portfolio_manager.daily_pnl = -600.0
        risk_manager.check_portfolio_risk({})

        result = risk_manager.check_pre_trade_risk('TEST', 'BUY', 10, 100.0, available_funds=5000.0)

        assert not result

    def test_pre_trade_check_fails_exceeding_position_limit(self, risk_manager, portfolio_manager, settings):
        """Test that trade exceeding position limit fails."""
        portfolio_manager.total_equity = 10000.0
        # MAX_SINGLE_POSITION_PERCENT = 0.25 means max $2500 position
        # Try to buy 30 shares @ $100 = $3000 (exceeds limit)

        result = risk_manager.check_pre_trade_risk('TEST', 'BUY', 30, 100.0, available_funds=5000.0)

        assert not result

    def test_pre_trade_check_fails_insufficient_funds(self, risk_manager, portfolio_manager):
        """Test that trade with insufficient funds fails."""
        result = risk_manager.check_pre_trade_risk('TEST', 'BUY', 100, 100.0, available_funds=500.0)

        assert not result

    def test_pre_trade_check_considers_existing_position(self, risk_manager, portfolio_manager, settings):
        """Test that existing position is considered in limit check."""
        portfolio_manager.total_equity = 10000.0
        # Add existing position: 15 shares @ $100 = $1500
        portfolio_manager.positions['TEST'] = {'quantity': 15, 'avg_price': 100.0}

        # Try to buy 15 more shares @ $100 = $1500
        # Total would be 30 shares = $3000 (exceeds 25% limit of $2500)
        result = risk_manager.check_pre_trade_risk('TEST', 'BUY', 15, 100.0, available_funds=5000.0)

        assert not result

    def test_pre_trade_check_allows_position_reduction(self, risk_manager, portfolio_manager):
        """Test that reducing position is allowed even if over limit."""
        portfolio_manager.total_equity = 10000.0
        # Existing large position: 30 shares @ $100 = $3000 (over limit)
        portfolio_manager.positions['TEST'] = {'quantity': 30, 'avg_price': 100.0}

        # Sell 10 shares (reducing position)
        result = risk_manager.check_pre_trade_risk('TEST', 'SELL', 10, 100.0, available_funds=10000.0)

        assert result


class TestManualControls:
    """Test manual halt and resume controls."""

    def test_force_halt(self, risk_manager):
        """Test manual halt."""
        assert not risk_manager.is_trading_halted()

        risk_manager.force_halt('Testing manual halt')

        assert risk_manager.is_trading_halted()
        assert 'manual halt' in risk_manager.get_halt_reason().lower()

    def test_resume_trading(self, risk_manager, portfolio_manager):
        """Test manual resume."""
        # Trigger halt
        portfolio_manager.daily_pnl = -600.0
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()

        # Manual resume
        risk_manager.resume_trading()

        assert not risk_manager.is_trading_halted()

    def test_force_halt_when_already_halted(self, risk_manager, portfolio_manager):
        """Test that forcing halt when already halted doesn't break."""
        portfolio_manager.daily_pnl = -600.0
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()

        risk_manager.force_halt('Another reason')

        assert risk_manager.is_trading_halted()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_equity_blocks_trades(self, risk_manager, portfolio_manager):
        """Test that zero equity blocks all trades."""
        portfolio_manager.total_equity = 0.0

        result = risk_manager.check_pre_trade_risk('TEST', 'BUY', 10, 100.0, available_funds=5000.0)

        assert not result

    def test_negative_equity_blocks_trades(self, risk_manager, portfolio_manager):
        """Test that negative equity blocks all trades."""
        portfolio_manager.total_equity = -1000.0

        result = risk_manager.check_pre_trade_risk('TEST', 'BUY', 10, 100.0, available_funds=5000.0)

        assert not result

    def test_very_small_daily_loss_no_halt(self, risk_manager, portfolio_manager):
        """Test that tiny losses don't trigger halt."""
        portfolio_manager.daily_pnl = -0.01
        portfolio_manager.total_equity = 9999.99

        risk_manager.check_portfolio_risk({})

        assert not risk_manager.is_trading_halted()

    def test_multiple_checks_maintain_halt_state(self, risk_manager, portfolio_manager):
        """Test that halt state persists across multiple checks."""
        # Trigger halt
        portfolio_manager.daily_pnl = -600.0
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()

        # Run check again without changing conditions
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()

        # Run check a third time
        risk_manager.check_portfolio_risk({})
        assert risk_manager.is_trading_halted()
