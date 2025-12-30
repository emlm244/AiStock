"""
Data structures and loading utilities.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, SupportsInt, cast, overload

if TYPE_CHECKING:
    from .config import DataQualityConfig, DataSource


class _BoolMask(Protocol):
    def __invert__(self) -> _BoolMask: ...


class _Index(Protocol):
    tz: timezone | None

    def tz_localize(self, tz: timezone) -> _Index: ...

    def tz_convert(self, tz: timezone) -> _Index: ...

    def duplicated(self, keep: str = 'last') -> _BoolMask: ...


class _SeriesLike(Protocol):
    def __ge__(self, other: float) -> _BoolMask: ...


class _DataFrame(Protocol):
    index: _Index
    columns: Sequence[str]

    def sort_index(self) -> _DataFrame: ...

    def dropna(self, subset: Sequence[str]) -> _DataFrame: ...

    def iterrows(self) -> Iterable[tuple[datetime, Mapping[str, object]]]: ...

    @overload
    def __getitem__(self, key: str) -> _SeriesLike: ...

    @overload
    def __getitem__(self, key: _BoolMask) -> _DataFrame: ...

    @overload
    def __getitem__(self, key: list[bool]) -> _DataFrame: ...


class _PandasModule(Protocol):
    def read_csv(self, *args: object, **kwargs: object) -> _DataFrame: ...

    def to_datetime(self, arg: object, *, utc: bool | None = None) -> _Index: ...


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if hasattr(value, '__int__'):
        try:
            return int(cast(SupportsInt, value))
        except (TypeError, ValueError):
            return None
    return None


@dataclass
class Bar:
    """Single OHLCV bar."""

    __slots__ = ('symbol', 'timestamp', 'open', 'high', 'low', 'close', 'volume')

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self):
        """Validate bar data."""
        if self.high < self.low:
            raise ValueError(f'High ({self.high}) < Low ({self.low})')
        if self.open < self.low or self.open > self.high:
            raise ValueError(f'Open ({self.open}) outside High/Low range')
        if self.close < self.low or self.close > self.high:
            raise ValueError(f'Close ({self.close}) outside High/Low range')
        if self.volume < 0:
            raise ValueError(f'Volume cannot be negative: {self.volume}')


def load_csv_file(file_path: Path, symbol: str, tz: timezone | None = None) -> list[Bar]:
    """
    Load a single CSV file and return list of Bars.

    Args:
        file_path: Path to CSV file
        symbol: Symbol name
        tz: Timezone (optional, defaults to UTC)

    Returns:
        List of Bar objects
    """
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError('pandas is required to load CSV market data') from exc

    pd = cast(_PandasModule, pd)
    df = pd.read_csv(file_path, index_col=0, parse_dates=True)

    # Ensure timezone (prefer provided tz, default to UTC)
    target_tz = tz if tz is not None else timezone.utc
    if df.index.tz is None:  # type: ignore[attr-defined]
        df.index = pd.to_datetime(df.index).tz_localize(target_tz)  # type: ignore[attr-defined]
    else:
        df.index = df.index.tz_convert(target_tz)  # type: ignore[attr-defined]

    # Validate columns
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f'Missing required columns in {file_path}')

    # Clean and validate
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='last')]
    df = df.dropna(subset=required_cols)  # type: ignore[call-overload]

    # Convert to Bar objects
    bars: list[Bar] = []
    for timestamp, row in df.iterrows():
        try:
            # Validate prices are positive
            open_value = _to_decimal(row['open'])
            high_value = _to_decimal(row['high'])
            low_value = _to_decimal(row['low'])
            close_value = _to_decimal(row['close'])
            volume_value = _to_int(row['volume'])
            if open_value is None:
                raise ValueError('Missing or invalid bar values')
            if high_value is None:
                raise ValueError('Missing or invalid bar values')
            if low_value is None:
                raise ValueError('Missing or invalid bar values')
            if close_value is None:
                raise ValueError('Missing or invalid bar values')
            if volume_value is None:
                raise ValueError('Missing or invalid bar values')
            if open_value <= 0 or high_value <= 0 or low_value <= 0 or close_value <= 0:
                raise ValueError(
                    f'Invalid prices: open={open_value}, high={high_value}, low={low_value}, close={close_value}'
                )

            bar = Bar(
                symbol=symbol,
                timestamp=timestamp,  # type: ignore[arg-type]
                open=open_value,
                high=high_value,
                low=low_value,
                close=close_value,
                volume=volume_value,
            )
            bars.append(bar)
        except (ValueError, KeyError) as e:
            # For invalid data, re-raise to catch in tests, but print warning for other issues
            if 'Invalid prices' in str(e) or 'outside' in str(e):
                print(f'Warning: Invalid bar data for {symbol} at {timestamp}: {e}')
                # In strict mode, raise the error
                raise ValueError(f'Invalid bar data for {symbol} at {timestamp}: {e}')
            else:
                print(f'Warning: Invalid bar data for {symbol} at {timestamp}: {e}')
                continue

    return bars


def load_csv_directory(
    data_source: DataSource, data_quality_config: DataQualityConfig | None = None
) -> dict[str, list[Bar]]:
    """
    Load CSV files from directory.

    Args:
        data_source: DataSource config with path and symbols
        data_quality_config: DataQualityConfig for validation (optional, uses defaults if None)

    Returns:
        Dictionary mapping symbol to list of Bars
    """
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError('pandas is required to load CSV market data') from exc

    pd = cast(_PandasModule, pd)
    # Use default quality config if not provided
    if data_quality_config is None:
        from .config import DataQualityConfig

        # Use warmup_bars from data_source as min_bars if it's smaller
        min_bars = getattr(data_source, 'warmup_bars', 30)
        data_quality_config = DataQualityConfig(min_bars=min_bars)

    data_map: dict[str, list[Bar]] = {}
    data_path = Path(data_source.path)

    if not data_path.exists():
        raise ValueError(f'Data directory does not exist: {data_path}')

    # If specific symbols provided, load only those
    symbols_to_load: list[str] = list(data_source.symbols) if data_source.symbols else []

    # If no symbols specified, load all CSV files
    if not symbols_to_load:
        csv_files = list(data_path.glob('*.csv'))
        symbols_to_load = [f.stem.replace('_', '/') for f in csv_files]

    for symbol in symbols_to_load:
        # Convert symbol to filename (replace / with _)
        safe_symbol = symbol.replace('/', '_').replace('\\', '_')
        file_path = data_path / f'{safe_symbol}.csv'

        if not file_path.exists():
            print(f'Warning: Data file not found for {symbol}: {file_path}')
            continue

        try:
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)

            # Ensure UTC timezone
            if df.index.tz is None:  # type: ignore[attr-defined]
                df.index = pd.to_datetime(df.index, utc=True)  # type: ignore[attr-defined]

            # Validate columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                print(f'Warning: Missing columns in {file_path}')
                continue

            # Clean and validate
            df = df.sort_index()
            df = df[~df.index.duplicated(keep='last')]
            df = df.dropna(subset=required_cols)  # type: ignore[call-overload]

            # Apply data quality filters
            if data_quality_config.min_volume > 0:
                df = df[df['volume'] >= data_quality_config.min_volume]

            if len(df) < data_quality_config.min_bars:
                print(f'Warning: Insufficient bars for {symbol}: {len(df)} < {data_quality_config.min_bars}')
                continue

            # Convert to Bar objects
            bars: list[Bar] = []
            for timestamp, row in df.iterrows():
                try:
                    open_value = _to_decimal(row['open'])
                    high_value = _to_decimal(row['high'])
                    low_value = _to_decimal(row['low'])
                    close_value = _to_decimal(row['close'])
                    volume_value = _to_int(row['volume'])
                    if open_value is None:
                        raise ValueError('Missing or invalid bar values')
                    if high_value is None:
                        raise ValueError('Missing or invalid bar values')
                    if low_value is None:
                        raise ValueError('Missing or invalid bar values')
                    if close_value is None:
                        raise ValueError('Missing or invalid bar values')
                    if volume_value is None:
                        raise ValueError('Missing or invalid bar values')
                    bar = Bar(
                        symbol=symbol,
                        timestamp=timestamp,  # type: ignore[arg-type]
                        open=open_value,
                        high=high_value,
                        low=low_value,
                        close=close_value,
                        volume=volume_value,
                    )
                    bars.append(bar)
                except (ValueError, KeyError) as e:
                    print(f'Warning: Invalid bar data for {symbol} at {timestamp}: {e}')
                    continue

            if bars:
                data_map[symbol] = bars
                print(f'Loaded {len(bars)} bars for {symbol}')

        except Exception as e:
            print(f'Error loading data for {symbol}: {e}')
            continue

    return data_map


class DataFeed:
    """
    Iterator-based data feed for live trading simulation with forward fill support.
    """

    def __init__(
        self,
        data_map: dict[str, list[Bar]],
        bar_interval: timedelta | None = None,
        warmup_bars: int = 0,
        fill_missing: bool = False,
    ):
        self.data_map = data_map
        self.bar_interval = bar_interval or timedelta(minutes=1)
        self.warmup_bars = warmup_bars
        self.fill_missing = fill_missing
        self.indices: dict[str, int] = dict.fromkeys(data_map, 0)
        self._last_bars: dict[str, Bar] = {}  # Track last bar for forward fill

    def next(self) -> dict[str, Bar] | None:
        """
        Get next bar for all symbols.

        Returns:
            Dict of symbol -> Bar, or None if no more data
        """
        result: dict[str, Bar] = {}
        has_data = False

        for symbol, bars in self.data_map.items():
            idx = self.indices[symbol]
            if idx < len(bars):
                result[symbol] = bars[idx]
                self.indices[symbol] += 1
                has_data = True

        return result if has_data else None

    def iter_stream(self) -> Generator[tuple[datetime, str, Bar], None, None]:
        """
        Iterate through bars chronologically across all symbols with optional forward fill.

        Yields:
            Tuple of (timestamp, symbol, bar)
        """
        # Collect all timestamps
        all_timestamps: set[datetime] = set()
        for bars in self.data_map.values():
            for bar in bars:
                all_timestamps.add(bar.timestamp)

        sorted_timestamps = sorted(all_timestamps)

        # Create indices for each symbol
        indices: dict[str, int] = dict.fromkeys(self.data_map, 0)

        # Iterate through timestamps
        for timestamp in sorted_timestamps:
            for symbol, bars in self.data_map.items():
                idx = indices[symbol]

                # Check if this symbol has a bar at this timestamp
                if idx < len(bars) and bars[idx].timestamp == timestamp:
                    # Real bar
                    bar = bars[idx]
                    indices[symbol] += 1
                    self._last_bars[symbol] = bar
                    yield (timestamp, symbol, bar)
                elif self.fill_missing and symbol in self._last_bars:
                    # Forward fill with last known bar
                    last_bar = self._last_bars[symbol]
                    filled_bar = Bar(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=last_bar.close,
                        high=last_bar.close,
                        low=last_bar.close,
                        close=last_bar.close,
                        volume=0,
                    )
                    yield (timestamp, symbol, filled_bar)

    def reset(self) -> None:
        """Reset feed to beginning."""
        self.indices = dict.fromkeys(self.data_map, 0)
        self._last_bars = {}
