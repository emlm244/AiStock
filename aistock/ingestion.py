"""
Deterministic data ingestion service for consolidating raw OHLCV files.

The ingestion pipeline is intentionally conservative: it tracks previously
processed timestamps, deduplicates incoming bars, validates monotonicity, and
appends new data into a curated directory.  No external dependencies are
required, keeping the workflow reproducible inside the Codex CLI environment.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from .config import DataQualityConfig
from .data import Bar, load_csv_file
from .logging import configure_logger


@dataclass
class DataIngestionConfig:
    """
    Configuration describing the ingestion workflow.

    Attributes:
        staging_dir: Directory containing freshly exported CSVs.
        curated_dir: Destination directory that stores the consolidated history.
        manifest_path: Path to a JSON file tracking last processed timestamps.
        allow_overwrite: If True, existing curated files are replaced instead of appended.
        archive_processed: Optional directory to archive staging files once processed.
        timezone: Timezone used when parsing naive timestamps.
    """

    staging_dir: str
    curated_dir: str
    manifest_path: str = 'state/ingestion_manifest.json'
    allow_overwrite: bool = False
    archive_processed: str | None = None
    timezone: timezone = timezone.utc
    quality: DataQualityConfig = field(default_factory=DataQualityConfig)


@dataclass
class IngestionReport:
    processed_symbols: list[str]
    bars_added: int
    manifest_path: str


class IngestionManifest:
    """
    Lightweight manifest that records the last ingested timestamp per symbol.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self._entries: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            with self.path.open('r', encoding='utf-8') as handle:
                try:
                    payload = cast(object, json.load(handle))
                    if isinstance(payload, dict):
                        data = cast(dict[object, object], payload)
                        self._entries = {str(k): str(v) for k, v in data.items()}
                except json.JSONDecodeError:
                    # Corrupt manifest -> start fresh.
                    self._entries = {}

    def last_timestamp(self, symbol: str) -> datetime | None:
        raw = self._entries.get(symbol.upper())
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def update(self, symbol: str, timestamp: datetime) -> None:
        self._entries[symbol.upper()] = timestamp.replace(tzinfo=timezone.utc).isoformat()

    def persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('w', encoding='utf-8') as handle:
            json.dump(self._entries, handle, indent=2)


class DataIngestionService:
    """
    Merge raw CSV drops into the curated dataset directory.

    The service is idempotent: rerunning it with the same staging files results in
    no changes.  It assumes each CSV filename corresponds to a single symbol
    (e.g. ``AAPL.csv``).
    """

    def __init__(self, config: DataIngestionConfig):
        self.config = config
        self.manifest = IngestionManifest(config.manifest_path)
        self.logger = configure_logger('IngestionService', structured=True)

    def ingest(self) -> IngestionReport:
        staging = Path(self.config.staging_dir).expanduser().resolve()
        curated = Path(self.config.curated_dir).expanduser().resolve()
        curated.mkdir(parents=True, exist_ok=True)

        processed: list[str] = []
        bars_added = 0

        if not staging.exists():
            self.logger.warning('staging_missing', extra={'path': str(staging)})
            return IngestionReport(processed_symbols=[], bars_added=0, manifest_path=str(self.manifest.path))

        for path in sorted(staging.glob('*.csv')):
            symbol = path.stem.upper()
            new_bars = self._load_new_bars(symbol, path)
            if not new_bars:
                continue

            destination = curated / f'{symbol}.csv'
            existing_bars: list[Bar] = []
            if destination.exists() and not self.config.allow_overwrite:
                existing_bars = load_csv_file(destination, symbol, self.config.timezone)

            merged = self._merge(existing_bars, new_bars)
            self._write_curated(destination, merged)
            processed.append(symbol)
            bars_added += len(new_bars)
            self.manifest.update(symbol, merged[-1].timestamp)

            if self.config.archive_processed:
                archive_root = Path(self.config.archive_processed).expanduser().resolve()
                archive_root.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, archive_root / path.name)

        self.manifest.persist()
        return IngestionReport(
            processed_symbols=processed, bars_added=bars_added, manifest_path=str(self.manifest.path)
        )

    # ------------------------------------------------------------------
    def _load_new_bars(self, symbol: str, path: Path) -> list[Bar]:
        bars = load_csv_file(path, symbol, self.config.timezone)
        last_ts = self.manifest.last_timestamp(symbol)
        if last_ts is None:
            return bars
        filtered = [bar for bar in bars if bar.timestamp > last_ts]
        if filtered:
            self.logger.info(
                'new_bars_detected',
                extra={
                    'symbol': symbol,
                    'count': len(filtered),
                    'path': str(path),
                    'last_manifest_ts': last_ts.isoformat(),
                },
            )
        return filtered

    def _merge(self, existing: list[Bar], incoming: list[Bar]) -> list[Bar]:
        if not existing:
            return incoming
        combined = existing + incoming
        combined.sort(key=lambda bar: bar.timestamp)

        deduped: list[Bar] = []
        seen: set[tuple[datetime, str]] = set()
        for bar in combined:
            key = (bar.timestamp, bar.symbol)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(bar)

        self._validate_order(deduped)
        return deduped

    @staticmethod
    def _validate_order(bars: Iterable[Bar]) -> None:
        previous: datetime | None = None
        for bar in bars:
            if previous and bar.timestamp <= previous:
                raise ValueError(f'Non-monotonic timestamp detected for {bar.symbol} at {bar.timestamp}')
            previous = bar.timestamp

    @staticmethod
    def _write_curated(destination: Path, bars: list[Bar]) -> None:
        import csv

        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('w', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for bar in bars:
                writer.writerow(
                    [
                        bar.timestamp.replace(tzinfo=timezone.utc).isoformat(),
                        f'{bar.open}',
                        f'{bar.high}',
                        f'{bar.low}',
                        f'{bar.close}',
                        f'{bar.volume}',
                    ]
                )
