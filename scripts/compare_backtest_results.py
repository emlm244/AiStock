#!/usr/bin/env python3
"""
Compare Old (INVALID) vs New (Corrected) Backtest Results

This script compares backtest results before and after the P&L fix
to identify discrepancies and validate the correction.

USAGE:
    python compare_backtest_results.py old.INVALID.json new.json

OUTPUT:
    - Side-by-side metric comparison
    - Percentage differences
    - Alerts for significant discrepancies
    - Trade-by-trade P&L comparison (optional)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_result(file_path: Path) -> dict[str, Any]:
    """Load backtest result from JSON file."""
    try:
        with open(file_path) as f:
            return json.load(f)
    except Exception as e:
        print(f'Error loading {file_path}: {e}')
        sys.exit(1)


def calculate_percentage_diff(old: float, new: float) -> float:
    """Calculate percentage difference between old and new values."""
    if old == 0:
        return float('inf') if new != 0 else 0.0
    return ((new - old) / abs(old)) * 100


def compare_metrics(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compare key metrics between old and new results."""
    metrics = {
        'total_return': {
            'old': old.get('total_return', 0),
            'new': new.get('total_return', 0),
        },
        'max_drawdown': {
            'old': old.get('max_drawdown', 0),
            'new': new.get('max_drawdown', 0),
        },
        'win_rate': {
            'old': old.get('win_rate', 0),
            'new': new.get('win_rate', 0),
        },
        'num_trades': {
            'old': old.get('num_trades', 0),
            'new': new.get('num_trades', 0),
        },
    }

    # Calculate differences
    for _metric, values in metrics.items():
        values['diff'] = values['new'] - values['old']
        values['pct_change'] = calculate_percentage_diff(values['old'], values['new'])

    return metrics


def generate_alerts(metrics: dict[str, Any]) -> list[str]:
    """Generate alerts for significant discrepancies."""
    alerts = []

    # Alert thresholds
    RETURN_THRESHOLD = 50  # 50% change in total return
    DRAWDOWN_THRESHOLD = 20  # 20% change in max drawdown
    WIN_RATE_THRESHOLD = 10  # 10 percentage point change
    TRADE_COUNT_THRESHOLD = 5  # 5% change in trade count

    # Check total return
    return_pct = abs(metrics['total_return']['pct_change'])
    if return_pct > RETURN_THRESHOLD:
        alerts.append(
            f'[CRITICAL] Total return changed by {return_pct:.1f}% '
            f'({metrics["total_return"]["old"]:.2%} -> {metrics["total_return"]["new"]:.2%})'
        )

    # Check max drawdown
    dd_pct = abs(metrics['max_drawdown']['pct_change'])
    if dd_pct > DRAWDOWN_THRESHOLD:
        alerts.append(
            f'[WARNING] Max drawdown changed by {dd_pct:.1f}% '
            f'({metrics["max_drawdown"]["old"]:.2%} -> {metrics["max_drawdown"]["new"]:.2%})'
        )

    # Check win rate
    wr_diff = abs(metrics['win_rate']['diff'])
    if wr_diff > WIN_RATE_THRESHOLD / 100:
        alerts.append(
            f'[WARNING] Win rate changed by {wr_diff*100:.1f} percentage points '
            f'({metrics["win_rate"]["old"]:.1%} -> {metrics["win_rate"]["new"]:.1%})'
        )

    # Check trade count
    tc_pct = abs(metrics['num_trades']['pct_change'])
    if tc_pct > TRADE_COUNT_THRESHOLD:
        alerts.append(
            f'[INFO] Trade count changed by {tc_pct:.1f}% '
            f'({metrics["num_trades"]["old"]} -> {metrics["num_trades"]["new"]})'
        )

    return alerts


