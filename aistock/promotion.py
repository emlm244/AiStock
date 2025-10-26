"""
Model promotion pipeline for managing trained artefacts and live registry state.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .calibration import CalibrationSummary
from .engine import BacktestResult
from .logging import configure_logger
from .ml.pipeline import TrainingResult


@dataclass(frozen=True)
class PromotionPolicy:
    """
    Guardrails used to decide whether a candidate model is eligible for live promotion.
    """

    min_train_accuracy: float = 0.55
    min_test_accuracy: float = 0.53
    min_sharpe: float = 0.6
    max_drawdown: float = 0.18
    min_total_return: float = 0.02
    min_trades: int = 20


@dataclass
class PromotionConfig:
    """
    Storage layout and thresholds for model promotion.
    """

    registry_dir: str = "models"
    active_model_path: str = "models/active/model.json"
    manifest_path: str = "state/promotion_manifest.json"
    report_filename: str = "report.json"
    policy: PromotionPolicy = field(default_factory=PromotionPolicy)
    max_history: int | None = 50


@dataclass
class PromotionDecision:
    """Outcome of a promotion attempt."""

    status: str
    approved: bool
    model_id: str | None
    report_path: str | None
    reason: str | None
    metrics: dict[str, float]


class ModelPromotionService:
    """
    Evaluate trained models, persist artefacts, and manage the active registry.
    """

    def __init__(self, config: PromotionConfig):
        self.config = config
        self.registry_dir = Path(config.registry_dir).expanduser().resolve()
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.logger = configure_logger("ModelPromotion", structured=True)

    def promote(
        self,
        training: TrainingResult,
        backtest: BacktestResult,
        calibration: CalibrationSummary | None = None,
        operator: str | None = "autopilot",
    ) -> PromotionDecision:
        evaluation = self._evaluate(training, backtest)
        timestamp = datetime.now(timezone.utc)
        report_path: Path | None = None
        model_id: str | None = None

        if evaluation["approved"]:
            model_id = self._next_model_id(timestamp)
            report_path = self._persist_model(training, backtest, calibration, model_id, timestamp)
            self._activate_model(model_id)
            status = "approved"
            reason = None
            self.logger.info(
                "model_promoted",
                extra={
                    "model_id": model_id,
                    "report_path": str(report_path),
                    "sharpe": evaluation["metrics"]["sharpe"],
                    "drawdown": evaluation["metrics"]["max_drawdown"],
                    "test_accuracy": evaluation["metrics"]["test_accuracy"],
                },
            )
        else:
            status = "rejected"
            reason = evaluation["reason"]
            self.logger.warning(
                "model_rejected",
                extra={
                    "reason": reason,
                    "train_accuracy": evaluation["metrics"]["train_accuracy"],
                    "test_accuracy": evaluation["metrics"]["test_accuracy"],
                    "sharpe": evaluation["metrics"]["sharpe"],
                    "drawdown": evaluation["metrics"]["max_drawdown"],
                },
            )

        self._record_manifest_entry(
            {
                "timestamp": timestamp.isoformat(),
                "status": status,
                "model_id": model_id,
                "operator": operator,
                "reason": evaluation["reason"],
                "metrics": evaluation["metrics"],
                "report_path": str(report_path) if report_path else None,
            }
        )
        return PromotionDecision(
            status=status,
            approved=evaluation["approved"],
            model_id=model_id,
            report_path=str(report_path) if report_path else None,
            reason=evaluation["reason"],
            metrics=evaluation["metrics"],
        )

    def rollback(self, model_id: str | None = None, operator: str | None = "autopilot") -> str:
        """
        Roll back the active model to a previous approved version.

        Args:
            model_id: Optional specific model to activate. If omitted, the previous approved model is used.
            operator: Identifier for audit manifest.

        Returns:
            The model identifier that is now active.
        """
        manifest = self._load_manifest()
        approved = [entry for entry in manifest if entry.get("status") == "approved" and entry.get("model_id")]
        if not approved:
            raise ValueError("No approved models available for rollback.")

        if model_id:
            candidate = next((entry for entry in approved if entry["model_id"] == model_id), None)
            if candidate is None:
                raise ValueError(f"Model id {model_id} not found in approved registry.")
        else:
            if len(approved) < 2:
                raise ValueError("No previous approved model available for rollback.")
            candidate = approved[-2]
            model_id = candidate["model_id"]

        self._activate_model(model_id)
        timestamp = datetime.now(timezone.utc)
        self._record_manifest_entry(
            {
                "timestamp": timestamp.isoformat(),
                "status": "rollback",
                "model_id": model_id,
                "operator": operator,
                "reason": "rollback_requested",
                "metrics": candidate.get("metrics", {}),
                "report_path": candidate.get("report_path"),
            }
        )
        self.logger.info("model_rollback", extra={"model_id": model_id})
        return model_id

    # ------------------------------------------------------------------
    def _evaluate(self, training: TrainingResult, backtest: BacktestResult) -> dict[str, Any]:
        policy = self.config.policy
        metrics = {
            "train_accuracy": float(training.train_accuracy),
            "test_accuracy": float(training.test_accuracy),
            "samples": float(training.samples),
            "sharpe": float(backtest.metrics.get("sharpe", 0.0)),
            "sortino": float(backtest.metrics.get("sortino", 0.0)),
            "max_drawdown": float(backtest.max_drawdown),
            "total_return": float(backtest.total_return),
            "win_rate": float(backtest.win_rate),
            "trade_count": float(backtest.metrics.get("total_trades", len(backtest.trades))),
        }

        reason: str | None = None
        approved = True
        if metrics["train_accuracy"] < policy.min_train_accuracy:
            approved = False
            reason = f"train_accuracy_below_threshold({metrics['train_accuracy']:.3f} < {policy.min_train_accuracy:.3f})"
        elif metrics["test_accuracy"] < policy.min_test_accuracy:
            approved = False
            reason = f"test_accuracy_below_threshold({metrics['test_accuracy']:.3f} < {policy.min_test_accuracy:.3f})"
        elif metrics["trade_count"] < policy.min_trades:
            approved = False
            reason = f"insufficient_trades({metrics['trade_count']} < {policy.min_trades})"
        elif metrics["total_return"] < policy.min_total_return:
            approved = False
            reason = f"total_return_below_threshold({metrics['total_return']:.3f} < {policy.min_total_return:.3f})"
        elif metrics["sharpe"] < policy.min_sharpe:
            approved = False
            reason = f"sharpe_below_threshold({metrics['sharpe']:.3f} < {policy.min_sharpe:.3f})"
        elif metrics["max_drawdown"] > policy.max_drawdown:
            approved = False
            reason = f"drawdown_above_threshold({metrics['max_drawdown']:.3f} > {policy.max_drawdown:.3f})"

        metrics["approved"] = 1.0 if approved else 0.0
        return {
            "approved": approved,
            "reason": reason,
            "metrics": metrics,
        }

    def _persist_model(
        self,
        training: TrainingResult,
        backtest: BacktestResult,
        calibration: CalibrationSummary | None,
        model_id: str,
        timestamp: datetime,
    ) -> Path:
        target_dir = self.registry_dir / model_id
        target_dir.mkdir(parents=True, exist_ok=True)

        source_model = Path(training.model_path).expanduser().resolve()
        if not source_model.exists():
            raise FileNotFoundError(f"Trained model file does not exist: {source_model}")

        model_dest = target_dir / "model.json"
        shutil.copy2(source_model, model_dest)

        report_dest = target_dir / self.config.report_filename
        report_payload = self._build_report(training, backtest, calibration, model_id, timestamp)
        with report_dest.open("w", encoding="utf-8") as handle:
            json.dump(report_payload, handle, indent=2)
        return report_dest

    @staticmethod
    def _build_report(
        training: TrainingResult,
        backtest: BacktestResult,
        calibration: CalibrationSummary | None,
        model_id: str,
        timestamp: datetime,
    ) -> dict[str, Any]:
        return {
            "model_id": model_id,
            "timestamp": timestamp.isoformat(),
            "training": {
                "model_path": training.model_path,
                "train_accuracy": training.train_accuracy,
                "test_accuracy": training.test_accuracy,
                "samples": training.samples,
            },
            "backtest": {
                "total_return": float(backtest.total_return),
                "max_drawdown": float(backtest.max_drawdown),
                "win_rate": backtest.win_rate,
                "trade_count": backtest.metrics.get("total_trades", len(backtest.trades)),
                "metrics": backtest.metrics,
            },
            "calibration": calibration.to_dict() if calibration else None,
        }

    def _activate_model(self, model_id: str) -> None:
        model_path = self.registry_dir / model_id / "model.json"
        if not model_path.exists():
            raise FileNotFoundError(f"Model file missing for id {model_id}: {model_path}")
        active_path = Path(self.config.active_model_path).expanduser()
        active_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(model_path, active_path)

    @staticmethod
    def _next_model_id(timestamp: datetime) -> str:
        return timestamp.strftime("model_%Y%m%dT%H%M%S")

    def _load_manifest(self) -> list[dict[str, Any]]:
        path = Path(self.config.manifest_path).expanduser()
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return data
        return []

    def _record_manifest_entry(self, entry: dict[str, Any]) -> None:
        path = Path(self.config.manifest_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        history = self._load_manifest()
        history.append(entry)
        if self.config.max_history is not None and len(history) > self.config.max_history:
            history = history[-self.config.max_history :]
        with path.open("w", encoding="utf-8") as handle:
            json.dump(history, handle, indent=2)


__all__ = [
    "ModelPromotionService",
    "PromotionConfig",
    "PromotionDecision",
    "PromotionPolicy",
]
