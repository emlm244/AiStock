"""
Backtrader Integration - Professional Backtesting Infrastructure

This module provides a production-ready Backtrader integration that replaces
all custom backtesting code while preserving 100% of the intelligence.

Features:
- FSD (Full Self-Driving) strategy wrapper
- BOT (rule-based) strategy wrapper  
- Data feed conversion from our CSV format
- Portfolio and risk integration
- Performance metrics and reporting

The intelligence (FSD, ML, Risk) remains UNCHANGED - Backtrader just handles
the infrastructure (data loading, order execution, portfolio tracking).
"""

from __future__ import annotations

import backtrader as bt
import pandas as pd
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import BacktestConfig, StrategyConfig
from .data import Bar, load_csv_directory
from .fsd import FSDConfig, FSDEngine
from .performance import compute_drawdown, compute_returns, sharpe_ratio, sortino_ratio, trade_performance
from .portfolio import Portfolio
from .risk import RiskEngine
from .strategy import StrategyContext, default_strategy_suite
from .universe import UniverseSelectionResult, UniverseSelector


class FSDStrategy(bt.Strategy):
    """
    Backtrader strategy that wraps our FSD reinforcement learning.
    
    This is a WRAPPER - all intelligence comes from FSD!
    Backtrader just provides:
    - Data management
    - Portfolio tracking
    - Order execution simulation
    - Performance metrics
    
    FSD does:
    - ALL trading decisions
    - ALL learning
    - ALL pattern recognition
    """
    
    params = (
        ('fsd_config', None),  # FSDConfig object
        ('verbose', False),    # Log decisions
    )
    
    def __init__(self):
        """Initialize FSD engine (our intelligence!)."""
        
        # Create our custom portfolio tracker (for FSD)
        initial_cash = self.broker.get_cash()
        self.custom_portfolio = Portfolio(Decimal(str(initial_cash)))
        
        # Create FSD engine (THE BRAIN - unchanged!)
        fsd_config = self.p.fsd_config  # Access params via self.p
        if fsd_config is None:
            raise ValueError("Must provide fsd_config parameter")
        
        self.fsd = FSDEngine(fsd_config, self.custom_portfolio)
        
        # Track last prices for all symbols
        self.last_prices = {}
        self.order_id_counter = 0
        self.recorded_trades = []  # Store trades here for retrieval
        
        # Logging
        if self.p.verbose:
            print(f"FSD Strategy initialized with {len(self.datas)} symbols")
    
    def next(self):
        """
        Called by Backtrader for each bar.
        
        We delegate ALL decision-making to FSD!
        """
        # Update last prices from all data feeds
        for data in self.datas:
            symbol = data._name
            self.last_prices[symbol] = Decimal(str(data.close[0]))
        
        # Let FSD evaluate EACH symbol
        for data in self.datas:
            symbol = data._name
            
            # Build bar history for this symbol
            bars = self._get_bars(data)
            
            if len(bars) < 50:
                continue  # Need warmup bars
            
            # FSD MAKES THE DECISION (our intelligence!)
            decision = self.fsd.evaluate_opportunity(
                symbol=symbol,
                bars=bars,
                last_prices=self.last_prices
            )
            
            # If FSD says trade, we execute
            if decision['should_trade'] and decision['action']['trade']:
                action = decision['action']
                size_fraction = action.get('size_fraction', 0.0)
                
                # Calculate position size
                equity = self.broker.get_value()
                cash = self.broker.get_cash()
                available = min(equity * size_fraction, cash * 0.95)
                
                current_price = data.close[0]
                shares = int(available / current_price) if current_price > 0 else 0
                
                if shares > 0:
                    # Get current position
                    position = self.getposition(data)
                    current_shares = position.size
                    
                    # Calculate delta
                    target_shares = shares
                    delta = target_shares - current_shares
                    
                    if abs(delta) >= 1:
                        if delta > 0:
                            # Buy
                            order = self.buy(data=data, size=abs(delta))
                            if self.p.verbose:
                                print(f"BUY {symbol} @ ${current_price:.2f} | {abs(delta)} shares")
                        else:
                            # Sell
                            order = self.sell(data=data, size=abs(delta))
                            if self.p.verbose:
                                print(f"SELL {symbol} @ ${current_price:.2f} | {abs(delta)} shares")
                        
                        # Register trade intent with FSD
                        self.fsd.register_trade_intent(
                            symbol=symbol,
                            timestamp=data.datetime.datetime(),
                            decision=decision,
                            target_notional=float(available),
                            target_quantity=float(target_shares)
                        )
    
    def notify_order(self, order):
        """Called when order is filled - notify FSD for learning."""
        if order.status in [order.Completed]:
            # Calculate P&L
            if order.isbuy():
                signed_qty = order.executed.size
            else:
                signed_qty = -order.executed.size
            
            # Get position before/after
            data = order.data
            symbol = data._name
            position = self.getposition(data)
            pnl = order.executed.pnl or 0.0
            
            # Record the trade
            trade = Trade(
                symbol=symbol,
                timestamp=data.datetime.datetime(),
                quantity=Decimal(str(signed_qty)),
                price=Decimal(str(order.executed.price)),
                realised_pnl=Decimal(str(pnl)),
                equity=Decimal(str(self.broker.get_value())),
                order_id=self.order_id_counter,
                strategy="FSD",
            )
            self.order_id_counter += 1
            
            # Store in strategy for retrieval
            self.recorded_trades.append(trade)
            
            # FSD learns from fill
            self.fsd.handle_fill(
                symbol=symbol,
                timestamp=data.datetime.datetime(),
                fill_price=order.executed.price,
                realised_pnl=pnl,
                signed_quantity=signed_qty,
                previous_position=position.size - signed_qty,
                new_position=position.size
            )
            
            if self.p.verbose:
                print(f"FILLED: {symbol} | P&L: ${pnl:+.2f}")
    
    def _get_bars(self, data):
        """Convert Backtrader data to our Bar format for FSD."""
        from .data import Bar
        
        bars = []
        # Get last 100 bars (enough for FSD warmup)
        lookback = min(100, len(data))
        
        for i in range(-lookback, 0):
            bar = Bar(
                symbol=data._name,
                timestamp=data.datetime.datetime(i),
                open=Decimal(str(data.open[i])),
                high=Decimal(str(data.high[i])),
                low=Decimal(str(data.low[i])),
                close=Decimal(str(data.close[i])),
                volume=int(data.volume[i]),
            )
            bars.append(bar)
        
        return bars
    
    def stop(self):
        """Called at end of backtest - save FSD state."""
        if self.p.verbose:
            print("\nBacktest Complete!")
            print(f"Final Portfolio Value: ${self.broker.get_value():.2f}")
            
            # FSD stats
            q_values = len(self.fsd.rl_agent.q_values)
            total_trades = self.fsd.rl_agent.total_trades
            win_rate = (self.fsd.rl_agent.winning_trades / total_trades * 100) if total_trades > 0 else 0
            
            print(f"FSD Stats:")
            print(f"  Q-values learned: {q_values:,}")
            print(f"  Total trades: {total_trades:,}")
            print(f"  Win rate: {win_rate:.1f}%")
        
        # Save FSD state (for next session)
        # FSD will save automatically via its own mechanism


