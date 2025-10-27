"""
Integration tests for aistock package and Backtrader integration.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pandas as pd

# Test aistock modules
from aistock.config import BacktestConfig, DataSource, EngineConfig, StrategyConfig, RiskConfig
from aistock.data import Bar, load_csv_directory
from aistock.portfolio import Portfolio
from aistock.performance import (
    compute_returns, sharpe_ratio, sortino_ratio, compute_drawdown, trade_performance
)
from aistock.risk import RiskEngine
from aistock.fsd import FSDConfig, FSDEngine, RLAgent


class TestAistockConfig:
    """Test configuration dataclasses."""
    
    def test_backtest_config_validation(self):
        """Test that BacktestConfig validates properly."""
        config = BacktestConfig(
            data=DataSource(path="/tmp", symbols=("AAPL",)),
            engine=EngineConfig(initial_equity=10000.0)
        )
        
        # Should not raise
        config.validate()
        
        # Test invalid config
        bad_config = BacktestConfig(
            data=DataSource(path="/tmp", symbols=("AAPL",)),
            engine=EngineConfig(initial_equity=-1000.0)  # Invalid
        )
        
        with pytest.raises(ValueError, match="initial_equity must be positive"):
            bad_config.validate()


class TestAistockData:
    """Test data structures and loading."""
    
    def test_bar_creation(self):
        """Test Bar dataclass validation."""
        # Valid bar
        bar = Bar(
            symbol="AAPL",
            timestamp=datetime.now(timezone.utc),
            open=Decimal("100.0"),
            high=Decimal("105.0"),
            low=Decimal("99.0"),
            close=Decimal("103.0"),
            volume=1000000
        )
        
        assert bar.symbol == "AAPL"
        assert bar.high >= bar.low
        
    def test_bar_validation_high_low(self):
        """Test that Bar validates high/low relationship."""
        with pytest.raises(ValueError, match="High .* < Low"):
            Bar(
                symbol="AAPL",
                timestamp=datetime.now(timezone.utc),
                open=Decimal("100.0"),
                high=Decimal("99.0"),  # Invalid: high < low
                low=Decimal("100.0"),
                close=Decimal("100.0"),
                volume=1000
            )
    
    def test_bar_validation_open_range(self):
        """Test that Bar validates open is within high/low."""
        with pytest.raises(ValueError, match="Open .* outside High/Low range"):
            Bar(
                symbol="AAPL",
                timestamp=datetime.now(timezone.utc),
                open=Decimal("110.0"),  # Invalid: open > high
                high=Decimal("105.0"),
                low=Decimal("99.0"),
                close=Decimal("103.0"),
                volume=1000
            )


class TestAistockPortfolio:
    """Test portfolio tracking."""
    
    def test_portfolio_initialization(self):
        """Test portfolio starts with correct cash."""
        portfolio = Portfolio(Decimal("10000.0"))
        
        assert portfolio.get_cash() == Decimal("10000.0")
        assert portfolio.get_position("AAPL") == Decimal("0")
    
    def test_portfolio_buy_updates_position(self):
        """Test buying updates position and cash correctly."""
        portfolio = Portfolio(Decimal("10000.0"))
        
        # Buy 10 shares at $100 each
        portfolio.update_position(
            symbol="AAPL",
            quantity_delta=Decimal("10"),
            price=Decimal("100.0"),
            commission=Decimal("1.0")
        )
        
        assert portfolio.get_position("AAPL") == Decimal("10")
        # Cash should be: 10000 - (10 * 100) - 1 = 8999
        assert portfolio.get_cash() == Decimal("8999.0")
        assert portfolio.get_avg_price("AAPL") == Decimal("100.0")
    
    def test_portfolio_sell_updates_position(self):
        """Test selling updates position and cash correctly."""
        portfolio = Portfolio(Decimal("10000.0"))
        
        # Buy first
        portfolio.update_position("AAPL", Decimal("10"), Decimal("100.0"))
        
        # Sell 5 shares at $110
        portfolio.update_position("AAPL", Decimal("-5"), Decimal("110.0"))
        
        assert portfolio.get_position("AAPL") == Decimal("5")
        # Cash: 10000 - 1000 + 550 = 9550
        assert portfolio.get_cash() == Decimal("9550.0")
    
    def test_portfolio_equity_calculation(self):
        """Test equity calculation includes cash + positions."""
        portfolio = Portfolio(Decimal("10000.0"))
        
        # Buy 10 AAPL at $100
        portfolio.update_position("AAPL", Decimal("10"), Decimal("100.0"))
        
        # Current prices: AAPL at $110
        current_prices = {"AAPL": Decimal("110.0")}
        
        equity = portfolio.get_equity(current_prices)
        # Equity = cash (9000) + position value (10 * 110) = 10100
        assert equity == Decimal("10100.0")


class TestAistockPerformance:
    """Test performance metrics."""
    
    def test_compute_returns(self):
        """Test returns calculation from equity curve."""
        equity_curve = [
            (datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal("10000")),
            (datetime(2024, 1, 2, tzinfo=timezone.utc), Decimal("10100")),
            (datetime(2024, 1, 3, tzinfo=timezone.utc), Decimal("10050")),
        ]
        
        returns = compute_returns(equity_curve)
        
        assert len(returns) == 2
        assert abs(returns[0] - 0.01) < 0.0001  # 1% gain
        assert returns[1] < 0  # Loss
    
    def test_sharpe_ratio_calculation(self):
        """Test Sharpe ratio calculation."""
        # Positive returns
        returns = [0.01, 0.02, -0.005, 0.015, 0.01]
        
        sharpe = sharpe_ratio(returns)
        
        assert sharpe > 0  # Positive returns should give positive Sharpe
    
    def test_sharpe_ratio_zero_returns(self):
        """Test Sharpe ratio with zero standard deviation."""
        returns = [0.0, 0.0, 0.0]
        
        sharpe = sharpe_ratio(returns)
        
        assert sharpe == 0.0
    
    def test_compute_drawdown(self):
        """Test drawdown calculation."""
        equity_curve = [
            (datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal("10000")),
            (datetime(2024, 1, 2, tzinfo=timezone.utc), Decimal("11000")),  # Peak
            (datetime(2024, 1, 3, tzinfo=timezone.utc), Decimal("9900")),   # Drawdown
        ]
        
        dd = compute_drawdown(equity_curve)
        
        # Max DD = (11000 - 9900) / 11000 = 0.1 = 10%
        assert abs(float(dd) - 0.1) < 0.001
    
    def test_trade_performance(self):
        """Test trade performance statistics."""
        trade_pnls = [
            Decimal("100"),   # Win
            Decimal("-50"),   # Loss
            Decimal("150"),   # Win
            Decimal("-30"),   # Loss
        ]
        
        perf = trade_performance(trade_pnls)
        
        assert perf.total_trades == 4
        assert perf.winning_trades == 2
        assert perf.losing_trades == 2
        assert perf.win_rate == 0.5
        assert perf.average_win == 125.0
        assert perf.average_loss == -40.0


class TestAistockRisk:
    """Test risk engine."""
    
    def test_risk_engine_initialization(self):
        """Test risk engine initializes correctly."""
        portfolio = Portfolio(Decimal("10000.0"))
        config = RiskConfig(
            max_daily_loss_pct=0.03,
            max_drawdown_pct=0.15,
            risk_per_trade_pct=0.01
        )
        
        risk = RiskEngine(config, portfolio, timedelta(days=1))
        
        assert not risk.is_halted
    
    def test_risk_engine_daily_loss_limit(self):
        """Test risk engine halts on daily loss limit."""
        portfolio = Portfolio(Decimal("10000.0"))
        config = RiskConfig(max_daily_loss_pct=0.03)
        
        risk = RiskEngine(config, portfolio, timedelta(days=1))
        
        # Current equity drops below daily loss limit
        current_equity = Decimal("9600.0")  # -4% loss
        
        with pytest.raises(ValueError, match="Daily loss limit exceeded"):
            risk.check_pre_trade(
                symbol="AAPL",
                quantity_delta=Decimal("10"),
                price=Decimal("100.0"),
                current_equity=current_equity,
                last_prices={}
            )
        
        assert risk.is_halted


class TestFSDEngine:
    """Test FSD reinforcement learning engine."""
    
    def test_fsd_config_creation(self):
        """Test FSD config dataclass."""
        config = FSDConfig(
            learning_rate=0.001,
            discount_factor=0.95,
            exploration_rate=0.1,
            max_capital=10000.0
        )
        
        assert config.learning_rate == 0.001
        assert config.max_capital == 10000.0
    
    def test_rl_agent_initialization(self):
        """Test RL agent initializes."""
        config = FSDConfig()
        agent = RLAgent(config)
        
        assert agent.total_trades == 0
        assert agent.exploration_rate == config.exploration_rate
        assert len(agent.q_values) == 0
    
    def test_rl_agent_action_selection(self):
        """Test RL agent can select actions."""
        config = FSDConfig(exploration_rate=0.0)  # No exploration for deterministic test
        agent = RLAgent(config)
        
        state = {
            'price_change_pct': 0.01,
            'volume_ratio': 1.2,
            'trend': 'up',
            'volatility': 'normal',
            'position_pct': 0.0
        }
        
        action = agent.select_action(state, training=False)
        
        assert action in agent.get_actions()
    
    def test_rl_agent_q_value_update(self):
        """Test RL agent updates Q-values."""
        config = FSDConfig(learning_rate=0.1)
        agent = RLAgent(config)
        
        state = {
            'price_change_pct': 0.01,
            'volume_ratio': 1.0,
            'trend': 'up',
            'volatility': 'normal',
            'position_pct': 0.0
        }
        
        next_state = state.copy()
        next_state['position_pct'] = 0.1
        
        # Update Q-value
        agent.update_q_value(
            state=state,
            action='BUY',
            reward=10.0,
            next_state=next_state,
            done=False
        )
        
        # Q-values should be updated
        assert len(agent.q_values) > 0
    
    def test_fsd_engine_initialization(self):
        """Test FSD engine initializes."""
        config = FSDConfig()
        portfolio = Portfolio(Decimal("10000.0"))
        
        fsd = FSDEngine(config, portfolio)
        
        assert fsd.rl_agent is not None
        assert len(fsd.current_positions) == 0
    
    def test_fsd_engine_state_extraction(self):
        """Test FSD extracts state features."""
        config = FSDConfig()
        portfolio = Portfolio(Decimal("10000.0"))
        fsd = FSDEngine(config, portfolio)
        
        # Create sample bars
        bars = []
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(50):
            bar = Bar(
                symbol="AAPL",
                timestamp=base_time + timedelta(minutes=i),
                open=Decimal("100.0") + Decimal(str(i * 0.1)),
                high=Decimal("101.0") + Decimal(str(i * 0.1)),
                low=Decimal("99.0") + Decimal(str(i * 0.1)),
                close=Decimal("100.5") + Decimal(str(i * 0.1)),
                volume=1000000
            )
            bars.append(bar)
        
        state = fsd.extract_state(
            symbol="AAPL",
            bars=bars,
            last_prices={"AAPL": Decimal("105.0")}
        )
        
        assert 'price_change_pct' in state
        assert 'trend' in state
        assert 'volatility' in state
        assert state['trend'] in ['up', 'down', 'neutral']


class TestBacktraderIntegration:
    """Test Backtrader integration (requires backtrader installed)."""
    
    def test_imports(self):
        """Test that backtrader integration can be imported."""
        try:
            from aistock import backtrader_integration
            assert hasattr(backtrader_integration, 'run_backtest')
            assert hasattr(backtrader_integration, 'FSDStrategy')
            assert hasattr(backtrader_integration, 'BOTStrategy')
        except ImportError as e:
            pytest.skip(f"Backtrader not installed: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
