"""CLI entrypoint for running Massive-backed backtests."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date

from ..providers.massive import MassiveConfig
from .config import BacktestPlanConfig, WalkForwardConfig
from .orchestrator import BacktestOrchestrator


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f'Invalid date: {value} (expected YYYY-MM-DD)') from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run a Massive.com-backed backtest.')
    parser.add_argument('--symbols', nargs='+', required=True, help='Symbols to backtest (space-separated).')
    parser.add_argument('--start-date', type=_parse_date, required=True, help='Start date (YYYY-MM-DD).')
    parser.add_argument('--end-date', type=_parse_date, required=True, help='End date (YYYY-MM-DD).')
    parser.add_argument('--timeframe', default='1m', help='Bar timeframe (default: 1m).')
    parser.add_argument('--output-dir', default='backtest_results', help='Output directory for reports.')
    parser.add_argument('--walkforward', action='store_true', help='Enable walk-forward validation.')
    parser.add_argument('--no-cache', action='store_true', help='Disable Massive cache usage.')
    parser.add_argument('--no-report', action='store_true', help='Skip report generation.')
    parser.add_argument('--massive-api-key', default=None, help='Massive.com API key (defaults to env).')
    return parser


class CLIArgs(argparse.Namespace):
    massive_api_key: str | None
    symbols: list[str]
    start_date: date
    end_date: date
    timeframe: str
    output_dir: str
    walkforward: bool
    no_cache: bool
    no_report: bool


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    parser = _build_parser()
    args = parser.parse_args(namespace=CLIArgs())

    api_key = args.massive_api_key or os.environ.get('MASSIVE_API_KEY')
    if not api_key:
        raise SystemExit('Missing Massive API key. Provide --massive-api-key or set MASSIVE_API_KEY.')

    symbols = [symbol.strip().upper() for symbol in args.symbols if symbol.strip()]
    if not symbols:
        raise SystemExit('At least one symbol is required.')

    walkforward_config = WalkForwardConfig() if args.walkforward else None

    plan = BacktestPlanConfig(
        symbols=symbols,
        start_date=args.start_date,
        end_date=args.end_date,
        timeframe=args.timeframe,
        walkforward=walkforward_config,
        output_dir=args.output_dir,
        use_cache=not args.no_cache,
        generate_report=not args.no_report,
    )
    plan.validate()

    massive_config = MassiveConfig(api_key=api_key)
    massive_config.validate()
    orchestrator = BacktestOrchestrator(plan, massive_config)
    result = orchestrator.run_backtest()

    if result.walkforward_result:
        wf = result.walkforward_result
        logging.info(
            'Backtest finished: success=%s folds=%s oos_sharpe=%.2f',
            result.success,
            wf.completed_folds,
            wf.out_of_sample_sharpe,
        )
    elif result.period_results:
        period = result.period_results[0]
        logging.info(
            'Backtest finished: success=%s trades=%s return=%.4f%%',
            result.success,
            period.total_trades,
            period.total_return_pct * 100,
        )
    else:
        logging.info('Backtest finished: success=%s (no period results)', result.success)
    return 0 if result.success else 1


if __name__ == '__main__':
    raise SystemExit(main())
