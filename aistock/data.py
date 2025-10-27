"""
Data structures and loading utilities.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
import pandas as pd


@dataclass
class Bar:
    """Single OHLCV bar."""
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
            raise ValueError(f"High ({self.high}) < Low ({self.low})")
        if self.open < self.low or self.open > self.high:
            raise ValueError(f"Open ({self.open}) outside High/Low range")
        if self.close < self.low or self.close > self.high:
            raise ValueError(f"Close ({self.close}) outside High/Low range")
        if self.volume < 0:
            raise ValueError(f"Volume cannot be negative: {self.volume}")


def load_csv_directory(data_source, data_quality_config) -> dict[str, list[Bar]]:
    """
    Load CSV files from directory.
    
    Args:
        data_source: DataSource config with path and symbols
        data_quality_config: DataQualityConfig for validation
    
    Returns:
        Dictionary mapping symbol to list of Bars
    """
    data_map = {}
    data_path = Path(data_source.path)
    
    if not data_path.exists():
        raise ValueError(f"Data directory does not exist: {data_path}")
    
    # If specific symbols provided, load only those
    symbols_to_load = data_source.symbols if data_source.symbols else []
    
    # If no symbols specified, load all CSV files
    if not symbols_to_load:
        csv_files = list(data_path.glob("*.csv"))
        symbols_to_load = [f.stem.replace('_', '/') for f in csv_files]
    
    for symbol in symbols_to_load:
        # Convert symbol to filename (replace / with _)
        safe_symbol = symbol.replace('/', '_').replace('\\', '_')
        file_path = data_path / f"{safe_symbol}.csv"
        
        if not file_path.exists():
            print(f"Warning: Data file not found for {symbol}: {file_path}")
            continue
        
        try:
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            
            # Ensure UTC timezone
            if df.index.tz is None:
                df.index = pd.to_datetime(df.index, utc=True)
            
            # Validate columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                print(f"Warning: Missing columns in {file_path}")
                continue
            
            # Clean and validate
            df = df.sort_index()
            df = df[~df.index.duplicated(keep='last')]
            df = df.dropna(subset=required_cols)
            
            # Apply data quality filters
            if data_quality_config.min_volume > 0:
                df = df[df['volume'] >= data_quality_config.min_volume]
            
            if len(df) < data_quality_config.min_bars:
                print(f"Warning: Insufficient bars for {symbol}: {len(df)} < {data_quality_config.min_bars}")
                continue
            
            # Convert to Bar objects
            bars = []
            for timestamp, row in df.iterrows():
                try:
                    bar = Bar(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=Decimal(str(row['open'])),
                        high=Decimal(str(row['high'])),
                        low=Decimal(str(row['low'])),
                        close=Decimal(str(row['close'])),
                        volume=int(row['volume']),
                    )
                    bars.append(bar)
                except (ValueError, KeyError) as e:
                    print(f"Warning: Invalid bar data for {symbol} at {timestamp}: {e}")
                    continue
            
            if bars:
                data_map[symbol] = bars
                print(f"Loaded {len(bars)} bars for {symbol}")
        
        except Exception as e:
            print(f"Error loading data for {symbol}: {e}")
            continue
    
    return data_map
