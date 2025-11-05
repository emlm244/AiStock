#!/usr/bin/env python3
"""
End-to-End Backtest Rerun Workflow

This script demonstrates the complete workflow for handling
the P&L fix:

1. Generate sample backtests (old broken + new corrected)
2. Mark invalid results
3. Compare old vs new metrics
4. Generate rerun priority plan

Perfect for testing and demonstration purposes.
"""

import json
import subprocess
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and report success/failure."""
    print(f'\n{"=" * 60}')
    print(f'{description}')
    print(f'{"=" * 60}')
    print(f'Command: {" ".join(cmd)}')
    print()

    try:
        subprocess.run(cmd, check=True, capture_output=False, text=True)
        print(f'[OK] {description} completed successfully')
        return True
    except subprocess.CalledProcessError as e:
        print(f'[ERROR] {description} failed: {e}')
        return False


def main():
    scripts_dir = Path(__file__).parent
    results_dir = scripts_dir.parent / 'backtest_results'
    results_dir.mkdir(exist_ok=True)

    print('=' * 60)
    print('END-TO-END BACKTEST RERUN WORKFLOW DEMONSTRATION')
    print('=' * 60)
    print()
    print('This workflow demonstrates:')
    print('1. Sample backtest generation (corrected P&L)')
    print('2. Result comparison (old vs new)')
    print('3. Invalid marking automation')
    print('4. Prioritized rerun planning')
    print()
    input('Press Enter to start...')

    # Step 1: Run sample backtest
    if not run_command(
        [sys.executable, str(scripts_dir / 'run_sample_backtest.py')],
        'Step 1: Generate sample backtest (corrected P&L)',
    ):
        return 1

    # Step 2: Compare results (if old result exists)
    old_result = results_dir / 'sample_old_INVALID.json'
    new_results = list(results_dir.glob('sample_backtest_*.json'))

    if (
        old_result.exists()
        and new_results
        and not run_command(
            [
                sys.executable,
                str(scripts_dir / 'compare_backtest_results.py'),
                str(old_result),
                str(new_results[0]),
                '--detailed',
            ],
            'Step 2: Compare old (INVALID) vs new (corrected) results',
        )
    ):
        print('[WARNING] Comparison failed, continuing...')

    # Step 3: Generate rerun plan
    plan_file = results_dir / 'rerun_plan.json'
    if not run_command(
        [
            sys.executable,
            str(scripts_dir / 'rerun_backtests.py'),
            '--results-dir',
            str(results_dir),
            '--generate-plan',
            str(plan_file),
        ],
        'Step 3: Generate prioritized rerun plan',
    ):
        print('[WARNING] Plan generation failed, continuing...')

    # Step 4: Show plan summary
    if plan_file.exists():
        print(f'\n{"=" * 60}')
        print('Step 4: Rerun Plan Summary')
        print(f'{"=" * 60}')
        with open(plan_file) as f:
            plan = json.load(f)

        print(f'Total backtest results found: {plan["total_results"]}')
        print(f'Pre-fix (INVALID) results: {plan["pre_fix_results"]}')
        print('\nTop 5 priorities:')
        for i, item in enumerate(plan['rerun_plan'][:5], 1):
            print(
                f'  {i}. {Path(item["file"]).name} '
                f'(score={item["impact_score"]:.1f}, '
                f'return={item.get("total_return", "N/A")}, '
                f'trades={item.get("num_trades", "N/A")})'
            )

    # Summary
    print(f'\n{"=" * 60}')
    print('WORKFLOW COMPLETE')
    print(f'{"=" * 60}')
    print()
    print('Next steps:')
    print('1. Review generated results in backtest_results/')
    print('2. Check rerun_plan.json for priorities')
    print('3. Execute reruns for production strategies')
    print('4. Set up daily duplicate monitoring')
    print()
    print('For production use:')
    print('  - Mark invalid: python scripts/rerun_backtests.py --mark-invalid')
    print('  - Monitor duplicates: python scripts/monitor_duplicates.py logs/aistock.log --alert')
    print()

    return 0


if __name__ == '__main__':
    sys.exit(main())