def print_comparison_table(metrics: dict[str, Any]) -> None:
    """Print formatted comparison table."""
    print('\n' + '=' * 80)
    print('BACKTEST COMPARISON REPORT')
    print('=' * 80)
    print(f'\n{"Metric":<20} {"Old (INVALID)":<20} {"New (Corrected)":<20} {"Change":<20}')
    print('-' * 80)

    for metric, values in metrics.items():
        metric_name = metric.replace('_', ' ').title()

        # Format values based on metric type
        if metric in ['total_return', 'max_drawdown', 'win_rate']:
            old_str = f'{values["old"]*100:.2f}%'
            new_str = f'{values["new"]*100:.2f}%'
            diff_str = f'{values["diff"]*100:+.2f}% ({values["pct_change"]:+.1f}%)'
        else:
            old_str = f'{values["old"]}'
            new_str = f'{values["new"]}'
            diff_str = f'{values["diff"]:+.0f} ({values["pct_change"]:+.1f}%)'

        print(f'{metric_name:<20} {old_str:<20} {new_str:<20} {diff_str:<20}')

    print('=' * 80)


def analyze_direction(metrics: dict[str, Any]) -> str:
    """Analyze overall direction of changes."""
    return_change = metrics['total_return']['pct_change']

    if abs(return_change) < 5:
        return 'Changes are relatively minor (<5% impact)'
    elif return_change < 0:
        return f'Old results OVERSTATED performance by {abs(return_change):.1f}%'
    else:
        return f'Old results UNDERSTATED performance by {return_change:.1f}%'


def main():
    parser = argparse.ArgumentParser(
        description='Compare old (INVALID) vs new (corrected) backtest results'
    )
    parser.add_argument('old_file', type=Path, help='Old backtest result (INVALID)')
    parser.add_argument('new_file', type=Path, help='New backtest result (corrected)')
    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Show detailed trade-by-trade comparison',
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Save comparison report to JSON file',
    )

    args = parser.parse_args()

    # Validate files
    if not args.old_file.exists():
        print(f'Error: Old file not found: {args.old_file}')
        sys.exit(1)
    if not args.new_file.exists():
        print(f'Error: New file not found: {args.new_file}')
        sys.exit(1)

    # Load results
    print(f'Loading old result: {args.old_file}')
    old_result = load_result(args.old_file)

    print(f'Loading new result: {args.new_file}')
    new_result = load_result(args.new_file)

    # Compare metrics
    metrics = compare_metrics(old_result, new_result)

    # Print comparison table
    print_comparison_table(metrics)

    # Print analysis
    print('\nANALYSIS:')
    print(f'  {analyze_direction(metrics)}')

    # Generate and print alerts
    alerts = generate_alerts(metrics)
    if alerts:
        print('\nALERTS:')
        for alert in alerts:
            print(f'  {alert}')
    else:
        print('\n[OK] No significant discrepancies detected')

    # Save to file if requested
    if args.output:
        report = {
            'old_file': str(args.old_file),
            'new_file': str(args.new_file),
            'metrics': metrics,
            'analysis': analyze_direction(metrics),
            'alerts': alerts,
        }
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'\nComparison report saved to: {args.output}')

    # Detailed trade comparison (if requested)
    if args.detailed and 'trades' in old_result and 'trades' in new_result:
        print('\nDETAILED TRADE COMPARISON:')
        old_trades = old_result['trades']
        new_trades = new_result['trades']

        if len(old_trades) != len(new_trades):
            print(f'  [WARNING] Trade count mismatch: {len(old_trades)} vs {len(new_trades)}')

        for i, (old_trade, new_trade) in enumerate(zip(old_trades, new_trades)):
            old_pnl = old_trade.get('realised_pnl', 0)
            new_pnl = new_trade.get('realised_pnl', 0)
            if abs(old_pnl - new_pnl) > 0.01:  # Non-zero difference
                pct_diff = calculate_percentage_diff(old_pnl, new_pnl)
                print(
                    f'  Trade {i+1}: P&L changed {old_pnl:.2f} -> {new_pnl:.2f} ({pct_diff:+.1f}%)'
                )

    return 0


if __name__ == '__main__':
    sys.exit(main())
