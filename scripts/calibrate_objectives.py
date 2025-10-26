#!/usr/bin/env python3
"""
Run a backtest and derive adaptive thresholds from its performance.
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta, timezone

from aistock.calibration import calibrate_objectives
from aistock.config import BacktestConfig, DataSource, EngineConfig, StrategyConfig
from aistock.engine import BacktestRunner

FREQUENCIES = {
    "minute": timedelta(minutes=1),
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate ObjectiveThresholds from historical data.")
    parser.add_argument("--data", required=True, help="Directory containing OHLCV CSV files.")
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbols to include in the calibration run.")
    parser.add_argument(
        "--frequency",
        choices=sorted(FREQUENCIES),
        default="daily",
        help="Bar interval of the dataset.",
    )
    parser.add_argument(
        "--short-window",
        type=int,
        default=8,
        help="Short moving-average window used during calibration.",
    )
    parser.add_argument(
        "--long-window",
        type=int,
        default=21,
        help="Long moving-average window used during calibration.",
    )
    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=120,
        help="Warmup history size passed to the data loader.",
    )
    parser.add_argument(
        "--initial-equity",
        type=float,
        default=100_000.0,
        help="Starting equity for the calibration backtest.",
    )
    parser.add_argument(
        "--safety-margin",
        type=float,
        default=0.15,
        help="Fractional margin applied when deriving thresholds.",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write the calibration summary as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    interval = FREQUENCIES[args.frequency]

    backtest_config = BacktestConfig(
        data=DataSource(
            path=args.data,
            symbols=[symbol.upper() for symbol in args.symbols],
            warmup_bars=args.warmup_bars,
            enforce_trading_hours=False,
            bar_interval=interval,
            timezone=timezone.utc,
        ),
        engine=EngineConfig(
            initial_equity=args.initial_equity,
            strategy=StrategyConfig(short_window=args.short_window, long_window=args.long_window),
        ),
    )

    result = BacktestRunner(backtest_config).run()
    summary = calibrate_objectives([result], safety_margin=args.safety_margin)
    payload = summary.to_dict()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(f"Calibration written to {args.output}")
    else:
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
