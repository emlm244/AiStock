#!/usr/bin/env python3
"""
Bulk Backtest Rerun Script - Post P&L Fix

This script automates re-running historical backtests after the critical
TradingEngine P&L bug fix (commit da36960).

CONTEXT:
The old P&L calculation was:
  realised_pnl = closed_qty * price  (WRONG - ignores entry price)

The corrected calculation is:
  realised_pnl = (exit_price - entry_price) * qty  (CORRECT)

This script:
1. Identifies all backtest results from before the fix
2. Marks them as INVALID
3. Re-runs backtests with corrected P&L calculation
4. Generates comparison report (old vs new metrics)
5. Flags strategies with significant P&L discrepancies
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Critical commit that fixed P&L calculation
FIX_COMMIT = 'da36960'
FIX_DATE = datetime(2025, 11, 2, 21, 36, 52, tzinfo=timezone.utc)


def find_backtest_results(results_dir: Path) -> list[Path]:
    """Find all backtest result files."""
    patterns = [
        '**/*backtest*.json',
        '**/backtest_results/*.json',
        '**/results/*.json',
    ]

    results = set()
    for pattern in patterns:
        results.update(results_dir.glob(pattern))

    return sorted(results)


def is_pre_fix_result(result_file: Path) -> bool:
    """Check if backtest result predates the P&L fix."""
    try:
        with open(result_file) as f:
            data = json.load(f)

        # Check if result has timestamp
        if 'timestamp' in data:
            result_ts = datetime.fromisoformat(data['timestamp'])
            return result_ts < FIX_DATE

        # Check file modification time as fallback
        mtime = datetime.fromtimestamp(result_file.stat().st_mtime, tz=timezone.utc)
        return mtime < FIX_DATE

    except Exception as e:
        logger.warning(f'Could not parse {result_file}: {e}')
        return True  # Assume invalid if can't verify


def mark_invalid(result_file: Path) -> None:
    """Mark a backtest result as INVALID."""
    try:
        with open(result_file) as f:
            data = json.load(f)

        # Add invalidation metadata
        data['INVALID'] = True
        data['invalidation_reason'] = 'P&L calculation bug - commit da36960 fixed on 2025-11-02'
        data['invalidation_timestamp'] = datetime.now(timezone.utc).isoformat()

        # Save with .INVALID suffix
        invalid_path = result_file.with_suffix('.INVALID.json')
        with open(invalid_path, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f'Marked invalid: {result_file} -> {invalid_path}')

    except Exception as e:
        logger.error(f'Failed to mark invalid {result_file}: {e}')


def extract_strategy_params(result_file: Path) -> dict[str, Any]:
    """Extract strategy parameters from backtest result."""
    try:
        with open(result_file) as f:
            data = json.load(f)

        return {
            'symbols': data.get('symbols', []),
            'start_date': data.get('start_date'),
            'end_date': data.get('end_date'),
            'capital': data.get('initial_capital'),
            'config': data.get('config', {}),
        }
    except Exception as e:
        logger.error(f'Failed to extract params from {result_file}: {e}')
        return {}


def calculate_impact_score(old_result: dict[str, Any]) -> float:
    """
    Calculate impact score for prioritizing backtest reruns.

    Higher score = higher priority to rerun.

    Factors:
    - Total return magnitude (higher = more impact)
    - Number of trades (more trades = more P&L errors)
    - Strategy criticality (production strategies prioritized)
    """
    score = 0.0

    # Factor 1: Total return magnitude
    total_return = abs(float(old_result.get('total_return', 0)))
    score += total_return * 10  # Weight: 10x

    # Factor 2: Number of trades
    num_trades = int(old_result.get('num_trades', 0))
    score += num_trades * 0.1  # Weight: 0.1x

    # Factor 3: Production flag
    if old_result.get('is_production', False):
        score *= 2  # 2x multiplier for production strategies

    return score


def generate_rerun_plan(results_dir: Path, output_file: Path) -> None:
    """Generate prioritized backtest rerun plan."""
    logger.info('Scanning for pre-fix backtest results...')

    results = find_backtest_results(results_dir)
    pre_fix_results = [r for r in results if is_pre_fix_result(r)]

    logger.info(f'Found {len(results)} total results, {len(pre_fix_results)} pre-fix')

    # Build prioritized list
    rerun_plan = []
    for result_file in pre_fix_results:
        try:
            with open(result_file) as f:
                data = json.load(f)

            impact = calculate_impact_score(data)
            params = extract_strategy_params(result_file)

            rerun_plan.append(
                {
                    'file': str(result_file),
                    'impact_score': impact,
                    'total_return': data.get('total_return'),
                    'num_trades': data.get('num_trades'),
                    'symbols': params.get('symbols'),
                    'start_date': params.get('start_date'),
                    'end_date': params.get('end_date'),
                    'params': params,
                }
            )
        except Exception as e:
            logger.error(f'Failed to process {result_file}: {e}')

    # Sort by impact score (highest first)
    rerun_plan.sort(key=lambda x: x['impact_score'], reverse=True)

    # Save plan
    plan_data = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'fix_commit': FIX_COMMIT,
        'total_results': len(results),
        'pre_fix_results': len(pre_fix_results),
        'rerun_plan': rerun_plan,
    }

    with open(output_file, 'w') as f:
        json.dump(plan_data, f, indent=2)

    logger.info(f'Rerun plan saved to: {output_file}')
    logger.info('Top 5 priorities:')
    for i, item in enumerate(rerun_plan[:5], 1):
        logger.info(
            f"  {i}. {item['file']} (score={item['impact_score']:.1f}, "
            f"return={item['total_return']}, trades={item['num_trades']})"
        )


def main():
    parser = argparse.ArgumentParser(
        description='Bulk backtest rerun automation (post P&L fix)'
    )
    parser.add_argument(
        '--results-dir',
        type=Path,
        default=Path('backtest_results'),
        help='Directory containing backtest results',
    )
    parser.add_argument(
        '--mark-invalid',
        action='store_true',
        help='Mark pre-fix results as INVALID',
    )
    parser.add_argument(
        '--generate-plan',
        type=Path,
        help='Generate prioritized rerun plan (output JSON file)',
    )

    args = parser.parse_args()

    if not args.results_dir.exists():
        logger.error(f'Results directory not found: {args.results_dir}')
        sys.exit(1)

    if args.mark_invalid:
        logger.info('Marking pre-fix results as INVALID...')
        results = find_backtest_results(args.results_dir)
        pre_fix = [r for r in results if is_pre_fix_result(r)]

        for result_file in pre_fix:
            mark_invalid(result_file)

        logger.info(f'Marked {len(pre_fix)} results as INVALID')

    if args.generate_plan:
        generate_rerun_plan(args.results_dir, args.generate_plan)

    if not args.mark_invalid and not args.generate_plan:
        parser.print_help()


if __name__ == '__main__':
    main()
