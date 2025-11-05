#!/usr/bin/env python3
"""
Duplicate Order Monitoring Script

Monitors logs for duplicate order patterns to validate Option D (time-boxed idempotency)
is working correctly in production.

WHAT TO MONITOR:
1. Same-session duplicates (should be ZERO)
2. Cross-restart duplicates within 5-min window (should be ZERO)
3. Intentional retries after 5-min window (expected, track rate)

ALERTS:
- Same-session duplicate: CRITICAL (Option D failed)
- Cross-restart duplicate <5min: HIGH (time-box failed)
- Retry rate >10%: WARNING (possible data/broker issues)
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_log_line(line: str) -> dict[str, Any] | None:
    """Parse structured log line."""
    try:
        # Assume JSON structured logs
        if line.strip().startswith('{'):
            return json.loads(line)

        # Fallback: regex for common log formats
        # Example: 2025-11-02 14:30:00 - INFO - Order submitted: AAPL T000123
        pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Order submitted: (\w+) (\w+)'
        match = re.search(pattern, line)
        if match:
            return {
                'timestamp': match.group(1),
                'symbol': match.group(2),
                'order_id': match.group(3),
            }

        return None
    except Exception:
        return None


def analyze_duplicates(log_file: Path) -> dict[str, Any]:
    """Analyze log file for duplicate patterns."""
    submissions = defaultdict(list)  # client_order_id -> [(timestamp, order_id)]
    duplicates = {
        'same_session': [],
        'cross_restart_under_5min': [],
        'retries_over_5min': [],
    }

    with open(log_file) as f:
        for line in f:
            entry = parse_log_line(line)
            if not entry:
                continue

            # Look for order submissions
            if 'Order submitted' in line or entry.get('event') == 'order_submitted':
                client_id = entry.get('client_order_id', 'UNKNOWN')
                timestamp = datetime.fromisoformat(entry['timestamp'])
                order_id = entry.get('order_id', 'UNKNOWN')

                # Check for duplicates
                if client_id in submissions:
                    prev_ts, prev_order = submissions[client_id][-1]
                    time_delta = (timestamp - prev_ts).total_seconds()

                    if time_delta < 60:  # <1 min = same session
                        duplicates['same_session'].append(
                            {
                                'client_id': client_id,
                                'first_order': prev_order,
                                'duplicate_order': order_id,
                                'time_delta_sec': time_delta,
                            }
                        )
                    elif time_delta < 300:  # 1-5 min = cross-restart window
                        duplicates['cross_restart_under_5min'].append(
                            {
                                'client_id': client_id,
                                'first_order': prev_order,
                                'retry_order': order_id,
                                'time_delta_sec': time_delta,
                            }
                        )
                    else:  # >5 min = intentional retry (expected)
                        duplicates['retries_over_5min'].append(
                            {
                                'client_id': client_id,
                                'first_order': prev_order,
                                'retry_order': order_id,
                                'time_delta_sec': time_delta,
                            }
                        )

                submissions[client_id].append((timestamp, order_id))

    return {
        'total_submissions': sum(len(v) for v in submissions.values()),
        'unique_clients': len(submissions),
        'duplicates': duplicates,
        'metrics': {
            'same_session_rate': len(duplicates['same_session']) / max(len(submissions), 1),
            'cross_restart_rate': len(duplicates['cross_restart_under_5min']) / max(len(submissions), 1),
            'retry_rate': len(duplicates['retries_over_5min']) / max(len(submissions), 1),
        },
    }


def generate_alert(analysis: dict[str, Any]) -> str | None:
    """Generate alert if thresholds exceeded."""
    alerts = []

    # CRITICAL: Same-session duplicates
    if analysis['duplicates']['same_session']:
        alerts.append(
            f'[CRITICAL] {len(analysis["duplicates"]["same_session"])} '
            'same-session duplicates detected! Option D failed.'
        )

    # HIGH: Cross-restart duplicates <5min
    if analysis['duplicates']['cross_restart_under_5min']:
        alerts.append(
            f'[HIGH] {len(analysis["duplicates"]["cross_restart_under_5min"])} '
            'cross-restart duplicates within 5-min window detected! Time-box failed.'
        )

    # WARNING: High retry rate
    retry_rate = analysis['metrics']['retry_rate']
    if retry_rate > 0.1:  # >10%
        alerts.append(
            f'[WARNING] Retry rate at {retry_rate * 100:.1f}% (threshold: 10%). Possible data lag or broker issues.'
        )

    return '\n'.join(alerts) if alerts else None


def main():
    parser = argparse.ArgumentParser(description='Monitor duplicate order patterns')
    parser.add_argument('log_file', type=Path, help='Log file to analyze')
    parser.add_argument('--output', type=Path, help='Save analysis to JSON file')
    parser.add_argument('--alert', action='store_true', help='Print alerts to stdout')

    args = parser.parse_args()

    if not args.log_file.exists():
        print(f'Error: Log file not found: {args.log_file}')
        return 1

    print(f'Analyzing {args.log_file}...')
    analysis = analyze_duplicates(args.log_file)

    print('\nSummary:')
    print(f'  Total submissions: {analysis["total_submissions"]}')
    print(f'  Unique clients: {analysis["unique_clients"]}')
    print(f'  Same-session duplicates: {len(analysis["duplicates"]["same_session"])} [CRITICAL]')
    print(f'  Cross-restart (<5min): {len(analysis["duplicates"]["cross_restart_under_5min"])} [WARNING]')
    print(f'  Retries (>5min): {len(analysis["duplicates"]["retries_over_5min"])} [OK]')
    print('\nMetrics:')
    print(f'  Same-session rate: {analysis["metrics"]["same_session_rate"] * 100:.2f}%')
    print(f'  Cross-restart rate: {analysis["metrics"]["cross_restart_rate"] * 100:.2f}%')
    print(f'  Retry rate: {analysis["metrics"]["retry_rate"] * 100:.2f}%')

    if args.alert:
        alert = generate_alert(analysis)
        if alert:
            print(f'\n{alert}')
        else:
            print('\n[OK] No alerts - duplicate protection working as expected')

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(analysis, f, indent=2)
        print(f'\nAnalysis saved to: {args.output}')

    return 0


if __name__ == '__main__':
    exit(main())
