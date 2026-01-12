from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import TypedDict, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aistock.config import BacktestConfig, BrokerConfig, DataSource, EngineConfig  # noqa: E402
from aistock.data import load_csv_file  # noqa: E402
from aistock.factories import SessionFactory  # noqa: E402
from aistock.fsd import FSDConfig  # noqa: E402


class SessionSnapshot(TypedDict):
    equity: float
    cash: float
    positions: list[object]
    trades: list[object]


@dataclass(frozen=True)
class Args:
    symbol: str
    data: str
    limit: int


def run(symbol: str, data_path: str, limit: int) -> int:
    # Build config for paper session in FSD mode
    data = DataSource(path=data_path, symbols=(symbol,), enforce_trading_hours=True)
    config = BacktestConfig(data=data, engine=EngineConfig(), broker=BrokerConfig(backend='paper'))
    fsd_config = FSDConfig()

    # Create session using new modular architecture
    factory = SessionFactory(config, fsd_config=fsd_config)
    session = factory.create_trading_session(
        symbols=list(data.symbols) if data.symbols else [symbol],
        checkpoint_dir='state',
    )
    # Disable checkpointing for smoke test
    session.checkpointer.enabled = False
    session.start()

    try:
        bars = load_csv_file(Path(data_path) / f'{symbol}.csv', symbol, tz=timezone.utc)
        fed = 0
        for bar in bars[:limit] if limit > 0 else bars:
            session.process_bar(bar)
            fed += 1

        snap = cast(SessionSnapshot, session.snapshot())
        print('--- Smoke Backtest Summary ---')
        print(f'Symbol: {symbol}')
        print(f'Bars processed: {fed}')
        print(f'Equity: {snap["equity"]:.2f}')
        print(f'Cash: {snap["cash"]:.2f}')
        print(f'Positions: {len(snap["positions"])}')
        print(f'Trades: {len(snap["trades"])}')
        return 0
    finally:
        session.stop()


def _parse_args() -> Args:
    parser = argparse.ArgumentParser(description='Run a quick FSD smoke backtest using the paper broker.')
    parser.add_argument('--symbol', default='AAPL', help='Symbol to backtest')
    parser.add_argument(
        '--data', default=str(Path('data/historical/stocks').as_posix()), help='Directory containing CSV files'
    )
    parser.add_argument('--limit', type=int, default=500, help='Max bars to process (0 = all)')
    parsed = parser.parse_args()
    return Args(
        symbol=cast(str, parsed.symbol),
        data=cast(str, parsed.data),
        limit=cast(int, parsed.limit),
    )


def main() -> int:
    args = _parse_args()
    return run(args.symbol.upper(), args.data, args.limit)


if __name__ == '__main__':
    raise SystemExit(main())
