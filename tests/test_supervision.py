"""Tests for the supervision module (approval gates, alerts, health monitoring)."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aistock.supervision import (
    AlertLevel,
    AlertManager,
    ApprovalAction,
    ApprovalGate,
    HealthMonitor,
    SupervisionConfig,
)


class TestApprovalGate(unittest.TestCase):
    """Test approval gate workflow."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.approvals_path = Path(self.temp_dir) / "approvals.json"
        self.gate = ApprovalGate(str(self.approvals_path))

    def test_request_approval(self):
        """Test creating an approval request."""
        context = {"model_id": "model_123", "metrics": {"sharpe": 0.8}}
        request = self.gate.request_approval(ApprovalAction.MODEL_PROMOTION, context)

        self.assertIsNotNone(request.id)
        self.assertEqual(request.action, ApprovalAction.MODEL_PROMOTION)
        self.assertEqual(request.context, context)
        self.assertEqual(request.status, "pending")

        # Verify persisted
        self.assertTrue(self.approvals_path.exists())
        pending = self.gate.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, request.id)

    def test_approve_request(self):
        """Test approving a pending request."""
        request = self.gate.request_approval(
            ApprovalAction.MODEL_PROMOTION,
            {"model_id": "test"},
        )

        success = self.gate.approve(request.id, operator="alice", notes="looks good")
        self.assertTrue(success)

        # Verify no longer pending
        pending = self.gate.list_pending()
        self.assertEqual(len(pending), 0)

        # Verify decision recorded
        decisions = self.gate.process_decisions()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].id, request.id)
        self.assertEqual(decisions[0].status, "approved")
        self.assertEqual(decisions[0].decided_by, "alice")
        self.assertEqual(decisions[0].notes, "looks good")

    def test_reject_request(self):
        """Test rejecting a pending request."""
        request = self.gate.request_approval(
            ApprovalAction.RISK_LIMIT_CHANGE,
            {"old_limit": 0.25, "new_limit": 0.30},
        )

        success = self.gate.reject(request.id, operator="bob", notes="too risky")
        self.assertTrue(success)

        # Verify no longer pending
        pending = self.gate.list_pending()
        self.assertEqual(len(pending), 0)

        # Load from file and verify
        with self.approvals_path.open("r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["status"], "rejected")
        self.assertEqual(data[0]["decided_by"], "bob")

    def test_approve_nonexistent(self):
        """Test approving a non-existent request."""
        success = self.gate.approve("nonexistent-id")
        self.assertFalse(success)

    def test_approve_already_decided(self):
        """Test approving an already-decided request."""
        request = self.gate.request_approval(ApprovalAction.MODEL_PROMOTION, {})
        self.gate.approve(request.id, operator="alice")

        # Try to approve again
        success = self.gate.approve(request.id, operator="bob")
        self.assertFalse(success)


class TestAlertManager(unittest.TestCase):
    """Test alert manager."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.alert_dir = Path(self.temp_dir) / "alerts"
        self.manager = AlertManager(str(self.alert_dir))

    def test_alert_creates_file(self):
        """Test that alerts create files."""
        self.manager.alert(
            AlertLevel.WARNING,
            "Test warning",
            {"value": 42},
        )

        # Verify file created
        warning_dir = self.alert_dir / "warning"
        self.assertTrue(warning_dir.exists())
        files = list(warning_dir.glob("*.json"))
        self.assertEqual(len(files), 1)

        # Verify content
        with files[0].open("r") as f:
            data = json.load(f)
        self.assertEqual(data["level"], "warning")
        self.assertEqual(data["message"], "Test warning")
        self.assertEqual(data["context"]["value"], 42)

    def test_alert_levels(self):
        """Test different alert levels."""
        self.manager.alert(AlertLevel.INFO, "Info message", {})
        self.manager.alert(AlertLevel.WARNING, "Warning message", {})
        self.manager.alert(AlertLevel.ERROR, "Error message", {})
        self.manager.alert(AlertLevel.CRITICAL, "Critical message", {})

        # Verify files in different directories
        self.assertEqual(len(list((self.alert_dir / "info").glob("*.json"))), 1)
        self.assertEqual(len(list((self.alert_dir / "warning").glob("*.json"))), 1)
        self.assertEqual(len(list((self.alert_dir / "error").glob("*.json"))), 1)
        self.assertEqual(len(list((self.alert_dir / "critical").glob("*.json"))), 1)


class TestHealthMonitor(unittest.TestCase):
    """Test health monitoring."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manifest_path = Path(self.temp_dir) / "manifest.json"
        self.alert_dir = Path(self.temp_dir) / "alerts"
        self.alert_manager = AlertManager(str(self.alert_dir))
        self.monitor = HealthMonitor(
            str(self.manifest_path),
            self.alert_manager,
            staleness_threshold_hours=24,
        )

    def test_missing_manifest(self):
        """Test health check with missing manifest."""
        report = self.monitor.check_health()
        self.assertFalse(report["healthy"])
        self.assertEqual(len(report["issues"]), 1)
        self.assertEqual(report["issues"][0]["type"], "missing_manifest")

    def test_stale_data(self):
        """Test health check with stale data."""
        # Create manifest with old timestamp
        old_time = datetime.now(timezone.utc) - timedelta(hours=30)
        manifest = {
            "last_update": old_time.isoformat(),
            "processed_symbols": ["AAPL"],
        }
        with self.manifest_path.open("w") as f:
            json.dump(manifest, f)

        report = self.monitor.check_health()
        self.assertFalse(report["healthy"])
        self.assertEqual(len(report["issues"]), 1)
        self.assertEqual(report["issues"][0]["type"], "data_staleness")
        self.assertIn("30", report["issues"][0]["message"])

    def test_fresh_data(self):
        """Test health check with fresh data."""
        # Create manifest with recent timestamp
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
        manifest = {
            "last_update": recent_time.isoformat(),
            "processed_symbols": ["AAPL"],
        }
        with self.manifest_path.open("w") as f:
            json.dump(manifest, f)

        report = self.monitor.check_health()
        self.assertTrue(report["healthy"])
        self.assertEqual(len(report["issues"]), 0)


class TestSupervisionConfig(unittest.TestCase):
    """Test supervision configuration."""

    def test_defaults(self):
        """Test default configuration."""
        config = SupervisionConfig()
        self.assertFalse(config.auto_approve_training)
        self.assertFalse(config.auto_approve_promotion)
        self.assertFalse(config.auto_approve_risk_changes)
        self.assertEqual(config.alert_dir, "state/alerts")
        self.assertEqual(config.data_staleness_hours, 24)
        self.assertEqual(config.notification_webhooks, {})

    def test_custom_config(self):
        """Test custom configuration."""
        config = SupervisionConfig(
            auto_approve_training=True,
            auto_approve_promotion=True,
            schedule_interval_minutes=60,
            data_staleness_hours=2,
            notification_webhooks={"slack": "https://hooks.slack.com/test"},
        )
        self.assertTrue(config.auto_approve_training)
        self.assertTrue(config.auto_approve_promotion)
        self.assertEqual(config.schedule_interval_minutes, 60)
        self.assertEqual(config.data_staleness_hours, 2)
        self.assertEqual(config.notification_webhooks["slack"], "https://hooks.slack.com/test")


if __name__ == "__main__":
    unittest.main()
