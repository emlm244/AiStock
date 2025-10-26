"""
Automatic universe selection utilities.

The selector inspects locally available historical data, computes a blended
ranking for each symbol (momentum, volatility, and volume), and returns the
highest scoring candidates. This keeps the trading pipeline flexible while
remaining deterministic and dependency-free.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, replace
from statistics import mean, pstdev
from typing import Iterable

from .config import DataQualityConfig, DataSource, UniverseConfig
from .data import Bar, load_csv_directory

_EPSILON = 1e-8


@dataclass(frozen=True)
class UniverseSelectionResult:
    symbols: list[str]
    scores: dict[str, dict[str, float]]


class UniverseSelector:
    """
    Score all available symbols and pick the best candidates.

    Symbols listed in ``UniverseConfig.include`` are pinned to the resulting
    universe (assuming data is present) and counted towards ``max_symbols``.
    Symbols in ``exclude`` are always ignored.
    """

    def __init__(
        self,
        data_source: DataSource,
        data_quality: DataQualityConfig | None = None,
    ) -> None:
        self._source = data_source
        self._quality = data_quality or DataQualityConfig()

    # ------------------------------------------------------------------
    def select(self, config: UniverseConfig) -> UniverseSelectionResult:
        config.validate()

        materialised_source = replace(self._source, symbols=None)
        bars_by_symbol = load_csv_directory(materialised_source, self._quality)

        include = [symbol.upper() for symbol in config.include]
        exclude = {symbol.upper() for symbol in config.exclude}

        metrics: dict[str, dict[str, float]] = {}
        candidates: list[tuple[str, float]] = []

        for symbol, bars in bars_by_symbol.items():
            symbol = symbol.upper()
            if symbol in exclude:
                continue

            computed = self._compute_metrics(bars, config.lookback_bars)
            if computed is None:
                continue

            if not self._passes_filters(computed, config) and symbol not in include:
                continue

            score = self._score_symbol(computed, config)
            enriched = dict(computed)
            enriched["score"] = score
            metrics[symbol] = enriched
            candidates.append((symbol, score))

        ordered = OrderedDict[str, dict[str, float]]()

        for symbol in include:
            if symbol in exclude or symbol not in metrics:
                continue
            ordered[symbol] = metrics[symbol]

        candidates.sort(key=lambda item: item[1], reverse=True)

        for symbol, _ in candidates:
            if len(ordered) >= config.max_symbols:
                break
            if symbol in ordered:
                continue
            ordered[symbol] = metrics[symbol]

        return UniverseSelectionResult(symbols=list(ordered), scores=dict(ordered))

    # ------------------------------------------------------------------
    @staticmethod
    def _compute_metrics(bars: Iterable[Bar], lookback: int) -> dict[str, float] | None:
        history: list[Bar] = list(bars)[-lookback:]
        if len(history) < 2:
            return None

        closes = [float(bar.close) for bar in history]
        volumes = [float(bar.volume) for bar in history]
        returns = [
            (closes[idx] / closes[idx - 1]) - 1.0 for idx in range(1, len(closes))
        ]

        momentum = (closes[-1] / closes[0]) - 1.0
        volatility = pstdev(returns) if len(returns) > 1 else 0.0
        avg_volume = mean(volumes)
        last_price = closes[-1]

        return {
            "momentum": momentum,
            "volatility": volatility,
            "avg_volume": avg_volume,
            "last_price": last_price,
        }

    @staticmethod
    def _passes_filters(metrics: dict[str, float], config: UniverseConfig) -> bool:
        if metrics["avg_volume"] < config.min_avg_volume:
            return False
        price = metrics["last_price"]
        if config.min_price is not None and price < config.min_price:
            return False
        if config.max_price is not None and price > config.max_price:
            return False
        return True

    @staticmethod
    def _score_symbol(metrics: dict[str, float], config: UniverseConfig) -> float:
        momentum_component = config.momentum_weight * metrics["momentum"]
        volatility_component = config.volatility_weight * metrics["volatility"]
        volume_component = config.volume_weight * math.log10(metrics["avg_volume"] + 1.0)
        return momentum_component - volatility_component + volume_component + _EPSILON
