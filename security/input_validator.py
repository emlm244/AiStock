"""Input validation and sanitization for AiStock trading bot."""

import re
from typing import List, Optional

class InputValidator:
    """Validates and sanitizes user inputs to prevent injection attacks."""
    
    # Known valid stock/crypto/forex symbol patterns
    STOCK_PATTERN = re.compile(r'^[A-Z]{1,5}$')
    CRYPTO_PATTERN = re.compile(r'^[A-Z]{3,5}/[A-Z]{3}$')
    FOREX_PATTERN = re.compile(r'^[A-Z]{3}/[A-Z]{3}$')
    
    # Whitelist of allowed characters for symbols
    SYMBOL_WHITELIST = re.compile(r'^[A-Z0-9/\-\.]+$')
    
    @classmethod
    def validate_symbol(cls, symbol: str) -> tuple[bool, str]:
        """
        Validate trading symbol format.
        
        Args:
            symbol: Trading symbol to validate
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not symbol:
            return False, "Symbol cannot be empty"
        
        # Remove whitespace
        symbol = symbol.strip().upper()
        
        # Check length
        if len(symbol) > 20:
            return False, f"Symbol too long: {len(symbol)} characters (max 20)"
        
        # Check whitelist
        if not cls.SYMBOL_WHITELIST.match(symbol):
            return False, f"Symbol contains invalid characters: {symbol}"
        
        # Check specific patterns
        if cls.STOCK_PATTERN.match(symbol):
            return True, "Valid stock symbol"
        elif cls.CRYPTO_PATTERN.match(symbol):
            return True, "Valid crypto symbol"
        elif cls.FOREX_PATTERN.match(symbol):
            return True, "Valid forex symbol"
        else:
            return False, f"Symbol format not recognized: {symbol}"
    
    @classmethod
    def validate_symbols(cls, symbols: List[str]) -> tuple[List[str], List[str]]:
        """
        Validate list of symbols.
        
        Args:
            symbols: List of symbols to validate
        
        Returns:
            Tuple of (valid_symbols, invalid_symbols_with_reasons)
        """
        valid = []
        invalid = []
        
        for symbol in symbols:
            is_valid, message = cls.validate_symbol(symbol)
            if is_valid:
                valid.append(symbol.strip().upper())
            else:
                invalid.append(f"{symbol}: {message}")
        
        return valid, invalid
    
    @classmethod
    def sanitize_symbol(cls, symbol: str) -> Optional[str]:
        """
        Sanitize symbol string.
        
        Args:
            symbol: Symbol to sanitize
        
        Returns:
            Sanitized symbol or None if invalid
        """
        is_valid, _ = cls.validate_symbol(symbol)
        if is_valid:
            return symbol.strip().upper()
        return None
    
    @classmethod
    def validate_quantity(cls, quantity: float, min_val: float = 0.0, max_val: float = 1e9) -> tuple[bool, str]:
        """
        Validate trading quantity.
        
        Args:
            quantity: Quantity to validate
            min_val: Minimum allowed value
            max_val: Maximum allowed value
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            qty = float(quantity)
            
            if qty <= min_val:
                return False, f"Quantity must be > {min_val}"
            
            if qty > max_val:
                return False, f"Quantity exceeds maximum: {max_val}"
            
            return True, "Valid quantity"
            
        except (ValueError, TypeError):
            return False, f"Invalid quantity format: {quantity}"
    
    @classmethod
    def validate_price(cls, price: float) -> tuple[bool, str]:
        """
        Validate price value.
        
        Args:
            price: Price to validate
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            p = float(price)
            
            if p <= 0:
                return False, "Price must be positive"
            
            if p > 1e9:
                return False, "Price unreasonably high"
            
            return True, "Valid price"
            
        except (ValueError, TypeError):
            return False, f"Invalid price format: {price}"
