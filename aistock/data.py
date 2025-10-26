"""
Utilities for reading historical OHLCV data without third-party dependencies.

The module intentionally avoids pandas/numpy so it can run inside the constrained
execution environment provided by the Codex CLI.  CSV parsing is streamed and
validated row-by-row to guard against malformed data.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path

from .config import DataQualityConfig, DataSource

# Increase decimal precision to handle instruments priced with many decimals.
getcontext().prec = 18


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime  # timezone-aware, always UTC internally
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: float

    def mid_price(self) -> Decimal:
        return (self.high + self.low) / Decimal("2")


def parse_timestamp(raw: str, tz: timezone) -> datetime:
    """
    Parse ISO-8601 timestamps and normalise them to UTC.

    We accept both aware and naive strings.  Naive timestamps are interpreted
    in the provided timezone, then converted to UTC.
    """
    ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=tz)
    return ts.astimezone(timezone.utc)


def load_csv_file(path: Path, symbol: str, tz: timezone) -> list[Bar]:
    bars: list[Bar] = []
    with path.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = expected - set(reader.fieldnames or set())
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        for row in reader:
            try:
                bar = Bar(
                    symbol=symbol,
                    timestamp=parse_timestamp(row["timestamp"], tz),
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=float(row["volume"]),
                )
            except (InvalidOperation, ValueError) as exc:
                # Skip malformed lines but keep a record so the caller can inspect.
                raise ValueError(f"{path}: invalid numeric content -> {exc}") from exc

            if bar.low > bar.high:
                raise ValueError(f"{path}: low({bar.low}) > high({bar.high}) at {bar.timestamp}")
            bars.append(bar)
    bars.sort(key=lambda b: b.timestamp)
    return bars


def _validate_bars(symbol: str, bars: list[Bar], quality: DataQualityConfig, bar_interval: timedelta) -> None:
    if not bars:
        raise ValueError(f"{symbol}: no data loaded")
    previous_ts: datetime | None = None
    for bar in bars:
        if previous_ts is not None:
            if quality.require_monotonic_timestamps and bar.timestamp <= previous_ts:
                raise ValueError(f"{symbol}: non-monotonic timestamp detected at {bar.timestamp.isoformat()}")
            gap = bar.timestamp - previous_ts
            if bar_interval > timedelta(0) and quality.max_gap_bars >= 0:
                expected = bar_interval
                # Allow small drift for irregular feeds; convert gap to multiples.
                multiples = gap / expected if expected.total_seconds() else 0
                if multiples > (quality.max_gap_bars + 1):
                    raise ValueError(
                        f"{symbol}: gap of {gap} between {previous_ts} and {bar.timestamp} exceeds limit of "
                        f"{quality.max_gap_bars} bars"
                    )
        if not quality.zero_volume_allowed and bar.volume == 0:
            raise ValueError(f"{symbol}: zero volume encountered at {bar.timestamp}")
        previous_ts = bar.timestamp


def resolve_symbol(filename: Path) -> str:
    """Infer symbol from file name (e.g. `AAPL.csv` -> `AAPL`)."""
    return filename.stem.upper()


def load_csv_directory(source: DataSource, quality: DataQualityConfig | None = None) -> dict[str, list[Bar]]:
    """
    Load all CSV files from ``source.path`` for the requested symbols.

    Returns a mapping ``symbol -> [Bar, ...]`` sorted chronologically.  Missing
    symbols raise a ``FileNotFoundError`` so that the calling code can fail
    loudly instead of silently running with incomplete data.
    """
    root = Path(source.path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Data directory does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Data source path is not a directory: {root}")

    symbol_whitelist = {sym.upper() for sym in source.symbols or []}
    available_files = {resolve_symbol(path): path for path in root.glob("*.csv")}
    if symbol_whitelist:
        missing = sorted(symbol_whitelist - set(available_files))
        if missing:
            raise FileNotFoundError(
                f"Data files missing for symbols {missing} in directory {root}"
            )
        targets = {sym: available_files[sym] for sym in symbol_whitelist}
    else:
        targets = available_files

    result: dict[str, list[Bar]] = {}
    quality = quality or DataQualityConfig()
    for symbol, path in sorted(targets.items()):
        bars = load_csv_file(path, symbol, source.timezone)
        _validate_bars(symbol, bars, quality, source.bar_interval)
        result[symbol] = bars
        if len(bars) <= source.warmup_bars:
            raise ValueError(
                f"{symbol}: not enough data for warmup ({len(bars)} <= warmup {source.warmup_bars})"
            )
    return result


@dataclass
class Cursor:
    symbol: str
    index: int = 0


class DataFeed:
    """
    Deterministic multi-symbol data feed with warmup handling and optional forward-fill
    for missing bars.
    """

    def __init__(
        self,
        bars_by_symbol: dict[str, list[Bar]],
        bar_interval: timedelta,
        warmup_bars: int,
        fill_missing: bool = False,
    ):
        self._bars = bars_by_symbol
        self._bar_interval = bar_interval
        self._warmup = warmup_bars
        self._fill_missing = fill_missing
        self._symbols = sorted(bars_by_symbol)

        self._cursors = {symbol: Cursor(symbol=symbol) for symbol in bars_by_symbol}
        all_timestamps = {
            bar.timestamp for bars in bars_by_symbol.values() for bar in bars
        }
        self._timeline: list[datetime] = sorted(all_timestamps)

    def warmup_history(self, symbol: str) -> list[Bar]:
        bars = self._bars[symbol][: self._warmup]
        if len(bars) < self._warmup:
            return bars[:]
        return bars[-self._warmup :]

    def iter_stream(self) -> Iterator[tuple[datetime, str, Bar]]:
        """
        Yields (timestamp, symbol, bar) in chronological order.
        """
        last_bar_by_symbol: dict[str, Bar] = {}
        for timestamp in self._timeline:
            for symbol in self._symbols:
                cursor = self._cursors[symbol]
                bar_list = self._bars[symbol]
                if cursor.index < len(bar_list) and bar_list[cursor.index].timestamp == timestamp:
                    bar = bar_list[cursor.index]
                    cursor.index += 1
                    last_bar_by_symbol[symbol] = bar
                    yield (timestamp, symbol, bar)
                elif self._fill_missing and symbol in last_bar_by_symbol:
                    last_bar = last_bar_by_symbol[symbol]
                    fill_bar = Bar(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=last_bar.close,
                        high=last_bar.close,
                        low=last_bar.close,
                        close=last_bar.close,
                        volume=0.0,
                    )
                    last_bar_by_symbol[symbol] = fill_bar
                    yield (timestamp, symbol, fill_bar)