class TradeRecorder(bt.Analyzer):
    """
    Custom Backtrader analyzer to record individual trades and equity curve.
    """
    
    def __init__(self):
        super().__init__()
        self.trades = []
        self.equity_curve = []
        self.order_counter = 0
    
    def prenext(self):
        """Called before strategy has enough data."""
        self.equity_curve.append((
            self.strategy.datetime.datetime(),
            Decimal(str(self.strategy.broker.get_value()))
        ))
    
    def next(self):
        """Record equity at each bar."""
        self.equity_curve.append((
            self.strategy.datetime.datetime(),
            Decimal(str(self.strategy.broker.get_value()))
        ))


class BOTStrategy(bt.Strategy):
    """
    Backtrader strategy that wraps our rule-based BOT strategies.
    
    Uses the same strategy suite as the custom system (MA crossover, RSI, etc.)
    but runs on Backtrader's infrastructure.
    """
    
    params = (
        ('strategy_config', None),  # StrategyConfig object
        ('risk_config', None),       # RiskConfig object
        ('verbose', False),
    )
    
    def __init__(self):
        """Initialize BOT strategy suite."""
        from datetime import timedelta
        
        initial_cash = self.broker.get_cash()
        self.custom_portfolio = Portfolio(Decimal(str(initial_cash)))
        
        strategy_config = self.p.strategy_config
        if strategy_config is None:
            raise ValueError("Must provide strategy_config parameter")
        
        # Create strategy suite (MA crossover, RSI, etc.)
        self.strategy_suite = default_strategy_suite(strategy_config)
        
        # Create risk engine if config provided
        self.risk_engine = None
        risk_config = self.p.risk_config
        if risk_config:
            self.risk_engine = RiskEngine(
                risk_config,
                self.custom_portfolio,
                bar_interval=timedelta(days=1)  # Default, override if needed
            )
        
        self.history = {}
        self.last_prices = {}
        self.order_id_counter = 0
        self.recorded_trades = []  # Store trades here for retrieval
        
        if self.p.verbose:
            print(f"BOT Strategy initialized with {len(self.datas)} symbols")
    
    def next(self):
        """Called by Backtrader for each bar - execute BOT strategies."""
        # Update history and last prices
        for data in self.datas:
            symbol = data._name
            bars = self._get_bars(data)
            self.history[symbol] = bars
            self.last_prices[symbol] = Decimal(str(data.close[0]))
        
        # Evaluate each symbol with strategy suite
        for data in self.datas:
            symbol = data._name
            
            if symbol not in self.history or len(self.history[symbol]) < 20:
                continue  # Need warmup
            
            # Get strategy signal
            context = StrategyContext(symbol=symbol, history=self.history[symbol])
            target = self.strategy_suite.blended_target(context)
            
            # Calculate target position
            equity = self.broker.get_value()
            current_price = data.close[0]
            
            # Simple sizing: target_weight * equity / price
            # Convert Decimal to float for calculations
            target_notional = equity * float(target.target_weight)
            target_shares = int(target_notional / current_price) if current_price > 0 else 0
            
            # Get current position
            position = self.getposition(data)
            current_shares = position.size
            delta = target_shares - current_shares
            
            if abs(delta) >= 1:
                # Check risk if engine available
                if self.risk_engine:
                    try:
                        self.risk_engine.check_pre_trade(
                            symbol,
                            Decimal(delta),
                            Decimal(str(current_price)),
                            Decimal(equity),
                            self.last_prices
                        )
                    except Exception:
                        # Risk violation - skip trade
                        continue
                
                # Execute trade
                if delta > 0:
                    self.buy(data=data, size=abs(delta))
                    if self.p.verbose:
                        print(f"BUY {symbol}: {abs(delta)} shares @ ${current_price:.2f}")
                else:
                    self.sell(data=data, size=abs(delta))
                    if self.p.verbose:
                        print(f"SELL {symbol}: {abs(delta)} shares @ ${current_price:.2f}")
    
    def notify_order(self, order):
        """Called when order is filled."""        
        if order.status in [order.Completed]:
            # Record the trade for the analyzer
            data = order.data
            symbol = data._name
            signed_qty = order.executed.size if order.isbuy() else -order.executed.size
            pnl = order.executed.pnl or 0.0
            
            # Create trade record (even if PnL is 0 for opening positions)
            trade = Trade(
                symbol=symbol,
                timestamp=data.datetime.datetime(),
                quantity=Decimal(str(signed_qty)),
                price=Decimal(str(order.executed.price)),
                realised_pnl=Decimal(str(pnl)),
                equity=Decimal(str(self.broker.get_value())),
                order_id=self.order_id_counter,
                strategy="BOT",
            )
            self.order_id_counter += 1
            
            # Store in strategy for retrieval
            self.recorded_trades.append(trade)
            
            if self.p.verbose:
                print(f"FILLED: {symbol} | Qty: {signed_qty} | Price: ${order.executed.price:.2f} | P&L: ${pnl:+.2f}")
    
    def _get_bars(self, data):
        """Convert Backtrader data to our Bar format."""
        bars = []
        lookback = min(100, len(data))
        
        for i in range(-lookback, 0):
            bar = Bar(
                symbol=data._name,
                timestamp=data.datetime.datetime(i),
                open=Decimal(str(data.open[i])),
                high=Decimal(str(data.high[i])),
                low=Decimal(str(data.low[i])),
                close=Decimal(str(data.close[i])),
                volume=int(data.volume[i]),
            )
            bars.append(bar)
        
        return bars


