"""
Risk management for backtest engines.
"""

from decimal import Decimal
from typing import Dict
from datetime import timedelta


class RiskEngine:
    """
    Risk management engine for backtesting.
    
    Enforces:
    - Daily loss limits
    - Maximum drawdown halts
    - Position size limits
    - Pre-trade risk checks
    """
    
    def __init__(self, risk_config, portfolio, bar_interval: timedelta):
        self.config = risk_config
        self.portfolio = portfolio
        self.bar_interval = bar_interval
        
        self.daily_start_equity = portfolio.initial_cash
        self.peak_equity = portfolio.initial_cash
        self.is_halted = False
        self.halt_reason = ""
    
    def check_pre_trade(
        self,
        symbol: str,
        quantity_delta: Decimal,
        price: Decimal,
        current_equity: Decimal,
        last_prices: Dict[str, Decimal]
    ):
        """
        Check if a trade violates risk limits.
        
        Args:
            symbol: Trading symbol
            quantity_delta: Proposed quantity change
            price: Execution price
            current_equity: Current portfolio equity
            last_prices: Dict of current prices for all symbols
        
        Raises:
            ValueError: If trade violates risk limits
        """
        # Check if trading is halted
        if self.is_halted:
            raise ValueError(f"Trading halted: {self.halt_reason}")
        
        # Check daily loss limit
        daily_loss = (self.daily_start_equity - current_equity) / self.daily_start_equity
        if daily_loss >= self.config.max_daily_loss_pct:
            self.is_halted = True
            self.halt_reason = f"Daily loss limit exceeded: {daily_loss:.2%}"
            raise ValueError(self.halt_reason)
        
        # Check maximum drawdown
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        drawdown = (self.peak_equity - current_equity) / self.peak_equity
        if drawdown >= self.config.max_drawdown_pct:
            self.is_halted = True
            self.halt_reason = f"Maximum drawdown exceeded: {drawdown:.2%}"
            raise ValueError(self.halt_reason)
        
        # Check position size limit
        position_value = abs(quantity_delta * price)
        position_pct = position_value / current_equity if current_equity > 0 else 0
        
        if position_pct > self.config.max_position_pct:
            raise ValueError(
                f"Position size {position_pct:.2%} exceeds limit {self.config.max_position_pct:.2%}"
            )
    
    def reset_daily(self, current_equity: Decimal):
        """Reset daily tracking (call at start of each trading day)."""
        self.daily_start_equity = current_equity
