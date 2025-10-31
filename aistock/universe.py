"""
Universe selection for automated symbol selection.

NOTE: This module is largely unused in FSD mode.
Symbols are typically specified directly in DataSource or discovered via scanner.
Retained for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import DataQualityConfig, DataSource, UniverseConfig


@dataclass
class UniverseSelectionResult:
    """Result of universe selection (unused placeholder)."""

    symbols: list[str]
    scores: dict[str, float]
    method: str


class UniverseSelector:
    """Placeholder universe selector (unused in FSD mode)."""

    def __init__(self, data_source: DataSource, data_quality_config: DataQualityConfig) -> None:
        self.data_source = data_source
        self.data_quality = data_quality_config

    def select(self, universe_config: UniverseConfig | None) -> UniverseSelectionResult:
        """Returns empty result - symbols must be specified directly."""
        return UniverseSelectionResult(symbols=[], scores={}, method='manual')
