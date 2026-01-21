"""Tests for historical universe reconstruction."""

from __future__ import annotations

import logging
from datetime import date

from aistock.backtest.universe import HistoricalUniverseManager, TickerLifecycle


def test_reconstruct_excludes_unknown_symbols_by_default(caplog) -> None:
    manager = HistoricalUniverseManager()
    manager.add_manual_lifecycle(TickerLifecycle(symbol='AAPL', ipo_date=date(2020, 1, 1)))

    with caplog.at_level(logging.WARNING):
        universe = manager.reconstruct_universe_at_time(
            date(2024, 1, 2),
            candidate_symbols=['AAPL', 'UNKNOWN'],
        )

    assert 'AAPL' in universe
    assert 'UNKNOWN' not in universe
    assert any('UNKNOWN' in record.message for record in caplog.records)


def test_reconstruct_includes_unknown_symbols_when_enabled() -> None:
    manager = HistoricalUniverseManager(include_unknown_symbols=True)
    manager.add_manual_lifecycle(TickerLifecycle(symbol='AAPL', ipo_date=date(2020, 1, 1)))

    universe = manager.reconstruct_universe_at_time(
        date(2024, 1, 2),
        candidate_symbols=['AAPL', 'UNKNOWN'],
    )

    assert 'AAPL' in universe
    assert 'UNKNOWN' in universe
