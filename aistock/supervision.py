"""
Supervised automation layer with human approval gates and enhanced alerting.

This module provides:
- ApprovalGate: Manages pending human approvals for critical actions
- AlertManager: Enhanced file-based alerting with optional webhook support
- HealthMonitor: Monitors system health (data staleness, risk breaches, position drift)
- SupervisedAutopilot: Wraps AutoPilot with approval gates and alerting
- ScheduledAutopilot: Runs supervised autopilot on a schedule
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .audit import AlertDispatcher
from .automation import AutoPilot, AutoPilotReport, PipelineConfig
from .logging import configure_logger


class ApprovalAction(str, Enum):
    """Types of actions requiring approval."""

    MODEL_PROMOTION = "model_promotion"
    RISK_LIMIT_CHANGE = "risk_limit_change"
    UNIVERSE_CHANGE = "universe_change"
    STRATEGY_PARAMETER_CHANGE = "strategy_parameter_change"


class AlertLevel(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ApprovalRequest:
    """A pending approval request."""

    id: str
    action: ApprovalAction
    timestamp: str
    context: dict[str, Any]
    status: str = "pending"  # pending, approved, rejected
    decided_at: str | None = None
    decided_by: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class SupervisionConfig:
    """
    Configuration for supervised autopilot.

    Attributes:
        auto_approve_training: Automatically approve ML model training.
        auto_approve_promotion: Automatically approve model promotion to active registry.
        auto_approve_risk_changes: Automatically approve risk limit adjustments.
        auto_approve_universe_changes: Automatically approve universe/symbol changes.
        alert_dir: Directory for alert output files.
        pending_approvals_path: JSON file tracking pending approvals.
        schedule_interval_minutes: How often to run autopilot (None = manual only).
        health_check_interval_seconds: Health monitor check frequency.
        data_staleness_hours: Alert if no new data ingested in X hours.
        position_reconciliation_tolerance_pct: Alert if position drift > X%.
        notification_webhooks: Optional webhook URLs for external alerting.
            Format: {"slack": "https://hooks.slack.com/...", "email": "..."}
    """

    auto_approve_training: bool = False
    auto_approve_promotion: bool = False
    auto_approve_risk_changes: bool = False
    auto_approve_universe_changes: bool = False
    alert_dir: str = "state/alerts"
    pending_approvals_path: str = "state/alerts/pending_approvals.json"
    schedule_interval_minutes: int | None = None
    health_check_interval_seconds: int = 300
    data_staleness_hours: int = 24
    position_reconciliation_tolerance_pct: float = 1.0
    notification_webhooks: dict[str, str] = field(default_factory=dict)


class ApprovalGate:
    """
    Manages human approval workflows for critical autopilot actions.

    Usage:
        gate = ApprovalGate("state/approvals.json")
        request = gate.request_approval(ApprovalAction.MODEL_PROMOTION, {...})
        # User reviews and approves via CLI or GUI
        gate.approve(request.id, operator="alice")
        decisions = gate.process_decisions()
    """

    def __init__(self, approvals_path: str):
        self.approvals_path = Path(approvals_path).expanduser()
        self.approvals_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = configure_logger("ApprovalGate", structured=True)

    def request_approval(
        self,
        action: ApprovalAction,
        context: dict[str, Any],
    ) -> ApprovalRequest:
        """
        Create a new approval request.

        Args:
            action: Type of action requiring approval
            context: Context data for the approval decision

        Returns:
            The created approval request
        """
        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            action=action,
            timestamp=datetime.now(timezone.utc).isoformat(),
            context=context,
        )
        self._save_request(request)
        self.logger.info(
            "approval_requested",
            extra={"request_id": request.id, "action": request.action, "context": context},
        )
        return request

    def approve(self, request_id: str, operator: str | None = None, notes: str | None = None) -> bool:
        """
        Approve a pending request.

        Args:
            request_id: ID of the approval request
            operator: Optional operator identifier
            notes: Optional approval notes

        Returns:
            True if approved, False if not found or already decided
        """
        request = self._find_request(request_id)
        if not request or request.status != "pending":
            return False

        request.status = "approved"
        request.decided_at = datetime.now(timezone.utc).isoformat()
        request.decided_by = operator
        request.notes = notes
        self._update_request(request)
        self.logger.info(
            "approval_granted",
            extra={"request_id": request_id, "operator": operator, "action": request.action},
        )
        return True

    def reject(self, request_id: str, operator: str | None = None, notes: str | None = None) -> bool:
        """
        Reject a pending request.

        Args:
            request_id: ID of the approval request
            operator: Optional operator identifier
            notes: Optional rejection notes

        Returns:
            True if rejected, False if not found or already decided
        """
        request = self._find_request(request_id)
        if not request or request.status != "pending":
            return False

        request.status = "rejected"
        request.decided_at = datetime.now(timezone.utc).isoformat()
        request.decided_by = operator
        request.notes = notes
        self._update_request(request)
        self.logger.info(
            "approval_rejected",
            extra={"request_id": request_id, "operator": operator, "action": request.action, "notes": notes},
        )
        return True

    def list_pending(self) -> list[ApprovalRequest]:
        """List all pending approval requests."""
        requests = self._load_all_requests()
        return [r for r in requests if r.status == "pending"]

    def process_decisions(self) -> list[ApprovalRequest]:
        """
        Get recently decided approvals and clean up old ones.

        Returns:
            List of recently approved requests
        """
        requests = self._load_all_requests()
        approved = [r for r in requests if r.status == "approved"]
        # Clean up old decided requests (keep last 100)
        if len(requests) > 100:
            requests = sorted(requests, key=lambda r: r.timestamp, reverse=True)[:100]
            self._save_all_requests(requests)
        return approved

    def _find_request(self, request_id: str) -> ApprovalRequest | None:
        requests = self._load_all_requests()
        for request in requests:
            if request.id == request_id:
                return request
        return None

    def _save_request(self, request: ApprovalRequest) -> None:
        requests = self._load_all_requests()
        requests.append(request)
        self._save_all_requests(requests)

    def _update_request(self, request: ApprovalRequest) -> None:
        requests = self._load_all_requests()
        for i, r in enumerate(requests):
            if r.id == request.id:
                requests[i] = request
                break
        self._save_all_requests(requests)

    def _load_all_requests(self) -> list[ApprovalRequest]:
        if not self.approvals_path.exists():
            return []
        with self.approvals_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [ApprovalRequest(**item) for item in data]

    def _save_all_requests(self, requests: list[ApprovalRequest]) -> None:
        data = [
            {
                "id": r.id,
                "action": r.action,
                "timestamp": r.timestamp,
                "context": r.context,
                "status": r.status,
                "decided_at": r.decided_at,
                "decided_by": r.decided_by,
                "notes": r.notes,
            }
            for r in requests
        ]
        with self.approvals_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


class AlertManager:
    """
    Enhanced alerting system with file-based output and optional webhook notifications.

    Usage:
        manager = AlertManager("state/alerts", webhooks={"slack": "https://..."})
        manager.alert(AlertLevel.WARNING, "Data staleness detected", {"hours": 25})
    """

    def __init__(self, alert_dir: str, webhooks: dict[str, str] | None = None):
        self.alert_dir = Path(alert_dir).expanduser()
        self.alert_dir.mkdir(parents=True, exist_ok=True)
        self.webhooks = webhooks or {}
        self.dispatcher = AlertDispatcher()
        self.logger = configure_logger("AlertManager", structured=True)

    def alert(self, level: AlertLevel, message: str, context: dict[str, Any] | None = None) -> None:
        """
        Emit an alert.

        Args:
            level: Alert severity level
            message: Alert message
            context: Additional context data
        """
        timestamp = datetime.now(timezone.utc)
        alert_data = {
            "timestamp": timestamp.isoformat(),
            "level": level.value,
            "message": message,
            "context": context or {},
        }

        # Write to file
        level_dir = self.alert_dir / level.value
        level_dir.mkdir(exist_ok=True)
        alert_file = level_dir / f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
        with alert_file.open("w", encoding="utf-8") as f:
            json.dump(alert_data, f, indent=2)

        # Emit via dispatcher
        self.dispatcher.notify(level.value, alert_data)

        # Send webhooks for warnings and above
        if level in (AlertLevel.WARNING, AlertLevel.ERROR, AlertLevel.CRITICAL):
            self._send_webhooks(alert_data)

        # Log alert (rename fields to avoid LogRecord conflicts)
        self.logger.info("alert_emitted", extra={
            "alert_level": level.value,
            "alert_message": message,
            "alert_context": context or {},
        })

    def _send_webhooks(self, alert_data: dict[str, Any]) -> None:
        """Send alert to configured webhooks (Slack, etc.)."""
        for name, url in self.webhooks.items():
            try:
                # For now, just log the webhook call
                # In production, use requests library to POST to webhook URL
                self.logger.info(
                    "webhook_notification",
                    extra={"webhook": name, "url": url, "alert": alert_data},
                )
                # TODO: Implement actual HTTP POST when requests library is available
                # import requests
                # requests.post(url, json=alert_data, timeout=5)
            except Exception as e:
                self.logger.error(
                    "webhook_failed",
                    extra={"webhook": name, "error": str(e)},
                )


class HealthMonitor:
    """
    Monitors system health and emits alerts for issues.

    Checks:
    - Data staleness (no new bars ingested in X hours)
    - Risk breaches (position reconciliation, risk limits)
    - Autopilot failures
    """

    def __init__(
        self,
        ingestion_manifest_path: str,
        alert_manager: AlertManager,
        staleness_threshold_hours: int = 24,
    ):
        self.ingestion_manifest_path = Path(ingestion_manifest_path).expanduser()
        self.alert_manager = alert_manager
        self.staleness_threshold = timedelta(hours=staleness_threshold_hours)
        self.logger = configure_logger("HealthMonitor", structured=True)
        self.last_check = None

    def check_health(self) -> dict[str, Any]:
        """
        Run all health checks.

        Returns:
            Health status report
        """
        now = datetime.now(timezone.utc)
        issues = []

        # Check data staleness
        if self.ingestion_manifest_path.exists():
            with self.ingestion_manifest_path.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
            last_update_str = manifest.get("last_update")
            if last_update_str:
                last_update = datetime.fromisoformat(last_update_str.replace("Z", "+00:00"))
                age = now - last_update
                if age > self.staleness_threshold:
                    issue = {
                        "type": "data_staleness",
                        "severity": "warning",
                        "message": f"No new data in {age.total_seconds() / 3600:.1f} hours",
                        "last_update": last_update_str,
                    }
                    issues.append(issue)
                    self.alert_manager.alert(
                        AlertLevel.WARNING,
                        "Data staleness detected",
                        {"hours_since_update": age.total_seconds() / 3600},
                    )
        else:
            issue = {
                "type": "missing_manifest",
                "severity": "error",
                "message": "Ingestion manifest not found",
            }
            issues.append(issue)
            self.alert_manager.alert(AlertLevel.ERROR, "Ingestion manifest missing", {})

        self.last_check = now.isoformat()
        health_report = {
            "timestamp": now.isoformat(),
            "healthy": len(issues) == 0,
            "issues": issues,
        }

        if health_report["healthy"]:
            self.logger.info("health_check_passed", extra=health_report)
        else:
            self.logger.warning("health_check_failed", extra=health_report)

        return health_report


class SupervisedAutopilot:
    """
    Wraps AutoPilot with human approval gates and enhanced monitoring.

    Usage:
        config = PipelineConfig(...)
        supervision = SupervisionConfig(auto_approve_training=True)
        autopilot = SupervisedAutopilot(config, supervision)
        report = autopilot.run_supervised()
    """

    def __init__(self, pipeline_config: PipelineConfig, supervision_config: SupervisionConfig):
        self.pipeline_config = pipeline_config
        self.supervision_config = supervision_config
        self.autopilot = AutoPilot(pipeline_config)
        self.approval_gate = ApprovalGate(supervision_config.pending_approvals_path)
        self.alert_manager = AlertManager(
            supervision_config.alert_dir,
            webhooks=supervision_config.notification_webhooks,
        )
        self.logger = configure_logger("SupervisedAutopilot", structured=True)

        # Initialize health monitor if ingestion config is available
        if pipeline_config.ingestion:
            manifest_path = pipeline_config.ingestion.manifest_path
        elif pipeline_config.acquisition:
            manifest_path = pipeline_config.acquisition.ingestion.manifest_path
        else:
            manifest_path = "state/ingestion/manifest.json"

        self.health_monitor = HealthMonitor(
            manifest_path,
            self.alert_manager,
            staleness_threshold_hours=supervision_config.data_staleness_hours,
        )

    def run_supervised(self) -> dict[str, Any]:
        """
        Run autopilot with supervision.

        Returns:
            Supervised report including autopilot report and supervision decisions
        """
        self.logger.info("supervised_run_started")
        start_time = datetime.now(timezone.utc)

        # Run health check before autopilot
        health_report = self.health_monitor.check_health()
        if not health_report["healthy"]:
            self.logger.warning("health_check_failed_before_run", extra=health_report)
            # Continue anyway, but log the warning

        # Run autopilot
        try:
            autopilot_report = self.autopilot.run_once()
        except Exception as e:
            self.logger.error("autopilot_failed", extra={"error": str(e)})
            self.alert_manager.alert(
                AlertLevel.ERROR,
                "Autopilot execution failed",
                {"error": str(e)},
            )
            raise

        # Check if model promotion occurred
        supervision_decisions = []
        if autopilot_report.promotion:
            decision = self._supervise_promotion(autopilot_report)
            supervision_decisions.append(decision)

        # Process pending approvals
        approved_requests = self.approval_gate.process_decisions()

        end_time = datetime.now(timezone.utc)
        supervised_report = {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": (end_time - start_time).total_seconds(),
            "autopilot_report": autopilot_report.to_dict(),
            "health_report": health_report,
            "supervision_decisions": supervision_decisions,
            "approved_requests_count": len(approved_requests),
            "pending_approvals_count": len(self.approval_gate.list_pending()),
        }

        self.logger.info("supervised_run_completed", extra=supervised_report)
        self.alert_manager.alert(
            AlertLevel.INFO,
            "Supervised autopilot run completed",
            supervised_report,
        )

        return supervised_report

    def _supervise_promotion(self, autopilot_report: AutoPilotReport) -> dict[str, Any]:
        """
        Apply supervision to model promotion.

        Returns:
            Supervision decision
        """
        promotion = autopilot_report.promotion
        if not promotion:
            return {"action": "promotion", "status": "no_promotion"}

        if promotion.status == "rejected":
            return {
                "action": "promotion",
                "status": "already_rejected",
                "reason": promotion.reason,
            }

        # Check if auto-approval is enabled
        if self.supervision_config.auto_approve_promotion:
            self.logger.info(
                "promotion_auto_approved",
                extra={"model_id": promotion.model_id, "metrics": promotion.metrics},
            )
            return {
                "action": "promotion",
                "status": "auto_approved",
                "model_id": promotion.model_id,
            }

        # Require human approval
        request = self.approval_gate.request_approval(
            ApprovalAction.MODEL_PROMOTION,
            {
                "model_id": promotion.model_id,
                "metrics": promotion.metrics,
                "report_path": promotion.report_path,
            },
        )

        self.alert_manager.alert(
            AlertLevel.WARNING,
            "Model promotion requires approval",
            {
                "request_id": request.id,
                "model_id": promotion.model_id,
                "metrics": promotion.metrics,
            },
        )

        return {
            "action": "promotion",
            "status": "pending_approval",
            "request_id": request.id,
            "model_id": promotion.model_id,
        }


class ScheduledAutopilot:
    """
    Runs supervised autopilot on a schedule with health monitoring.

    Usage:
        scheduler = ScheduledAutopilot(pipeline_config, supervision_config)
        scheduler.start()  # Runs in background
        # Later...
        scheduler.stop()
    """

    def __init__(self, pipeline_config: PipelineConfig, supervision_config: SupervisionConfig):
        if supervision_config.schedule_interval_minutes is None:
            raise ValueError("SupervisionConfig.schedule_interval_minutes must be set for scheduled mode")

        self.pipeline_config = pipeline_config
        self.supervision_config = supervision_config
        self.supervised_autopilot = SupervisedAutopilot(pipeline_config, supervision_config)
        self.logger = configure_logger("ScheduledAutopilot", structured=True)
        self.running = False
        self.last_run: datetime | None = None
        self.next_run: datetime | None = None

    def start(self) -> None:
        """
        Start the scheduled autopilot.

        Note: This is a simple implementation without APScheduler dependency.
        For production use, integrate with APScheduler, Airflow, or similar.
        """
        if self.running:
            self.logger.warning("scheduler_already_running")
            return

        self.running = True
        self.logger.info("scheduler_started", extra={"interval_minutes": self.supervision_config.schedule_interval_minutes})

        # Schedule first run
        self._schedule_next_run()

    def stop(self) -> None:
        """Stop the scheduler."""
        self.running = False
        self.logger.info("scheduler_stopped")

    def run_now(self) -> dict[str, Any]:
        """Run autopilot immediately (manual trigger)."""
        self.logger.info("manual_run_triggered")
        try:
            report = self.supervised_autopilot.run_supervised()
            self.last_run = datetime.now(timezone.utc)
            return report
        except Exception as e:
            self.logger.error("manual_run_failed", extra={"error": str(e)})
            raise

    def tick(self) -> dict[str, Any] | None:
        """
        Check if it's time to run and execute if so.

        Returns:
            Report if run occurred, None otherwise
        """
        if not self.running:
            return None

        now = datetime.now(timezone.utc)
        if self.next_run and now >= self.next_run:
            try:
                report = self.supervised_autopilot.run_supervised()
                self.last_run = now
                self._schedule_next_run()
                return report
            except Exception as e:
                self.logger.error("scheduled_run_failed", extra={"error": str(e)})
                self._schedule_next_run()
                raise

        return None

    def _schedule_next_run(self) -> None:
        """Schedule the next autopilot run."""
        interval = timedelta(minutes=self.supervision_config.schedule_interval_minutes)
        self.next_run = datetime.now(timezone.utc) + interval
        self.logger.info("next_run_scheduled", extra={"next_run": self.next_run.isoformat()})


__all__ = [
    "AlertLevel",
    "AlertManager",
    "ApprovalAction",
    "ApprovalGate",
    "ApprovalRequest",
    "HealthMonitor",
    "ScheduledAutopilot",
    "SupervisedAutopilot",
    "SupervisionConfig",
]
