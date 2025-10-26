"""
Autonomous orchestration layer for ingestion → training → calibration.

`AutoPilot` stitches together the deterministic primitives provided by the
codebase so that a single call to `run_once()` can ingest fresh data, retrain
models, backtest, and derive updated risk thresholds.  Operators can schedule
the autopilot via cron or any external task runner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import Sequence

from .acquisition import AcquisitionReport, DataAcquisitionConfig, DataAcquisitionService
from .agent import AssetClassPolicy, ObjectiveThresholds
from .calibration import CalibrationSummary, calibrate_objectives
from .config import (
    BacktestConfig,
    DataSource,
    EngineConfig,
)
from .engine import BacktestResult, BacktestRunner
from .audit import AuditConfig, AuditLogger, StateStore
from .ingestion import DataIngestionConfig, DataIngestionService, IngestionReport
from .logging import configure_logger
from .promotion import ModelPromotionService, PromotionConfig, PromotionDecision
from .ml.pipeline import TrainingResult, train_model


@dataclass(frozen=True)
class AutoTrainingConfig:
    lookback: int = 30
    horizon: int = 1
    learning_rate: float = 0.01
    epochs: int = 200
    model_path: str = "models/autopilot_model.json"


@dataclass(frozen=True)
class AutoCalibrationConfig:
    safety_margin: float = 0.15
    output_path: str = "state/calibrated_thresholds.json"


@dataclass(frozen=True)
class PipelineConfig:
    """
    Aggregate configuration for the autopilot loop.

    Attributes:
        symbols: Universe of symbols to ingest, train, and backtest.
        ingestion: Ingestion pipeline configuration (optional when acquisition is provided).
        acquisition: Full data acquisition pipeline configuration.
        training: Training parameters for the ML strategy refresh.
        calibration: Threshold calibration parameters.
        engine: Base engine configuration used for backtesting.
        asset_policies: Optional per-asset-class risk overrides.
        state_path: JSON file capturing the outcome of the most recent run.
        promotion: Model promotion configuration (optional).
        audit: Audit and state store configuration (optional).
    """

    symbols: Sequence[str]
    ingestion: DataIngestionConfig | None = None
    acquisition: DataAcquisitionConfig | None = None
    training: AutoTrainingConfig = field(default_factory=AutoTrainingConfig)
    calibration: AutoCalibrationConfig = field(default_factory=AutoCalibrationConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    asset_policies: dict[str, AssetClassPolicy] = field(default_factory=dict)
    bar_interval: timedelta = field(default_factory=lambda: timedelta(minutes=1))
    state_path: str = "state/autopilot_state.json"
    promotion: PromotionConfig | None = None
    audit: AuditConfig | None = None


@dataclass(frozen=True)
class AutoPilotReport:
    acquisition: AcquisitionReport | None
    ingestion: IngestionReport
    training: TrainingResult | None
    calibration: CalibrationSummary | None
    backtest: BacktestResult | None
    thresholds: ObjectiveThresholds | None
    promotion: PromotionDecision | None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "acquisition": None,
            "ingestion": {
                "processed_symbols": self.ingestion.processed_symbols,
                "bars_added": self.ingestion.bars_added,
                "manifest_path": self.ingestion.manifest_path,
            },
            "training": None,
            "calibration": None,
            "thresholds": None,
            "backtest": None,
        }
        if self.acquisition:
            payload["acquisition"] = {
                "fetched_files": len(self.acquisition.fetched),
                "validations": len(self.acquisition.validations),
                "bars_added": self.acquisition.ingestion.bars_added,
            }
        if self.training:
            payload["training"] = {
                "model_path": self.training.model_path,
                "train_accuracy": self.training.train_accuracy,
                "test_accuracy": self.training.test_accuracy,
                "samples": self.training.samples,
            }
        if self.backtest:
            payload["backtest"] = {
                "trades": len(self.backtest.trades),
                "total_return": float(self.backtest.total_return),
                "win_rate": self.backtest.win_rate,
                "max_drawdown": float(self.backtest.max_drawdown),
                "metrics": self.backtest.metrics,
            }
        if self.calibration:
            payload["calibration"] = self.calibration.to_dict()
        if self.thresholds:
            payload["thresholds"] = {
                "min_sharpe": self.thresholds.min_sharpe,
                "max_drawdown": self.thresholds.max_drawdown,
                "min_win_rate": self.thresholds.min_win_rate,
                "min_trades": self.thresholds.min_trades,
                "max_equity_pullback_pct": self.thresholds.max_equity_pullback_pct,
                "max_position_fraction_cap": self.thresholds.max_position_fraction_cap,
                "max_daily_loss_pct": self.thresholds.max_daily_loss_pct,
                "max_weekly_loss_pct": self.thresholds.max_weekly_loss_pct,
            }
        if self.promotion:
            payload["promotion"] = {
                "status": self.promotion.status,
                "approved": self.promotion.approved,
                "model_id": self.promotion.model_id,
                "reason": self.promotion.reason,
                "report_path": self.promotion.report_path,
            }
        return payload


class AutoPilot:
    """
    Compose ingestion, training, backtesting, and calibration into a single action.

    A typical deployment would run `AutoPilot.run_once()` on a schedule (cron,
    Airflow, etc.).  The method is safe to re-run; if no new data is ingested the
    training and calibration steps are skipped.
    """

    def __init__(self, config: PipelineConfig):
        if not config.symbols:
            raise ValueError("PipelineConfig.symbols must contain at least one symbol.")
        self.config = config
        self.logger = configure_logger("AutoPilot", structured=True)
        self.acquisition_service = DataAcquisitionService(config.acquisition) if config.acquisition else None
        self.ingestion_service = DataIngestionService(config.ingestion) if config.ingestion else None
        if self.acquisition_service is None and self.ingestion_service is None:
            raise ValueError("PipelineConfig requires either acquisition or ingestion configuration.")
        self.promotion_service = ModelPromotionService(config.promotion) if config.promotion else None
        if config.audit:
            self.audit_logger = AuditLogger(config.audit)
            self.state_store = StateStore(config.audit.state_root)
        else:
            self.audit_logger = None
            self.state_store = None

    def run_once(self) -> AutoPilotReport:
        acquisition_report: AcquisitionReport | None = None
        if self.acquisition_service:
            acquisition_report = self.acquisition_service.run()
            ingestion_report = acquisition_report.ingestion
            self._audit(
                "data_acquisition",
                {
                    "fetched_files": len(acquisition_report.fetched),
                    "validations": len(acquisition_report.validations),
                    "bars_added": acquisition_report.ingestion.bars_added,
                },
            )
        else:
            ingestion_report = self.ingestion_service.ingest()
            self._audit(
                "data_ingestion",
                {
                    "processed_symbols": ingestion_report.processed_symbols,
                    "bars_added": ingestion_report.bars_added,
                },
            )
        if ingestion_report.bars_added == 0:
            report = AutoPilotReport(
                acquisition=acquisition_report,
                ingestion=ingestion_report,
                training=None,
                calibration=None,
                backtest=None,
                thresholds=None,
                promotion=None,
            )
            self._store_state(report)
            return report

        training_result = self._run_training()
        backtest_result = self._run_backtest()
        calibration_summary = calibrate_objectives([backtest_result], safety_margin=self.config.calibration.safety_margin)
        thresholds = calibration_summary.thresholds
        self._store_thresholds(calibration_summary)
        promotion_decision = self._run_promotion(training_result, backtest_result, calibration_summary)

        report = AutoPilotReport(
            acquisition=acquisition_report,
            ingestion=ingestion_report,
            training=training_result,
            calibration=calibration_summary,
            backtest=backtest_result,
            thresholds=thresholds,
            promotion=promotion_decision,
        )
        self._store_state(report)
        return report

    # ------------------------------------------------------------------
    def _run_training(self) -> TrainingResult:
        build = self.config.training
        result = train_model(
            data_dir=self._curated_dir(),
            symbols=self.config.symbols,
            lookback=build.lookback,
            horizon=build.horizon,
            learning_rate=build.learning_rate,
            epochs=build.epochs,
            model_path=build.model_path,
            quality=self.config.engine.data_quality,
            bar_interval=self.config.bar_interval,
        )
        self.logger.info(
            "training_completed",
            extra={
                "model_path": result.model_path,
                "train_accuracy": result.train_accuracy,
                "test_accuracy": result.test_accuracy,
                "samples": result.samples,
            },
        )
        self._audit(
            "model_training",
            {
                "train_accuracy": result.train_accuracy,
                "test_accuracy": result.test_accuracy,
                "samples": result.samples,
            },
            artefacts={"model_path": result.model_path},
        )
        return result

    def _run_backtest(self) -> BacktestResult:
        data_source = DataSource(
            path=self._curated_dir(),
            symbols=list(self.config.symbols),
            warmup_bars=max(120, self.config.training.lookback),
            enforce_trading_hours=False,
            bar_interval=self.config.bar_interval,
            timezone=timezone.utc,
        )
        backtest_config = BacktestConfig(
            data=data_source,
            engine=self.config.engine,
        )
        result = BacktestRunner(backtest_config).run()
        self.logger.info(
            "backtest_completed",
            extra={
                "total_return": float(result.total_return),
                "max_drawdown": float(result.max_drawdown),
                "win_rate": result.win_rate,
            },
        )
        self._audit(
            "backtest",
            {
                "total_return": float(result.total_return),
                "max_drawdown": float(result.max_drawdown),
                "win_rate": result.win_rate,
            },
        )
        return result

    def _store_thresholds(self, summary: CalibrationSummary) -> None:
        output = Path(self.config.calibration.output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            json.dump(summary.to_dict(), handle, indent=2)
        self.logger.info("thresholds_updated", extra={"path": str(output)})
        self._audit(
            "calibration",
            {
                "min_sharpe": summary.thresholds.min_sharpe,
                "max_drawdown": summary.thresholds.max_drawdown,
                "min_trades": summary.thresholds.min_trades,
            },
            artefacts={"thresholds_path": str(output)},
        )

    def _store_state(self, report: AutoPilotReport) -> None:
        path = Path(self.config.state_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = report.to_dict()
        if self.config.asset_policies:
            payload["asset_policies"] = {
                key: {
                    "sec_type": policy.sec_type,
                    "exchange": policy.exchange,
                    "currency": policy.currency,
                    "multiplier": policy.multiplier,
                    "max_position_fraction": policy.max_position_fraction,
                    "per_symbol_cap": policy.per_symbol_cap,
                }
                for key, policy in self.config.asset_policies.items()
            }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        self.logger.info("autopilot_state_written", extra={"path": str(path)})
        if self.state_store:
            self.state_store.write("autopilot", "run", payload, suffix=".json")
        self._audit("autopilot_state", {"path": str(path)}, artefacts={"state_path": str(path)})

    def _run_promotion(
        self,
        training: TrainingResult,
        backtest: BacktestResult,
        calibration: CalibrationSummary,
    ) -> PromotionDecision | None:
        if not self.promotion_service:
            return None
        decision = self.promotion_service.promote(training, backtest, calibration, operator="autopilot")
        self._audit(
            "model_promotion",
            {
                "status": decision.status,
                "approved": decision.approved,
                "reason": decision.reason,
            },
            artefacts={"model_id": decision.model_id or "pending"},
        )
        return decision

    def _ingestion_config(self) -> DataIngestionConfig:
        if self.config.ingestion:
            return self.config.ingestion
        if self.config.acquisition:
            return self.config.acquisition.ingestion
        raise ValueError("No ingestion configuration available.")

    def _curated_dir(self) -> str:
        return self._ingestion_config().curated_dir

    def _audit(self, action: str, details: dict[str, object], artefacts: dict[str, str] | None = None) -> None:
        if not self.audit_logger:
            return
        self.audit_logger.append(
            action,
            actor="autopilot",
            details=details,
            artefacts=artefacts or {},
        )
