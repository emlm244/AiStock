"""
Portfolio tracking for backtesting.
"""

from decimal import Decimal
from typing import Dict, Optional


class Portfolio:
    """
    Simple portfolio tracker for backtest engines.
    
    Tracks:
    - Cash balance
    - Position quantities
    - Average entry prices
    - Realized P&L
    """
    
    def __init__(self, initial_cash: Decimal):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: Dict[str, Decimal] = {}  # symbol -> quantity
        self.avg_prices: Dict[str, Decimal] = {}  # symbol -> avg entry price
        self.realised_pnl = Decimal('0')
        
    def get_cash(self) -> Decimal:
        """Get current cash balance."""
        return self.cash
    
    def get_position(self, symbol: str) -> Decimal:
        """Get current position quantity for symbol."""
        return self.positions.get(symbol, Decimal('0'))
    
    def get_avg_price(self, symbol: str) -> Optional[Decimal]:
        """Get average entry price for symbol."""
        return self.avg_prices.get(symbol)
    
    def update_position(
        self,
        symbol: str,
        quantity_delta: Decimal,
        price: Decimal,
        commission: Decimal = Decimal('0')
    ):
        """
        Update position and cash after a trade.
        
        Args:
            symbol: Trading symbol
            quantity_delta: Change in position (positive for buy, negative for sell)
            price: Execution price
            commission: Transaction cost
        """
        current_qty = self.get_position(symbol)
        new_qty = current_qty + quantity_delta
        
        # Update cash (reduce for buys, increase for sells, always reduce commission)
        cash_delta = -(quantity_delta * price) - commission
        self.cash += cash_delta
        
        # Update position
        if new_qty == 0:
            # Position closed
            if symbol in self.positions:
                del self.positions[symbol]
            if symbol in self.avg_prices:
                del self.avg_prices[symbol]
        else:
            self.positions[symbol] = new_qty
            
            # Update average price (only when increasing position)
            if (current_qty >= 0 and quantity_delta > 0) or (current_qty <= 0 and quantity_delta < 0):
                # Adding to position - update average price
                if current_qty == 0:
                    self.avg_prices[symbol] = price
                else:
                    total_cost = (current_qty * self.avg_prices.get(symbol, price)) + (quantity_delta * price)
                    self.avg_prices[symbol] = total_cost / new_qty
    
    def record_pnl(self, pnl: Decimal):
        """Record realized P&L."""
        self.realised_pnl += pnl
    
    def get_equity(self, current_prices: Dict[str, Decimal]) -> Decimal:
        """
        Calculate total equity (cash + position values).
        
        Args:
            current_prices: Dict of symbol -> current price
        
        Returns:
            Total equity value
        """
        position_value = Decimal('0')
        
        for symbol, qty in self.positions.items():
            if symbol in current_prices:
                position_value += qty * current_prices[symbol]
        
        return self.cash + position_value
