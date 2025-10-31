import csv
import tempfile
from pathlib import Path

from aistock.ingestion import DataIngestionConfig, DataIngestionService


def _write_csv(path: Path | str, rows: list[list[str]]) -> None:
    with open(path, 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        writer.writerows(rows)


def test_ingestion_appends_new_bars_and_updates_manifest():
    with tempfile.TemporaryDirectory() as tmpdir:
        staging = f'{tmpdir}/staging'
        curated = f'{tmpdir}/curated'
        state_dir = f'{tmpdir}/state'

        import os

        os.makedirs(staging, exist_ok=True)
        os.makedirs(curated, exist_ok=True)
        os.makedirs(state_dir, exist_ok=True)

        config = DataIngestionConfig(
            staging_dir=staging,
            curated_dir=curated,
            manifest_path=f'{state_dir}/manifest.json',
        )
        service = DataIngestionService(config)

        # First ingestion: ingest initial 2 bars
        base_rows = [
            ['2024-01-01T14:30:00+00:00', '100', '100.5', '99.5', '100.2', '10000'],
            ['2024-01-02T14:30:00+00:00', '101', '101.5', '100.5', '101.2', '11000'],
        ]
        _write_csv(f'{staging}/AAPL.csv', base_rows)
        first_report = service.ingest()
        assert first_report.bars_added == 2

        # Second ingestion: add 1 new bar
        new_rows = base_rows + [
            ['2024-01-03T14:30:00+00:00', '102', '102.5', '101.5', '102.2', '12000'],
        ]
        _write_csv(f'{staging}/AAPL.csv', new_rows)

        report = service.ingest()

        assert report.bars_added == 1
        assert report.processed_symbols == ['AAPL']

        with open(f'{curated}/AAPL.csv', newline='') as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            assert len(rows) == 3
            assert rows[-1]['timestamp'] == '2024-01-03T14:30:00+00:00'

        with open(report.manifest_path, encoding='utf-8') as handle:
            import json

            manifest = json.load(handle)
            assert manifest['AAPL'].startswith('2024-01-03T14:30:00')
