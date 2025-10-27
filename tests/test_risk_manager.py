# tests/test_risk_manager.py
"""Tests for risk management and halt conditions."""

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
    s.DRAWDOWN_RECOVERY_THRESHOLD_FACTOR = 0.8
    s.TIMEZONE = 'America/New_York'
    return s


@pytest.fixture
def portfolio_manager(settings):
    """Create a portfolio manager."""
    logger = Mock()
    pm = PortfolioManager(settings, logger)
    pm.initial_capital = 10000.0
    pm.total_equity = 10000.0
    pm.peak_equity = 10000.0
    return pm


@pytest.fixture
def risk_manager(portfolio_manager, settings):
    """Create a risk manager."""
    logger = Mock()
    return RiskManager(portfolio_manager, settings, logger)


def test_daily_loss_limit_triggers_halt(risk_manager, portfolio_manager, settings):
    """Test that exceeding daily loss limit halts trading."""
    # Simulate a 6% daily loss (exceeds 5% limit)
    portfolio_manager.daily_pnl = -600.0  # -6% of 10000
    portfolio_manager.total_equity = 9400.0

    risk_manager.check_portfolio_risk({})

    assert risk_manager.is_trading_halted()
    assert 'daily loss' in risk_manager.get_halt_reason().lower()


def test_daily_loss_within_limit_no_halt(risk_manager, portfolio_manager):
    """Test that staying within daily loss limit doesn't halt."""
    # Simulate a 3% daily loss (within 5% limit)
    portfolio_manager.daily_pnl = -300.0  # -3% of 10000
    portfolio_manager.total_equity = 9700.0

    risk_manager.check_portfolio_risk({})

    assert not risk_manager.is_trading_halted()


def test_max_drawdown_triggers_halt(risk_manager, portfolio_manager, settings):
    """Test that exceeding max drawdown halts trading."""
    # Set peak and create 12% drawdown (exceeds 10% limit)
    portfolio_manager.peak_equity = 10000.0
    portfolio_manager.total_equity = 8800.0  # 12% drawdown
    portfolio_manager.daily_pnl = -1200.0

    risk_manager.check_portfolio_risk({})

    assert risk_manager.is_trading_halted()
    assert risk_manager._halted_by_drawdown


def test_drawdown_recovery_resumes_trading(risk_manager, portfolio_manager, settings):
    """Test that recovering from drawdown resumes trading."""
    # First trigger drawdown halt (12% drawdown)
    portfolio_manager.peak_equity = 10000.0
    portfolio_manager.total_equity = 8800.0
    portfolio_manager.daily_pnl = -1200.0
    risk_manager.check_portfolio_risk({})
    assert risk_manager.is_trading_halted()

    # Recover to 7% drawdown (below 80% of 10% limit = 8%)
    portfolio_manager.total_equity = 9300.0
    portfolio_manager.daily_pnl = -700.0
    risk_manager.check_portfolio_risk({})

    assert not risk_manager.is_trading_halted()
    assert not risk_manager._halted_by_drawdown


def test_daily_reset_clears_daily_loss_halt(risk_manager, portfolio_manager, settings):
    """Test that daily reset clears daily loss halt but not drawdown halt."""
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

    # Reset daily PnL
    portfolio_manager.daily_pnl = 0.0

    # Check should reset halt
    risk_manager.check_portfolio_risk({})

    assert not risk_manager.is_trading_halted()


def test_pre_trade_risk_checks():
    """Test pre-trade risk validation."""
    settings = Settings()
    settings.MAX_SINGLE_POSITION_PERCENT = 0.25
    logger = Mock()
    pm = PortfolioManager(settings, logger)
    pm.total_equity = 10000.0

    rm = RiskManager(pm, settings, logger)

    # Test position size within limits
    result = rm.check_pre_trade_risk('TEST', 'BUY', 10, 100.0, available_funds=5000.0)
    assert result

    # Test position size exceeding max single position
    result = rm.check_pre_trade_risk('TEST', 'BUY', 30, 100.0, available_funds=5000.0)
    # Should fail if position value (30*100=3000) exceeds 25% of equity (2500)
    assert not result


def test_halt_persists_across_checks(risk_manager, portfolio_manager):
    """Test that halt state persists until conditions clear."""
    # Trigger halt
    portfolio_manager.daily_pnl = -600.0
    risk_manager.check_portfolio_risk({})
    assert risk_manager.is_trading_halted()

    # Run check again without changing conditions
    risk_manager.check_portfolio_risk({})
    assert risk_manager.is_trading_halted()
