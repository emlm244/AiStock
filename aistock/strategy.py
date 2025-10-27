"""
Strategy context and suite for BOT mode.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List


@dataclass
class StrategyContext:
    """Context passed to strategies for evaluation."""
    symbol: str
    history: List  # List of Bar objects


@dataclass
class TargetPosition:
    """Target position from strategy."""
    target_weight: Decimal  # Target portfolio weight (-1 to +1)
    confidence: float  # Signal confidence (0 to 1)


class StrategySuite:
    """Collection of strategies with blended output."""
    
    def __init__(self, strategies: List):
        self.strategies = strategies
    
    def blended_target(self, context: StrategyContext) -> TargetPosition:
        """
        Get blended target position from all strategies.
        
        Args:
            context: Strategy evaluation context
        
        Returns:
            Blended target position
        """
        # Simple equal weighting for now
        # In full implementation, use dynamic weighting based on performance
        
        if not self.strategies:
            return TargetPosition(target_weight=Decimal('0'), confidence=0.0)
        
        signals = []
        for strategy in self.strategies:
            try:
                signal = strategy.evaluate(context)
                signals.append(signal)
            except Exception:
                continue
        
        if not signals:
            return TargetPosition(target_weight=Decimal('0'), confidence=0.0)
        
        # Average the signals
        avg_weight = sum(s.target_weight for s in signals) / len(signals)
        avg_confidence = sum(s.confidence for s in signals) / len(signals)
        
        return TargetPosition(target_weight=avg_weight, confidence=avg_confidence)


def default_strategy_suite(config) -> StrategySuite:
    """
    Create default strategy suite based on configuration.
    
    Args:
        config: StrategyConfig
    
    Returns:
        StrategySuite with configured strategies
    """
    # Placeholder - in full implementation, load actual strategy classes
    # from the main codebase (trend_following, mean_reversion, etc.)
    strategies = []
    
    # For now, return empty suite
    # Real implementation would import and instantiate:
    # - TrendFollowingStrategy
    # - MeanReversionStrategy
    # - MomentumStrategy
    # - MLStrategy (if enabled and model exists)
    
    return StrategySuite(strategies)
