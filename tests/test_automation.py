import csv
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from aistock.acquisition import DataAcquisitionConfig, FileSystemSourceConfig
from aistock.automation import AutoCalibrationConfig, AutoPilot, AutoTrainingConfig, PipelineConfig
from aistock.audit import AuditConfig
from aistock.config import DataQualityConfig, EngineConfig, RiskLimits, StrategyConfig
from aistock.ingestion import DataIngestionConfig
from aistock.promotion import PromotionConfig, PromotionPolicy
from aistock.agent import AssetClassPolicy


def _write_series(path: str, start_price: float = 100.0, bars: int = 120) -> None:
    ts = datetime(2022, 1, 3, 14, 30, tzinfo=timezone.utc)
    price = start_price
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for idx in range(bars):
            timestamp = ts + timedelta(days=idx)
            open_price = price
            high = price * 1.01
            low = price * 0.99
            close = price * 1.001
            writer.writerow(
                [
                    timestamp.isoformat(),
                    f"{open_price:.4f}",
                    f"{high:.4f}",
                    f"{low:.4f}",
                    f"{close:.4f}",
                    "150000",
                ]
            )
            price = close


def test_autopilot_runs_full_cycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        staging = os.path.join(tmpdir, "staging")
        curated = os.path.join(tmpdir, "curated")
        state_dir = os.path.join(tmpdir, "state")
        os.makedirs(staging, exist_ok=True)
        os.makedirs(curated, exist_ok=True)
        os.makedirs(state_dir, exist_ok=True)

        _write_series(os.path.join(staging, "AAA.csv"), 100.0, bars=160)

        ingestion_config = DataIngestionConfig(
            staging_dir=staging,
            curated_dir=curated,
            manifest_path=os.path.join(state_dir, "manifest.json"),
            archive_processed=os.path.join(state_dir, "archive"),
        )

        training_config = AutoTrainingConfig(
            lookback=30,
            horizon=1,
            epochs=50,
            model_path=os.path.join(state_dir, "model.json"),
        )

        calibration_config = AutoCalibrationConfig(
            safety_margin=0.2,
            output_path=os.path.join(state_dir, "thresholds.json"),
        )

        engine_config = EngineConfig(
            strategy=StrategyConfig(short_window=5, long_window=12),
            risk=RiskLimits(
                max_position_fraction=0.25,
                per_symbol_notional_cap=200_000,
                max_single_position_units=1_000_000,
            ),
            data_quality=DataQualityConfig(max_gap_bars=30),  # Daily bars, allow weekend/holiday gaps
        )

        policies = {
            "STK": AssetClassPolicy(sec_type="STK", max_position_fraction=0.2, per_symbol_cap=150_000),
        }

        pipeline_config = PipelineConfig(
            symbols=["AAA"],
            ingestion=ingestion_config,
            training=training_config,
            calibration=calibration_config,
            engine=engine_config,
            asset_policies=policies,
            bar_interval=timedelta(days=1),
            state_path=os.path.join(state_dir, "autopilot_state.json"),
        )

        autopilot = AutoPilot(pipeline_config)
        report = autopilot.run_once()

        assert report.acquisition is None
        assert report.ingestion.bars_added > 0
        assert report.training is not None
        assert report.calibration is not None
        assert report.backtest is not None
        assert report.thresholds is not None
        assert report.promotion is None

        with open(pipeline_config.state_path, encoding="utf-8") as handle:
            state = json.load(handle)
            assert "thresholds" in state

        with open(calibration_config.output_path, encoding="utf-8") as handle:
            thresholds = json.load(handle)
            assert thresholds["thresholds"]["min_sharpe"] >= 0.0


def test_autopilot_with_acquisition_and_promotion(tmp_path):
    provider = tmp_path / "provider"
    provider.mkdir()
    _write_series(str(provider / "AAA.csv"), 100.0, bars=160)

    staging = tmp_path / "staging"
    curated = tmp_path / "curated"
    raw = tmp_path / "raw"
    state_dir = tmp_path / "state"
    staging.mkdir()
    curated.mkdir()
    raw.mkdir()
    state_dir.mkdir()

    ingestion_config = DataIngestionConfig(
        staging_dir=str(staging),
        curated_dir=str(curated),
        manifest_path=str(state_dir / "manifest.json"),
        archive_processed=str(state_dir / "archive"),
    )

    acquisition_config = DataAcquisitionConfig(
        sources=[
            FileSystemSourceConfig(
                name="local",
                root=str(provider),
                symbols=["AAA"],
                bar_interval=timedelta(days=1),  # Daily bars in test data
            )
        ],
        raw_lake_dir=str(raw),
        ingestion=ingestion_config,
        metadata_log_path=str(state_dir / "acquisition_log.jsonl"),
    )

    training_config = AutoTrainingConfig(
        lookback=30,
        horizon=1,
        epochs=50,
        model_path=str(state_dir / "model.json"),
    )

    calibration_config = AutoCalibrationConfig(
        safety_margin=0.1,
        output_path=str(state_dir / "thresholds.json"),
    )

    engine_config = EngineConfig(
        strategy=StrategyConfig(short_window=5, long_window=12),
        risk=RiskLimits(
            max_position_fraction=0.25,
            per_symbol_notional_cap=200_000,
            max_single_position_units=1_000_000,
        ),
        data_quality=DataQualityConfig(max_gap_bars=30),  # Daily bars, allow weekend/holiday gaps
    )

    promotion_config = PromotionConfig(
        registry_dir=str(tmp_path / "models"),
        active_model_path=str(tmp_path / "models" / "active" / "model.json"),
        manifest_path=str(state_dir / "promotion_manifest.json"),
        policy=PromotionPolicy(
            min_train_accuracy=0.0,
            min_test_accuracy=0.0,
            min_sharpe=-10.0,
            max_drawdown=10.0,
            min_total_return=-10.0,
            min_trades=0,
        ),
    )

    audit_config = AuditConfig(
        log_path=str(state_dir / "audit.jsonl"),
        state_root=str(state_dir / "archive_runs"),
    )

    pipeline_config = PipelineConfig(
        symbols=["AAA"],
        acquisition=acquisition_config,
        training=training_config,
        calibration=calibration_config,
        engine=engine_config,
        bar_interval=timedelta(days=1),
        state_path=str(state_dir / "autopilot_state.json"),
        promotion=promotion_config,
        audit=audit_config,
    )

    autopilot = AutoPilot(pipeline_config)
    report = autopilot.run_once()

    assert report.acquisition is not None
    assert report.ingestion.bars_added > 0
    assert report.promotion is not None and report.promotion.approved
    assert os.path.exists(promotion_config.active_model_path)

    with open(audit_config.log_path, encoding="utf-8") as handle:
        entries = [line for line in handle if line.strip()]
    assert entries, "Audit log should capture events"

    archive_entries = list((state_dir / "archive_runs").glob("*/*"))
    assert archive_entries, "State store should capture versioned artefacts"
