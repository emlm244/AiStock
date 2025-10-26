"""
Scenario runner for stress testing strategies.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from .data import Bar


@dataclass
class Scenario:
    name: str

    def apply(self, bars: list[Bar]) -> list[Bar]:
        raise NotImplementedError


@dataclass
class GapScenario(Scenario):
    gap_percentage: Decimal
    bars_to_skip: int = 1

    def apply(self, bars: list[Bar]) -> list[Bar]:
        if len(bars) <= self.bars_to_skip:
            return bars
        modified = []
        for idx, bar in enumerate(bars):
            if idx == self.bars_to_skip:
                factor = Decimal("1") + (self.gap_percentage / Decimal("100"))
                modified.append(
                    Bar(
                        symbol=bar.symbol,
                        timestamp=bar.timestamp,
                        open=bar.open * factor,
                        high=bar.high * factor,
                        low=bar.low * factor,
                        close=bar.close * factor,
                        volume=bar.volume,
                    )
                )
            else:
                modified.append(bar)
        return modified


@dataclass
class VolatilitySpikeScenario(Scenario):
    multiplier: Decimal

    def apply(self, bars: list[Bar]) -> list[Bar]:
        modified = []
        for bar in bars:
            mid = (bar.high + bar.low) / Decimal("2")
            range_delta = (bar.high - mid) * self.multiplier
            modified.append(
                Bar(
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=mid + range_delta,
                    low=mid - range_delta,
                    close=bar.close,
                    volume=bar.volume,
                )
            )
        return modified


@dataclass
class MissingDataScenario(Scenario):
    probability: float  # 0 to 1

    def apply(self, bars: list[Bar]) -> list[Bar]:
        filtered = []
        for idx, bar in enumerate(bars):
            threshold = (idx % 10) / 10.0
            if threshold < self.probability:
                continue
            filtered.append(bar)
        return filtered


class ScenarioRunner:
    def __init__(self, scenarios: Iterable[Scenario]) -> None:
        self._scenarios = list(scenarios)

    def run(self, bars_by_symbol: dict[str, list[Bar]]) -> dict[str, dict[str, list[Bar]]]:
        returns: dict[str, dict[str, list[Bar]]] = {}
        for scenario in self._scenarios:
            scenario_view: dict[str, list[Bar]] = {}
            for symbol, bars in bars_by_symbol.items():
                scenario_view[symbol] = scenario.apply(list(bars))
            returns[scenario.name] = scenario_view
        return returns
