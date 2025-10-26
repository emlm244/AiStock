import csv
from datetime import timedelta, timezone

from aistock.acquisition import DataAcquisitionConfig, DataAcquisitionService, FileSystemSourceConfig
from aistock.config import DataQualityConfig
from aistock.ingestion import DataIngestionConfig


def _write_csv(path, rows):
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        writer.writerows(rows)


def test_acquisition_pipeline_fetches_validates_and_ingests(tmp_path):
    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    rows = [
        ["2024-01-01T14:30:00+00:00", "100", "101", "99", "100.5", "10000"],
        ["2024-01-02T14:30:00+00:00", "101", "102", "100", "101.5", "11000"],
        ["2024-01-03T14:30:00+00:00", "102", "103", "101", "102.5", "12000"],
    ]
    _write_csv(provider_root / "AAPL.csv", rows)

    staging = tmp_path / "staging"
    curated = tmp_path / "curated"
    raw = tmp_path / "raw"
    state = tmp_path / "state"

    ingestion_config = DataIngestionConfig(
        staging_dir=str(staging),
        curated_dir=str(curated),
        manifest_path=str(state / "manifest.json"),
    )
    acquisition_config = DataAcquisitionConfig(
        sources=[
            FileSystemSourceConfig(
                name="local",
                root=str(provider_root),
                symbols=["AAPL"],
                timezone=timezone.utc,
                bar_interval=timedelta(days=1),  # Daily bars in test data
            )
        ],
        raw_lake_dir=str(raw),
        ingestion=ingestion_config,
        metadata_log_path=str(state / "acquisition.jsonl"),
        quality=DataQualityConfig(max_gap_bars=10),
    )

    service = DataAcquisitionService(acquisition_config)
    report = service.run()

    assert report.ingestion.bars_added == len(rows)
    assert report.fetched[0].symbol == "AAPL"
    assert report.validations[0].rows == len(rows)
    assert (curated / "AAPL.csv").exists()

    raw_files = list((raw / "local" / "AAPL").glob("*.csv"))
    assert raw_files, "raw lake should contain snapshot copies"

    with open(state / "acquisition.jsonl", encoding="utf-8") as handle:
        log_lines = handle.readlines()
    assert any('"event": "fetch"' in line for line in log_lines)
    assert any('"event": "ingestion"' in line for line in log_lines)
