"""
Strategy primitives.

The goal is not to be fancy but to provide a transparent baseline that can be
audited and extended.  Strategies operate on plain lists of :class:`Bar`
objects, making it clear how much history they consume and preventing hidden
state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .config import StrategyConfig
from .data import Bar


def moving_average(prices: Sequence[Decimal]) -> Decimal:
    if not prices:
        raise ValueError("moving_average requires at least one price")
    return sum(prices) / Decimal(len(prices))


@dataclass
class StrategyContext:
    symbol: str
    history: list[Bar]


@dataclass
class TargetPosition:
    symbol: str
    target_weight: Decimal  # -1.0 to 1.0
    confidence: float


class BaseStrategy:
    name: str

    def min_history(self) -> int:
        raise NotImplementedError

    def generate(self, context: StrategyContext) -> TargetPosition:
        raise NotImplementedError


@dataclass
class MovingAverageCrossover(BaseStrategy):
    short_window: int
    long_window: int
    name: str = "MA_Crossover"

    def min_history(self) -> int:
        return max(self.short_window, self.long_window)

    def generate(self, context: StrategyContext) -> TargetPosition:
        if len(context.history) < self.min_history():
            return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)
        closes = [bar.close for bar in context.history]
        short_ma = moving_average(closes[-self.short_window :])
        long_ma = moving_average(closes[-self.long_window :])
        if short_ma > long_ma:
            return TargetPosition(context.symbol, Decimal("1"), confidence=0.6)
        if short_ma < long_ma:
            return TargetPosition(context.symbol, Decimal("-1"), confidence=0.6)
        return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)


@dataclass
class RSIStrategy(BaseStrategy):
    period: int = 14
    overbought: Decimal = Decimal("70")
    oversold: Decimal = Decimal("30")
    name: str = "RSI_Reversion"

    def min_history(self) -> int:
        return self.period + 1

    def generate(self, context: StrategyContext) -> TargetPosition:
        if len(context.history) < self.min_history():
            return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)
        gains = []
        losses = []
        closes = [bar.close for bar in context.history]
        for prev, curr in zip(closes[-self.period - 1 : -1], closes[-self.period :]):
            delta = curr - prev
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        avg_gain = sum(gains) / Decimal(len(gains) or 1)
        avg_loss = sum(losses) / Decimal(len(losses) or 1)
        if avg_loss == 0:
            rsi = Decimal("100")
        else:
            rs = avg_gain / avg_loss
            rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
        if rsi > self.overbought:
            return TargetPosition(context.symbol, Decimal("-1"), confidence=0.5)
        if rsi < self.oversold:
            return TargetPosition(context.symbol, Decimal("1"), confidence=0.5)
        return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)


@dataclass
class StrategySuite:
    strategies: Sequence[BaseStrategy]

    def min_history(self) -> int:
        return max(strategy.min_history() for strategy in self.strategies)

    def generate_targets(self, context: StrategyContext) -> list[TargetPosition]:
        return [strategy.generate(context) for strategy in self.strategies]

    def blended_target(self, context: StrategyContext) -> TargetPosition:
        targets = self.generate_targets(context)
        if not targets:
            return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)
        weight_sum = Decimal("0")
        confidence_sum = 0.0
        for target in targets:
            weight_sum += target.target_weight * Decimal(str(target.confidence))
            confidence_sum += target.confidence
        if confidence_sum == 0:
            return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)
        blended_weight = weight_sum / Decimal(str(confidence_sum))
        blended_confidence = min(1.0, confidence_sum / len(targets))
        return TargetPosition(context.symbol, blended_weight, blended_confidence)


def default_strategy_suite(config: StrategyConfig) -> StrategySuite:
    strategies: list[BaseStrategy] = [
        MovingAverageCrossover(short_window=config.short_window, long_window=config.long_window),
        RSIStrategy(),
    ]
    if config.ml_enabled:
        try:
            from .ml.strategy import MachineLearningStrategy

            strategies.append(MachineLearningStrategy(config))
        except Exception:
            # Model might be missing; degrade gracefully.
            pass
    return StrategySuite(strategies=strategies)
