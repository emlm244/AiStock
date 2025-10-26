"""
Data acquisition pipeline that fetches raw datasets, validates them, and
hands staged files to the ingestion service.

The goal is to formalise the ``source → raw lake → validator → curated`` flow
so scheduled jobs can operate deterministically while preserving the metadata
needed for audits.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from .config import DataQualityConfig
from .data import Bar, load_csv_file
from .ingestion import DataIngestionConfig, DataIngestionService, IngestionReport
from .logging import configure_logger


@dataclass(frozen=True)
class FileSystemSourceConfig:
    """
    Configuration describing a provider that exports CSV files locally.

    Attributes:
        name: Human readable source identifier (e.g. ``"polygon"``).
        root: Directory containing exported CSV files.
        symbols: Symbols fetched from this source.
        timezone: Timezone applied to naive timestamps when parsing.
        bar_interval: Expected sampling cadence; used for gap detection.
        filename_template: Naming pattern for files inside ``root``.
    """

    name: str
    root: str
    symbols: Sequence[str]
    timezone: timezone = timezone.utc
    bar_interval: timedelta = timedelta(minutes=1)
    filename_template: str = "{symbol}.csv"


@dataclass
class FetchedArtifact:
    """Metadata describing a file copied from a data source."""

    source: str
    symbol: str
    raw_path: str
    staging_path: str
    bytes_fetched: int
    checksum: str
    fetched_at: datetime


@dataclass
class ValidationReport:
    """Quality checks performed on a staged CSV."""

    source: str
    symbol: str
    rows: int
    start_timestamp: datetime
    end_timestamp: datetime
    gaps_detected: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class AcquisitionReport:
    """Aggregate outcome of a full acquisition run."""

    fetched: list[FetchedArtifact]
    validations: list[ValidationReport]
    ingestion: IngestionReport


@dataclass
class DataAcquisitionConfig:
    """
    Parameters controlling the acquisition pipeline.

    Attributes:
        sources: List of source configurations to poll.
        raw_lake_dir: Append-only directory used for raw snapshots.
        ingestion: Ingestion configuration used to merge into curated history.
        metadata_log_path: JSONL log capturing fetch + validation metadata.
        quality: Data quality thresholds reused by validators.
    """

    sources: Sequence[FileSystemSourceConfig]
    raw_lake_dir: str
    ingestion: DataIngestionConfig
    metadata_log_path: str = "state/acquisition_log.jsonl"
    quality: DataQualityConfig = field(default_factory=DataQualityConfig)


class MetadataLogger:
    """Append-only JSONL logger for acquisition artefacts."""

    def __init__(self, path: str):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, payload: dict[str, object]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str))
            handle.write("\n")


class DataValidator:
    """Run quality checks on staged CSV files."""

    def __init__(self, quality: DataQualityConfig):
        self.quality = quality
        self.logger = configure_logger("DataValidator", structured=True)

    def validate(
        self,
        path: Path,
        symbol: str,
        tz: timezone,
        bar_interval: timedelta,
    ) -> ValidationReport:
        bars = load_csv_file(path, symbol, tz)
        if not bars:
            raise ValueError(f"{path}: no rows loaded for {symbol}")
        gaps, gap_warnings = self._inspect_gaps(bars, bar_interval)
        warnings: list[str] = gap_warnings
        self._enforce_volume_rules(bars)
        return ValidationReport(
            source="",
            symbol=symbol,
            rows=len(bars),
            start_timestamp=bars[0].timestamp,
            end_timestamp=bars[-1].timestamp,
            gaps_detected=gaps,
            warnings=warnings,
        )

    def _inspect_gaps(self, bars: Sequence[Bar], bar_interval: timedelta) -> tuple[int, list[str]]:
        if bar_interval <= timedelta(0):
            return 0, []
        expected_seconds = bar_interval.total_seconds()
        if expected_seconds <= 0:
            return 0, []
        gaps_detected = 0
        warnings: list[str] = []
        previous = bars[0].timestamp
        for bar in bars[1:]:
            if bar.timestamp <= previous:
                raise ValueError(f"{bar.symbol}: non-monotonic timestamp at {bar.timestamp.isoformat()}")
            delta_seconds = (bar.timestamp - previous).total_seconds()
            multiples = delta_seconds / expected_seconds
            if multiples > 1.01:  # Allow tiny drift
                gaps_detected += int(max(1, round(multiples - 1)))
                if self.quality.max_gap_bars >= 0 and multiples > (self.quality.max_gap_bars + 1):
                    raise ValueError(
                        f"{bar.symbol}: gap of {bar.timestamp - previous} exceeds limit of {self.quality.max_gap_bars} bars"
                    )
                warnings.append(
                    f"{bar.symbol}: gap of {(bar.timestamp - previous)} detected at {bar.timestamp.isoformat()}"
                )
            previous = bar.timestamp
        return gaps_detected, warnings

    def _enforce_volume_rules(self, bars: Sequence[Bar]) -> None:
        if self.quality.zero_volume_allowed:
            return
        for bar in bars:
            if bar.volume == 0:
                raise ValueError(f"{bar.symbol}: zero volume detected at {bar.timestamp.isoformat()}")


class FileSystemFetcher:
    """Copy CSV files from a local directory into the raw lake and staging area."""

    def __init__(
        self,
        source: FileSystemSourceConfig,
        raw_root: Path,
        staging_root: Path,
    ):
        self.source = source
        self.raw_root = Path(raw_root).expanduser().resolve() / source.name
        self.staging_root = Path(staging_root).expanduser().resolve()
        self.logger = configure_logger(f"Fetcher[{source.name}]", structured=True)

    def fetch(self, since: datetime | None = None) -> list[FetchedArtifact]:
        results: list[FetchedArtifact] = []
        for symbol in self.source.symbols:
            template = self.source.filename_template.format(symbol=symbol)
            origin = Path(self.source.root).expanduser().resolve() / template
            if not origin.exists():
                self.logger.warning(
                    "source_file_missing",
                    extra={"symbol": symbol, "path": str(origin)},
                )
                continue
            data = origin.read_bytes()
            checksum = hashlib.sha256(data).hexdigest()
            fetched_at = datetime.now(timezone.utc)

            raw_dir = self.raw_root / symbol.upper()
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{fetched_at.strftime('%Y%m%d%H%M%S')}.csv"
            raw_path.write_bytes(data)

            staging_path = self.staging_root / f"{symbol.upper()}.csv"
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            staging_path.write_bytes(data)

            artifact = FetchedArtifact(
                source=self.source.name,
                symbol=symbol.upper(),
                raw_path=str(raw_path),
                staging_path=str(staging_path),
                bytes_fetched=len(data),
                checksum=checksum,
                fetched_at=fetched_at,
            )
            results.append(artifact)
            self.logger.info(
                "fetch_complete",
                extra={
                    "symbol": artifact.symbol,
                    "bytes": artifact.bytes_fetched,
                    "raw_path": artifact.raw_path,
                    "staging_path": artifact.staging_path,
                },
            )
        return results


class DataAcquisitionService:
    """
    Compose fetchers, validators, and ingestion into a single deterministic run.
    """

    def __init__(self, config: DataAcquisitionConfig):
        if not config.sources:
            raise ValueError("DataAcquisitionConfig.sources must contain at least one source.")
        self.config = config
        self.logger = configure_logger("DataAcquisition", structured=True)
        self.metadata_logger = MetadataLogger(config.metadata_log_path)
        self.validator = DataValidator(config.quality)
        self.ingestion_service = DataIngestionService(config.ingestion)

    def run(self, since: datetime | None = None) -> AcquisitionReport:
        fetched: list[FetchedArtifact] = []
        validations: list[ValidationReport] = []
        raw_root = Path(self.config.raw_lake_dir).expanduser().resolve()
        staging_root = Path(self.config.ingestion.staging_dir).expanduser().resolve()
        raw_root.mkdir(parents=True, exist_ok=True)
        staging_root.mkdir(parents=True, exist_ok=True)

        for source in self.config.sources:
            fetcher = FileSystemFetcher(source, raw_root, staging_root)
            artifacts = fetcher.fetch(since=since)
            for artifact in artifacts:
                self.metadata_logger.append(
                    {
                        "event": "fetch",
                        "source": artifact.source,
                        "symbol": artifact.symbol,
                        "bytes": artifact.bytes_fetched,
                        "checksum": artifact.checksum,
                        "raw_path": artifact.raw_path,
                        "staging_path": artifact.staging_path,
                    }
                )
            fetched.extend(artifacts)
            for artifact in artifacts:
                report = self.validator.validate(
                    Path(artifact.staging_path),
                    symbol=artifact.symbol,
                    tz=source.timezone,
                    bar_interval=source.bar_interval,
                )
                report.source = source.name
                validations.append(report)
                self.metadata_logger.append(
                    {
                        "event": "validation",
                        "source": report.source,
                        "symbol": report.symbol,
                        "rows": report.rows,
                        "start_timestamp": report.start_timestamp.isoformat(),
                        "end_timestamp": report.end_timestamp.isoformat(),
                        "gaps_detected": report.gaps_detected,
                        "warnings": report.warnings,
                    }
                )

        ingestion_report = self.ingestion_service.ingest()
        self.metadata_logger.append(
            {
                "event": "ingestion",
                "processed_symbols": ingestion_report.processed_symbols,
                "bars_added": ingestion_report.bars_added,
                "manifest_path": ingestion_report.manifest_path,
            }
        )
        self.logger.info(
            "acquisition_completed",
            extra={
                "fetched": len(fetched),
                "validations": len(validations),
                "bars_added": ingestion_report.bars_added,
            },
        )
        return AcquisitionReport(
            fetched=fetched,
            validations=validations,
            ingestion=ingestion_report,
        )


__all__ = [
    "AcquisitionReport",
    "DataAcquisitionConfig",
    "DataAcquisitionService",
    "FetchedArtifact",
    "FileSystemSourceConfig",
    "ValidationReport",
]
