import csv
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path

from aistock.acquisition import (
    DataAcquisitionConfig,
    DataAcquisitionService,
    DataValidator,
    FileSystemSourceConfig,
)
from aistock.config import DataQualityConfig
from aistock.ingestion import DataIngestionConfig


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with open(path, 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        writer.writerows(rows)


class DataAcquisitionPipelineTests(unittest.TestCase):
    """Integration tests for acquisition pipeline without pytest fixtures."""

    def test_acquisition_pipeline_fetches_validates_and_ingests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            provider_root = tmp_path / 'provider'
            provider_root.mkdir()
            rows = [
                ['2024-01-01T14:30:00+00:00', '100', '101', '99', '100.5', '10000'],
                ['2024-01-02T14:30:00+00:00', '101', '102', '100', '101.5', '11000'],
                ['2024-01-03T14:30:00+00:00', '102', '103', '101', '102.5', '12000'],
            ]
            _write_csv(provider_root / 'AAPL.csv', rows)

            staging = tmp_path / 'staging'
            curated = tmp_path / 'curated'
            raw = tmp_path / 'raw'
            state = tmp_path / 'state'

            ingestion_config = DataIngestionConfig(
                staging_dir=str(staging),
                curated_dir=str(curated),
                manifest_path=str(state / 'manifest.json'),
            )
            acquisition_config = DataAcquisitionConfig(
                sources=[
                    FileSystemSourceConfig(
                        name='local',
                        root=str(provider_root),
                        symbols=['AAPL'],
                        timezone=timezone.utc,
                        bar_interval=timedelta(days=1),  # Daily bars in test data
                    )
                ],
                raw_lake_dir=str(raw),
                ingestion=ingestion_config,
                metadata_log_path=str(state / 'acquisition.jsonl'),
                quality=DataQualityConfig(max_gap_bars=10),
            )

            service = DataAcquisitionService(acquisition_config)
            report = service.run()

            self.assertEqual(report.ingestion.bars_added, len(rows))
            self.assertEqual(report.fetched[0].symbol, 'AAPL')
            self.assertEqual(report.validations[0].rows, len(rows))
            self.assertTrue((curated / 'AAPL.csv').exists())

            raw_files = list((raw / 'local' / 'AAPL').glob('*.csv'))
            self.assertTrue(raw_files, 'raw lake should contain snapshot copies')

            with open(state / 'acquisition.jsonl', encoding='utf-8') as handle:
                log_lines = handle.readlines()
            self.assertTrue(any('"event": "fetch"' in line for line in log_lines))
            self.assertTrue(any('"event": "ingestion"' in line for line in log_lines))


class PriceAnomalyDetectionTests(unittest.TestCase):
    """P0 Fix: Tests for price anomaly detection."""

    def test_detects_invalid_negative_prices(self):
        """Test that negative prices are rejected."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rows = [
                ['2024-01-01T14:30:00+00:00', '100', '101', '99', '100.5', '10000'],
                ['2024-01-02T14:30:00+00:00', '-10', '102', '100', '101.5', '11000'],  # Negative price
            ]
            _write_csv(tmp / 'TEST.csv', rows)

            validator = DataValidator(DataQualityConfig())
            with self.assertRaises(ValueError) as ctx:
                validator.validate(tmp / 'TEST.csv', 'TEST', timezone.utc, timedelta(days=1))
            self.assertIn('invalid price', str(ctx.exception).lower())

    def test_detects_zero_prices(self):
        """Test that zero prices are rejected."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rows = [
                ['2024-01-01T14:30:00+00:00', '100', '101', '99', '100.5', '10000'],
                ['2024-01-02T14:30:00+00:00', '0', '102', '100', '101.5', '11000'],  # Zero price
            ]
            _write_csv(tmp / 'TEST.csv', rows)

            validator = DataValidator(DataQualityConfig())
            with self.assertRaises(ValueError) as ctx:
                validator.validate(tmp / 'TEST.csv', 'TEST', timezone.utc, timedelta(days=1))
            self.assertIn('invalid price', str(ctx.exception).lower())

    def test_warns_on_extreme_price_jump(self):
        """Test that extreme price jumps generate warnings."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rows = [
                ['2024-01-01T14:30:00+00:00', '100', '101', '99', '100', '10000'],
                ['2024-01-02T14:30:00+00:00', '200', '201', '199', '200', '11000'],  # 100% jump
            ]
            _write_csv(tmp / 'TEST.csv', rows)

            validator = DataValidator(DataQualityConfig())
            report = validator.validate(tmp / 'TEST.csv', 'TEST', timezone.utc, timedelta(days=1))

            # Should have warning about extreme jump
            self.assertTrue(any('extreme price jump' in w.lower() for w in report.warnings))

    def test_warns_on_suspiciously_low_price(self):
        """Test that very low prices generate warnings."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rows = [
                ['2024-01-01T14:30:00+00:00', '100', '101', '99', '100', '10000'],
                ['2024-01-02T14:30:00+00:00', '0.001', '0.002', '0.0009', '0.001', '11000'],  # Very low
            ]
            _write_csv(tmp / 'TEST.csv', rows)

            validator = DataValidator(DataQualityConfig())
            report = validator.validate(tmp / 'TEST.csv', 'TEST', timezone.utc, timedelta(days=1))

            # Should have warning about suspiciously low price
            self.assertTrue(any('suspiciously low' in w.lower() for w in report.warnings))

    def test_warns_on_suspiciously_high_price(self):
        """Test that very high prices generate warnings."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rows = [
                ['2024-01-01T14:30:00+00:00', '100', '101', '99', '100', '10000'],
                ['2024-01-02T14:30:00+00:00', '150000', '150001', '149999', '150000', '11000'],  # Very high
            ]
            _write_csv(tmp / 'TEST.csv', rows)

            validator = DataValidator(DataQualityConfig())
            report = validator.validate(tmp / 'TEST.csv', 'TEST', timezone.utc, timedelta(days=1))

            # Should have warning about suspiciously high price
            self.assertTrue(any('suspiciously high' in w.lower() for w in report.warnings))

    def test_normal_prices_pass_validation(self):
        """Test that normal price movements pass without warnings."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rows = [
                ['2024-01-01T14:30:00+00:00', '100', '101', '99', '100.5', '10000'],
                ['2024-01-02T14:30:00+00:00', '101', '103', '100', '102', '11000'],  # Normal 1.5% move
                ['2024-01-03T14:30:00+00:00', '102', '104', '101', '103', '12000'],
            ]
            _write_csv(tmp / 'TEST.csv', rows)

            validator = DataValidator(DataQualityConfig())
            report = validator.validate(tmp / 'TEST.csv', 'TEST', timezone.utc, timedelta(days=1))

            # Should have no price-related warnings
            price_warnings = [w for w in report.warnings if 'price' in w.lower() or 'jump' in w.lower()]
            self.assertEqual(len(price_warnings), 0)


if __name__ == '__main__':
    unittest.main()
