"""
CLI entry point for fully autonomous headless autopilot.

⚠️  WARNING: This mode runs completely autonomously without human approval.
    Only use after extensive testing in supervised mode.

Usage:
    # Run once (test mode)
    python scripts/headless_autopilot.py config.json --run-once

    # Run on schedule (fully autonomous daemon)
    python scripts/headless_autopilot.py config.json --daemon

    # Activate kill switch (emergency stop)
    python scripts/headless_autopilot.py config.json --kill

    # Deactivate kill switch
    python scripts/headless_autopilot.py config.json --unkill
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from run_autopilot import load_pipeline_config

from aistock.headless import HeadlessAutopilot, HeadlessConfig, RemoteKillSwitch
from aistock.supervision import SupervisionConfig


def load_headless_config(config_path: Path) -> tuple:
    """
    Load pipeline, supervision, and headless configs.

    Returns:
        Tuple of (PipelineConfig, SupervisionConfig, HeadlessConfig)
    """
    with config_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    # Load pipeline config
    pipeline_config = load_pipeline_config(config_path)

    # Load supervision config
    supervision_payload = payload.get("supervision", {})
    supervision_config = SupervisionConfig(
        alert_dir=supervision_payload.get("alert_dir", "state/alerts"),
        pending_approvals_path=supervision_payload.get("pending_approvals_path", "state/alerts/pending_approvals.json"),
        data_staleness_hours=supervision_payload.get("data_staleness_hours", 24),
        notification_webhooks=supervision_payload.get("notification_webhooks", {}),
    )

    # Load headless config
    headless_payload = payload.get("headless", {})
    headless_config = HeadlessConfig(
        enable_auto_promotion=headless_payload.get("enable_auto_promotion", True),
        enable_auto_risk_adjustment=headless_payload.get("enable_auto_risk_adjustment", True),
        enable_auto_recovery=headless_payload.get("enable_auto_recovery", True),
        promotion_validation_stages=headless_payload.get("promotion_validation_stages", 3),
        max_risk_increase_pct=headless_payload.get("max_risk_increase_pct", 0.05),
        min_risk_floor=headless_payload.get("min_risk_floor", 0.10),
        max_consecutive_failures=headless_payload.get("max_consecutive_failures", 3),
        performance_monitoring_window_days=headless_payload.get("performance_monitoring_window_days", 7),
        auto_rollback_on_degradation=headless_payload.get("auto_rollback_on_degradation", True),
        degradation_threshold_pct=headless_payload.get("degradation_threshold_pct", 0.10),
        kill_switch_check_url=headless_payload.get("kill_switch_check_url"),
        kill_switch_check_interval_seconds=headless_payload.get("kill_switch_check_interval_seconds", 60),
        external_health_report_url=headless_payload.get("external_health_report_url"),
        health_report_interval_seconds=headless_payload.get("health_report_interval_seconds", 300),
    )

    return pipeline_config, supervision_config, headless_config


def cmd_run_once(args):
    """Run headless autopilot once."""
    pipeline_config, supervision_config, headless_config = load_headless_config(args.config)
    autopilot = HeadlessAutopilot(pipeline_config, supervision_config, headless_config)

    print("=" * 80)
    print("⚠️  HEADLESS AUTOPILOT - FULLY AUTONOMOUS MODE")
    print("=" * 80)
    print(f"Config: {args.config}")
    print(f"Auto-promotion: {headless_config.enable_auto_promotion}")
    print(f"Auto-risk adjustment: {headless_config.enable_auto_risk_adjustment}")
    print(f"Auto-recovery: {headless_config.enable_auto_recovery}")
    print(f"Alert directory: {supervision_config.alert_dir}")
    print("=" * 80)
    print("⚠️  This mode operates WITHOUT HUMAN APPROVAL")
    print("=" * 80)
    print()

    try:
        report = autopilot.run_headless()
        print()
        print("=" * 80)
        print("RUN COMPLETED")
        print("=" * 80)
        print(json.dumps(report, indent=2))
        print()

        if report["status"] == "killed":
            print("⚠️  KILL SWITCH ACTIVE - Autopilot halted")
            return 1

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def cmd_daemon(args):
    """Run headless autopilot as daemon."""
    pipeline_config, supervision_config, headless_config = load_headless_config(args.config)

    if not args.interval_minutes:
        print("ERROR: --interval-minutes required for daemon mode", file=sys.stderr)
        return 1

    interval_seconds = args.interval_minutes * 60

    autopilot = HeadlessAutopilot(pipeline_config, supervision_config, headless_config)

    print("=" * 80)
    print("⚠️  HEADLESS AUTOPILOT - DAEMON MODE")
    print("=" * 80)
    print(f"Config: {args.config}")
    print(f"Interval: Every {args.interval_minutes} minutes")
    print(f"Auto-promotion: {headless_config.enable_auto_promotion}")
    print(f"Auto-risk adjustment: {headless_config.enable_auto_risk_adjustment}")
    print(f"Kill switch check: state/KILL_SWITCH file")
    print("=" * 80)
    print("⚠️  THIS RUNS COMPLETELY AUTONOMOUSLY")
    print("⚠️  CREATE state/KILL_SWITCH FILE TO HALT")
    print("=" * 80)
    print("Press Ctrl+C to stop")
    print()

    next_run = time.time()

    try:
        while True:
            now = time.time()

            if now >= next_run:
                print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting headless run...")

                try:
                    report = autopilot.run_headless()

                    if report["status"] == "killed":
                        print("⚠️  KILL SWITCH ACTIVATED - Daemon halted")
                        return 1

                    elif report["status"] == "success":
                        print("  ✓ Success")
                        if report.get("promotion_decision"):
                            promo = report["promotion_decision"]
                            if promo["approved"]:
                                print(f"    → Model auto-promoted: {promo['model_id']}")
                            else:
                                print(f"    → Model rejected: {promo['reason']}")
                        if report.get("risk_adjustment"):
                            print(f"    → Risk adjusted: {report['risk_adjustment']['reason']}")

                    else:
                        print(f"  ⚠️  {report['status']}")

                except Exception as e:
                    print(f"  ✗ Error: {e}")

                next_run = now + interval_seconds

            time.sleep(10)  # Check every 10 seconds

    except KeyboardInterrupt:
        print("\nStopping daemon...")
        return 0


def cmd_kill(args):
    """Activate kill switch."""
    _, supervision_config, headless_config = load_headless_config(args.config)
    kill_switch = RemoteKillSwitch(headless_config)
    kill_switch.activate()
    print("✓ Kill switch activated (state/KILL_SWITCH file created)")
    print("  Headless autopilot will halt on next run")
    return 0


def cmd_unkill(args):
    """Deactivate kill switch."""
    _, supervision_config, headless_config = load_headless_config(args.config)
    kill_switch = RemoteKillSwitch(headless_config)
    kill_switch.deactivate()
    print("✓ Kill switch deactivated (state/KILL_SWITCH file removed)")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="⚠️  Fully autonomous headless autopilot (USE WITH CAUTION)",
    )
    parser.add_argument("config", type=Path, help="Path to pipeline configuration JSON file")

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--run-once", action="store_true", help="Run autopilot once (test mode)")
    mode_group.add_argument("--daemon", action="store_true", help="Run as daemon (fully autonomous)")
    mode_group.add_argument("--kill", action="store_true", help="Activate kill switch (emergency stop)")
    mode_group.add_argument("--unkill", action="store_true", help="Deactivate kill switch")

    # Daemon options
    parser.add_argument("--interval-minutes", type=int, help="Run interval in minutes (for --daemon)")

    args = parser.parse_args()

    if args.run_once:
        return cmd_run_once(args)
    elif args.daemon:
        return cmd_daemon(args)
    elif args.kill:
        return cmd_kill(args)
    elif args.unkill:
        return cmd_unkill(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
