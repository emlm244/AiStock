# Data Directory

This directory contains historical market data for backtesting and live trading.

## Directory Structure

```
data/
├── historical/       # Historical OHLCV data (CSV files)
├── staging/          # Temporary staging area for data ingestion
├── curated/          # Clean, validated data after ingestion
└── live_data/        # Real-time data feeds (optional)
```

## Generating Sample Data

If the `historical/` directory is empty or you need to regenerate data:

### Method 1: Using the Data Generator Script

Generate synthetic data for common stocks:

```bash
python scripts/generate_synthetic_dataset.py \
  --out data/historical \
  --symbols AAPL MSFT GOOGL AMZN TSLA NVDA META \
  --start 2023-01-01 \
  --end 2024-12-31 \
  --frequency daily \
  --seed 42
```

### Method 2: Quick Setup (Recommended)

For quick testing with 5 popular stocks (2 years of daily data):

```bash
python scripts/generate_synthetic_dataset.py \
  --out data/historical \
  --symbols AAPL MSFT GOOGL AMZN TSLA \
  --start 2023-01-01 \
  --end 2024-12-31 \
  --frequency daily
```

This generates approximately 731 bars per symbol (2 years × 365 days).

## Data Format

CSV files must follow this format:

```csv
timestamp,open,high,low,close,volume
2023-01-01T00:00:00+00:00,100.0,101.0,99.5,100.5,10000
2023-01-02T00:00:00+00:00,100.5,101.5,100.0,101.0,11000
...
```

### Requirements:
- **Headers**: `timestamp,open,high,low,close,volume`
- **Timestamp**: ISO-8601 format with timezone (e.g., `2023-01-01T00:00:00+00:00`)
- **Prices**: Decimal values (OHLC)
- **Volume**: Integer or float
- **Filename**: `{SYMBOL}.csv` (e.g., `AAPL.csv`)

## Using Real Market Data

To use real market data:

1. **Download from a provider**: Use APIs from Alpha Vantage, Yahoo Finance, Polygon.io, etc.
2. **Convert to the required format**: Ensure CSV follows the format above
3. **Place files in**: `data/historical/`
4. **Validate**: Run a test backtest to verify data quality

## Data Quality

The system validates:
- ✅ Monotonic timestamps (chronological order)
- ✅ No negative or zero prices
- ✅ Price anomaly detection (rejects >50% jumps)
- ✅ Gap detection (warns on missing bars)
- ✅ Volume validation (optional)

## Recommended Symbols

### US Equities (Large Cap)
- **Tech**: AAPL, MSFT, GOOGL, AMZN, META, NVDA
- **Finance**: JPM, BAC, GS, WFC
- **Healthcare**: JNJ, UNH, PFE
- **Consumer**: TSLA, NKE, DIS

### Minimum Requirements

For FSD mode to work properly:
- **Minimum symbols**: 3-5 stocks
- **Minimum bars**: 100+ (preferably 365+ for daily data)
- **Recommended timeframe**: 1-2 years of history

## Troubleshooting

### "Data directory does not exist"
```bash
mkdir -p data/historical
python scripts/generate_synthetic_dataset.py --out data/historical --symbols AAPL MSFT --start 2023-01-01 --end 2024-12-31 --frequency daily
```

### "Not enough data for warmup"
Ensure you have at least 100 bars per symbol. Check with:
```bash
wc -l data/historical/*.csv
```

### "Invalid price detected"
Check for:
- Negative prices
- Zero prices
- Missing OHLC values
- Corrupted CSV files

Run validation:
```bash
python -c "from aistock import load_csv_directory, DataSource; from datetime import timedelta, timezone; load_csv_directory(DataSource(path='data/historical', symbols=['AAPL'], bar_interval=timedelta(days=1), timezone=timezone.utc, warmup_bars=30))"
```

## Notes

- Generated data files (`.csv`) are in `.gitignore` and won't be committed to git
- Data can be regenerated anytime using the scripts
- For production use, replace synthetic data with real market data
