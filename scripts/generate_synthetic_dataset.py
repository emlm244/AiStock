#!/usr/bin/env python3
"""
Generate a deterministic multi-asset dataset for backtests and agent validation.

The script builds OHLCV CSV files in the format expected by `aistock.data.load_csv_directory`.
Each symbol follows a seeded geometric random walk with occasional volatility regimes so
the adaptive agent can experience different behaviours during simulation.

Usage:
    python3 scripts/generate_synthetic_dataset.py --out data/simulated/us_equities \
        --symbols AAPL MSFT NVDA AMZN META \
        --start 2020-01-02 --end 2023-12-29 --frequency daily
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

FREQUENCIES = {
    "daily": timedelta(days=1),
    "hourly": timedelta(hours=1),
    "minute": timedelta(minutes=1),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic OHLCV test data.")
    parser.add_argument("--out", required=True, help="Output directory for generated CSV files")
    parser.add_argument("--symbols", nargs="+", required=True, help="Ticker symbols to generate")
    parser.add_argument(
        "--start",
        required=True,
        help="Start date (YYYY-MM-DD) inclusive",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End date (YYYY-MM-DD) inclusive",
    )
    parser.add_argument(
        "--frequency",
        choices=sorted(FREQUENCIES),
        default="daily",
        help="Bar frequency to generate",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=17,
        help="Random seed for deterministic generation",
    )
    parser.add_argument(
        "--base-price",
        type=float,
        default=100.0,
        help="Starting price for the first symbol; subsequent symbols are offset.",
    )
    return parser.parse_args()


def _daterange(start: datetime, end: datetime, step: timedelta) -> Iterable[datetime]:
    current = start
    while current <= end:
        yield current
        current += step


def _generate_series(
    symbol: str,
    start: datetime,
    end: datetime,
    step: timedelta,
    base_price: float,
    seed: int,
) -> list[dict[str, float | str]]:
    rng = random.Random(seed)
    # Offset starting price per symbol to avoid identical paths.
    price = base_price * (1 + 0.05 * (abs(hash(symbol)) % 11))

    series: list[dict[str, float | str]] = []
    drift = 0.0005
    volatility = 0.01

    for timestamp in _daterange(start, end, step):
        # Introduce regime shifts every quarter to create richer behaviour.
        if timestamp.month in {3, 9} and timestamp.day == 1:
            drift *= rng.uniform(0.5, 1.5)
            volatility *= rng.uniform(0.6, 1.6)

        shock = rng.gauss(drift, volatility)
        price = max(1.0, price * math.exp(shock))
        high = price * (1 + rng.uniform(0.0005, 0.002))
        low = price * (1 - rng.uniform(0.0005, 0.002))
        open_price = (high + low) / 2
        close = price
        volume = max(1000.0, rng.gauss(50_000, 10_000))

        series.append(
            {
                "timestamp": timestamp.isoformat(),
                "open": f"{open_price:.4f}",
                "high": f"{high:.4f}",
                "low": f"{low:.4f}",
                "close": f"{close:.4f}",
                "volume": f"{volume:.0f}",
            }
        )

    return series


def _write_csv(path: Path, rows: Iterable[dict[str, float | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = _parse_args()
    output_dir = Path(args.out).expanduser().resolve()

    try:
        step = FREQUENCIES[args.frequency]
    except KeyError:
        raise SystemExit(f"Unsupported frequency {args.frequency!r}")

    start_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    if end_dt < start_dt:
        raise SystemExit("End date must be on or after start date.")

    for idx, symbol in enumerate(args.symbols):
        rows = _generate_series(
            symbol=symbol.upper(),
            start=start_dt,
            end=end_dt,
            step=step,
            base_price=args.base_price,
            seed=args.seed + idx,
        )
        out_path = output_dir / f"{symbol.upper()}.csv"
        _write_csv(out_path, rows)

    print(f"Generated {len(args.symbols)} symbols in {output_dir}")


if __name__ == "__main__":
    main()
