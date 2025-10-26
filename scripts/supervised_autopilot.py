"""
CLI entry point for supervised autopilot with human approval gates.

Usage:
    # Run once (manual mode)
    python scripts/supervised_autopilot.py config.json --run-once

    # Run on schedule (daemon mode)
    python scripts/supervised_autopilot.py config.json --schedule

    # Check health
    python scripts/supervised_autopilot.py config.json --health-check

    # Manage approvals
    python scripts/supervised_autopilot.py config.json --list-approvals
    python scripts/supervised_autopilot.py config.json --approve <request_id>
    python scripts/supervised_autopilot.py config.json --reject <request_id> --notes "reason"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Import the config loader from run_autopilot.py
from run_autopilot import load_pipeline_config

from aistock.supervision import (
    ScheduledAutopilot,
    SupervisedAutopilot,
    SupervisionConfig,
    ApprovalGate,
    HealthMonitor,
    AlertManager,
)


def load_supervision_config(config_path: Path) -> tuple:
    """
    Load both pipeline and supervision configs from a JSON file.

    Returns:
        Tuple of (PipelineConfig, SupervisionConfig)
    """
    with config_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    # Load pipeline config using existing loader
    pipeline_config = load_pipeline_config(config_path)

    # Load supervision config
    supervision_payload = payload.get("supervision", {})
    supervision_config = SupervisionConfig(
        auto_approve_training=supervision_payload.get("auto_approve_training", False),
        auto_approve_promotion=supervision_payload.get("auto_approve_promotion", False),
        auto_approve_risk_changes=supervision_payload.get("auto_approve_risk_changes", False),
        auto_approve_universe_changes=supervision_payload.get("auto_approve_universe_changes", False),
        alert_dir=supervision_payload.get("alert_dir", "state/alerts"),
        pending_approvals_path=supervision_payload.get("pending_approvals_path", "state/alerts/pending_approvals.json"),
        schedule_interval_minutes=supervision_payload.get("schedule_interval_minutes"),
        health_check_interval_seconds=supervision_payload.get("health_check_interval_seconds", 300),
        data_staleness_hours=supervision_payload.get("data_staleness_hours", 24),
        position_reconciliation_tolerance_pct=supervision_payload.get("position_reconciliation_tolerance_pct", 1.0),
        notification_webhooks=supervision_payload.get("notification_webhooks", {}),
    )

    return pipeline_config, supervision_config


def cmd_run_once(args):
    """Run supervised autopilot once."""
    pipeline_config, supervision_config = load_supervision_config(args.config)
    autopilot = SupervisedAutopilot(pipeline_config, supervision_config)

    print("=" * 80)
    print("SUPERVISED AUTOPILOT - SINGLE RUN")
    print("=" * 80)
    print(f"Config: {args.config}")
    print(f"Auto-approve promotion: {supervision_config.auto_approve_promotion}")
    print(f"Auto-approve training: {supervision_config.auto_approve_training}")
    print(f"Alert directory: {supervision_config.alert_dir}")
    print("=" * 80)
    print()

    try:
        report = autopilot.run_supervised()
        print()
        print("=" * 80)
        print("RUN COMPLETED")
        print("=" * 80)
        print(json.dumps(report, indent=2))
        print()

        # Show pending approvals
        pending = autopilot.approval_gate.list_pending()
        if pending:
            print("=" * 80)
            print(f"PENDING APPROVALS: {len(pending)}")
            print("=" * 80)
            for req in pending:
                print(f"  ID: {req.id}")
                print(f"  Action: {req.action}")
                print(f"  Timestamp: {req.timestamp}")
                print(f"  Context: {json.dumps(req.context, indent=4)}")
                print()
            print(f"To approve: python {' '.join(sys.argv)} --approve <request_id>")
            print(f"To reject:  python {' '.join(sys.argv)} --reject <request_id> --notes 'reason'")
            print()

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def cmd_schedule(args):
    """Run supervised autopilot on schedule."""
    pipeline_config, supervision_config = load_supervision_config(args.config)

    if supervision_config.schedule_interval_minutes is None:
        print("ERROR: schedule_interval_minutes not configured", file=sys.stderr)
        print("Add 'supervision.schedule_interval_minutes' to your config file.", file=sys.stderr)
        return 1

    scheduler = ScheduledAutopilot(pipeline_config, supervision_config)

    print("=" * 80)
    print("SUPERVISED AUTOPILOT - SCHEDULED MODE")
    print("=" * 80)
    print(f"Config: {args.config}")
    print(f"Schedule: Every {supervision_config.schedule_interval_minutes} minutes")
    print(f"Health check: Every {supervision_config.health_check_interval_seconds} seconds")
    print(f"Auto-approve promotion: {supervision_config.auto_approve_promotion}")
    print(f"Alert directory: {supervision_config.alert_dir}")
    print("=" * 80)
    print("Press Ctrl+C to stop")
    print()

    scheduler.start()

    try:
        while scheduler.running:
            # Tick the scheduler
            report = scheduler.tick()
            if report:
                print(f"[{report['end_time']}] Run completed")
                if report['pending_approvals_count'] > 0:
                    print(f"  → {report['pending_approvals_count']} pending approvals")

            time.sleep(10)  # Check every 10 seconds

    except KeyboardInterrupt:
        print("\nStopping scheduler...")
        scheduler.stop()
        print("Stopped.")
        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        scheduler.stop()
        return 1


def cmd_health_check(args):
    """Run health check."""
    pipeline_config, supervision_config = load_supervision_config(args.config)
    autopilot = SupervisedAutopilot(pipeline_config, supervision_config)

    print("=" * 80)
    print("HEALTH CHECK")
    print("=" * 80)

    report = autopilot.health_monitor.check_health()

    if report["healthy"]:
        print("✓ HEALTHY")
    else:
        print("✗ UNHEALTHY")

    print()
    print(json.dumps(report, indent=2))
    print()

    return 0 if report["healthy"] else 1


def cmd_list_approvals(args):
    """List pending approvals."""
    _, supervision_config = load_supervision_config(args.config)
    gate = ApprovalGate(supervision_config.pending_approvals_path)

    pending = gate.list_pending()

    print("=" * 80)
    print(f"PENDING APPROVALS: {len(pending)}")
    print("=" * 80)
    print()

    if not pending:
        print("No pending approvals.")
        print()
        return 0

    for req in pending:
        print(f"Request ID: {req.id}")
        print(f"  Action:    {req.action}")
        print(f"  Timestamp: {req.timestamp}")
        print(f"  Context:   {json.dumps(req.context, indent=13)}")
        print()
        print(f"  To approve: python {' '.join(sys.argv[:-1])} --approve {req.id}")
        print(f"  To reject:  python {' '.join(sys.argv[:-1])} --reject {req.id} --notes 'reason'")
        print()
        print("-" * 80)
        print()

    return 0


def cmd_approve(args):
    """Approve a pending request."""
    _, supervision_config = load_supervision_config(args.config)
    gate = ApprovalGate(supervision_config.pending_approvals_path)

    success = gate.approve(args.approve, operator=args.operator, notes=args.notes)

    if success:
        print(f"✓ Approved request {args.approve}")
        return 0
    else:
        print(f"✗ Failed to approve request {args.approve} (not found or already decided)", file=sys.stderr)
        return 1


def cmd_reject(args):
    """Reject a pending request."""
    _, supervision_config = load_supervision_config(args.config)
    gate = ApprovalGate(supervision_config.pending_approvals_path)

    if not args.notes:
        print("ERROR: --notes required for rejection", file=sys.stderr)
        return 1

    success = gate.reject(args.reject, operator=args.operator, notes=args.notes)

    if success:
        print(f"✓ Rejected request {args.reject}")
        return 0
    else:
        print(f"✗ Failed to reject request {args.reject} (not found or already decided)", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description="Run supervised autopilot with human approval gates")
    parser.add_argument("config", type=Path, help="Path to pipeline configuration JSON file")

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--run-once", action="store_true", help="Run autopilot once")
    mode_group.add_argument("--schedule", action="store_true", help="Run autopilot on schedule (daemon)")
    mode_group.add_argument("--health-check", action="store_true", help="Run health check")
    mode_group.add_argument("--list-approvals", action="store_true", help="List pending approvals")
    mode_group.add_argument("--approve", metavar="REQUEST_ID", help="Approve a pending request")
    mode_group.add_argument("--reject", metavar="REQUEST_ID", help="Reject a pending request")

    # Common options
    parser.add_argument("--operator", help="Operator identifier (for approvals)")
    parser.add_argument("--notes", help="Notes for approval/rejection")

    args = parser.parse_args()

    if args.run_once:
        return cmd_run_once(args)
    elif args.schedule:
        return cmd_schedule(args)
    elif args.health_check:
        return cmd_health_check(args)
    elif args.list_approvals:
        return cmd_list_approvals(args)
    elif args.approve:
        return cmd_approve(args)
    elif args.reject:
        return cmd_reject(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