class PandasData(bt.feeds.PandasData):
    """
    Custom Backtrader data feed for our CSV format.
    
    Converts our historical CSV data into Backtrader format.
    """
    
    params = (
        ('datetime', None),  # Will use index
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', None),  # Not used
    )


def run_backtest(
    config: BacktestConfig,
    mode: str = "bot",
    fsd_config: FSDConfig | None = None,
    verbose: bool = False,
    override_data: dict[str, list[Bar]] | None = None
) -> dict:
    """
    Universal backtest runner using Backtrader.
    
    Replaces the old BacktestRunner with Backtrader infrastructure while
    maintaining 100% compatibility with all modes and intelligence.
    
    Args:
        config: Backtest configuration
        mode: "bot" or "fsd"
        fsd_config: FSD configuration (required if mode="fsd")
        verbose: Show detailed trade log
        override_data: Optional pre-loaded data (for scenarios)
    
    Returns:
        Results dict with metrics, trades, and mode-specific stats
    """
    # Validate configuration
    config.validate()
    
    # Load data using our existing loader or use override
    if override_data:
        data_map = override_data
    else:
        data_map = load_csv_directory(config.data, config.engine.data_quality)
    
    if not data_map:
        raise ValueError("No data loaded - check data source configuration")
    
    # Create Backtrader engine
    cerebro = bt.Cerebro()
    
    # Set initial cash and commission
    cerebro.broker.set_cash(config.engine.initial_equity)
    cerebro.broker.setcommission(commission=config.engine.commission_per_trade)
    
    # Add data feeds (convert our format to Backtrader format)
    for symbol, bars in data_map.items():
        if not bars:
            continue
        
        # Convert to pandas DataFrame
        df_data = {
            'timestamp': [bar.timestamp for bar in bars],
            'open': [float(bar.open) for bar in bars],
            'high': [float(bar.high) for bar in bars],
            'low': [float(bar.low) for bar in bars],
            'close': [float(bar.close) for bar in bars],
            'volume': [float(bar.volume) for bar in bars],
        }
        df = pd.DataFrame(df_data)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        
        # FIXED: Add to Backtrader with proper name handling
        data_feed = PandasData(dataname=df)
        data_feed._name = symbol  # Set name attribute after creation
        cerebro.adddata(data_feed)
    
    # Add appropriate strategy
    if mode == "fsd":
        if not fsd_config:
            raise ValueError("fsd_config required when mode='fsd'")
        cerebro.addstrategy(
            FSDStrategy,
            fsd_config=fsd_config,
            verbose=verbose
        )
    elif mode == "bot":
        cerebro.addstrategy(
            BOTStrategy,
            strategy_config=config.engine.strategy,
            risk_config=config.engine.risk,
            verbose=verbose
        )
    else:
        raise ValueError(f"Unknown mode: {mode}. Use 'bot' or 'fsd'")
    
    # Add analyzers for metrics
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # Run backtest
    if verbose:
        print(f"🚀 Starting {mode.upper()} backtest with ${config.engine.initial_equity:.2f}")
        print(f"📊 Processing {len(data_map)} symbols with {sum(len(bars) for bars in data_map.values())} total bars")
    
    starting_value = cerebro.broker.get_value()
    results = cerebro.run()
    final_value = cerebro.broker.get_value()
    
    # Extract strategy and analyzers
    strategy = results[0]
    
    # Build results dict
    result = {
        'mode': mode,
        'initial_value': starting_value,
        'final_value': final_value,
        'profit': final_value - starting_value,
        'profit_pct': ((final_value - starting_value) / starting_value * 100) if starting_value > 0 else 0,
    }
    
    # Extract analyzer metrics
    sharpe = strategy.analyzers.sharpe.get_analysis()
    drawdown = strategy.analyzers.drawdown.get_analysis()
    returns = strategy.analyzers.returns.get_analysis()
    trades_analysis = strategy.analyzers.trades.get_analysis()
    
    result['metrics'] = {
        'sharpe_ratio': sharpe.get('sharperatio', 0.0) if sharpe.get('sharperatio') is not None else 0.0,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0),
        'total_return': returns.get('rtot', 0.0),
        'total_trades': trades_analysis.get('total', {}).get('total', 0),
        'won_trades': trades_analysis.get('won', {}).get('total', 0),
        'lost_trades': trades_analysis.get('lost', {}).get('total', 0),
    }
    
    # Calculate win rate
    total_trades = result['metrics']['total_trades']
    won_trades = result['metrics']['won_trades']
    result['win_rate'] = (won_trades / total_trades) if total_trades > 0 else 0.0
    
    # Mode-specific stats
    if mode == "fsd":
        result['fsd'] = {
            'q_values_learned': len(strategy.fsd.rl_agent.q_values),
            'total_trades': strategy.fsd.rl_agent.total_trades,
            'winning_trades': strategy.fsd.rl_agent.winning_trades,
            'win_rate': (strategy.fsd.rl_agent.winning_trades / strategy.fsd.rl_agent.total_trades) 
                       if strategy.fsd.rl_agent.total_trades > 0 else 0,
            'exploration_rate': strategy.fsd.rl_agent.exploration_rate,
            'total_pnl': strategy.fsd.rl_agent.total_pnl,
        }
    
    if verbose:
        print(f"\nBacktest Complete!")
        print(f"Final Value: ${final_value:.2f}")
        print(f"Profit: ${result['profit']:+.2f} ({result['profit_pct']:+.1f}%)")
        print(f"Total Trades: {total_trades}")
        print(f"Win Rate: {result['win_rate']:.1%}")
        
        if mode == "fsd":
            print(f"Q-Values Learned: {result['fsd']['q_values_learned']:,}")
    
    return result


# =============================================================================
# Compatibility Layer & dataclass definitions
# =============================================================================

from dataclasses import dataclass


@dataclass
class Trade:
    """Trade record (compatible with old engine.Trade)."""
    symbol: str
    timestamp: datetime
    quantity: Decimal
    price: Decimal
    realised_pnl: Decimal
    equity: Decimal
    order_id: int
    strategy: str


@dataclass
class BacktestResult:
    """
    Backtest result (compatible with old engine.BacktestResult).
    
    This allows seamless migration from custom engine to Backtrader.
    """
    trades: list[Trade]
    equity_curve: list[tuple[datetime, Decimal]]
    metrics: dict[str, float]
    max_drawdown: Decimal
    total_return: Decimal
    win_rate: float


# Export all public APIs
__all__ = [
    'FSDStrategy',
    'BOTStrategy',
    'PandasData',
    'TradeRecorder',
    'run_backtest',
    'BacktestResult',
    'Trade',
]
