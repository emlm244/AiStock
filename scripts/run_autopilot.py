"""CLI entry point to execute the AIStock autopilot pipeline once."""

from __future__ import annotations

import argparse
import json
from dataclasses import fields
from datetime import timedelta
from pathlib import Path

from aistock import AutoPilot, PipelineConfig
from aistock.acquisition import DataAcquisitionConfig, FileSystemSourceConfig
from aistock.audit import AuditConfig
from aistock.automation import AutoCalibrationConfig, AutoTrainingConfig
from aistock.config import EngineConfig, RiskLimits, StrategyConfig
from aistock.ingestion import DataIngestionConfig
from aistock.promotion import PromotionConfig, PromotionPolicy


def _filter_kwargs(model, payload: dict) -> dict:
    valid = {field.name for field in fields(model)}
    return {key: value for key, value in payload.items() if key in valid}


def _build_ingestion_config(payload: dict) -> DataIngestionConfig:
    payload = dict(payload)
    payload.pop("timezone", None)  # Default to UTC inside the dataclass
    return DataIngestionConfig(**_filter_kwargs(DataIngestionConfig, payload))


def _build_acquisition_config(payload: dict) -> DataAcquisitionConfig:
    ingestion = _build_ingestion_config(payload["ingestion"])
    sources = []
    for source_payload in payload.get("sources", []):
        data = dict(source_payload)
        minutes = data.pop("bar_interval_minutes", None)
        kwargs = _filter_kwargs(FileSystemSourceConfig, data)
        if minutes is not None:
            kwargs["bar_interval"] = timedelta(minutes=float(minutes))
        sources.append(FileSystemSourceConfig(**kwargs))
    kwargs = _filter_kwargs(DataAcquisitionConfig, payload)
    kwargs["ingestion"] = ingestion
    kwargs["sources"] = sources
    return DataAcquisitionConfig(**kwargs)


def _build_promotion_config(payload: dict) -> PromotionConfig:
    policy_payload = payload.get("policy") or {}
    policy = PromotionPolicy(**_filter_kwargs(PromotionPolicy, policy_payload))
    kwargs = _filter_kwargs(PromotionConfig, payload)
    kwargs["policy"] = policy
    return PromotionConfig(**kwargs)


def _build_audit_config(payload: dict) -> AuditConfig:
    return AuditConfig(**_filter_kwargs(AuditConfig, payload))


def load_pipeline_config(path: Path) -> PipelineConfig:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    ingestion_payload = payload.get("ingestion")
    acquisition_payload = payload.get("acquisition")

    ingestion = _build_ingestion_config(ingestion_payload) if ingestion_payload else None
    acquisition = _build_acquisition_config(acquisition_payload) if acquisition_payload else None

    training = AutoTrainingConfig(**_filter_kwargs(AutoTrainingConfig, payload.get("training", {})))
    calibration = AutoCalibrationConfig(**_filter_kwargs(AutoCalibrationConfig, payload.get("calibration", {})))

    engine_payload = payload.get("engine", {})
    risk_payload = engine_payload.get("risk", {})
    strategy_payload = engine_payload.get("strategy", {})
    risk = RiskLimits(**_filter_kwargs(RiskLimits, risk_payload))
    strategy = StrategyConfig(**_filter_kwargs(StrategyConfig, strategy_payload))
    engine = EngineConfig(risk=risk, strategy=strategy)

    promotion_config = None
    if payload.get("promotion"):
        promotion_config = _build_promotion_config(payload["promotion"])

    audit_config = None
    if payload.get("audit"):
        audit_config = _build_audit_config(payload["audit"])

    config_kwargs = {
        "symbols": payload["symbols"],
        "ingestion": ingestion,
        "acquisition": acquisition,
        "training": training,
        "calibration": calibration,
        "engine": engine,
        "state_path": payload.get("state_path", "state/autopilot_state.json"),
        "bar_interval": timedelta(minutes=float(payload.get("bar_interval_minutes", 1))),
        "promotion": promotion_config,
        "audit": audit_config,
    }
    return PipelineConfig(**config_kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AIStock autopilot once")
    parser.add_argument("config", type=Path, help="Path to pipeline configuration JSON file")
    args = parser.parse_args()

    pipeline_config = load_pipeline_config(args.config)
    autopilot = AutoPilot(pipeline_config)
    report = autopilot.run_once()
    print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()
