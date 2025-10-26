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

## FSD Auto-Discovery Feature ✨

**NEW**: FSD (Full Self-Driving) mode now **automatically discovers ALL available stocks** in this directory!

- The AI scans all CSV files in `data/historical/`
- It evaluates each stock based on liquidity, volatility, and price action
- It **autonomously chooses** which stocks to trade based on your risk preferences
- No need to specify which stocks to use - FSD makes the decision!

### Current Universe (36 Stocks)

The default generated dataset includes:

- **Tech (7)**: AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA
- **Finance (5)**: JPM, BAC, GS, WFC, C
- **Healthcare (5)**: JNJ, UNH, PFE, CVS, ABBV
- **Energy (4)**: XOM, CVX, COP, SLB
- **Media (3)**: DIS, NFLX, CMCSA
- **Retail (4)**: WMT, TGT, COST, HD
- **Industrial (4)**: BA, CAT, DE, MMM
- **Consumer (4)**: KO, PEP, MCD, SBUX

**Total**: 36 stocks across 8 sectors

### How FSD Chooses Stocks

Based on your risk preference:

**Conservative:**
- Selects large-cap, low-volatility stocks
- Prefers stable sectors (Consumer, Healthcare)
- Focuses on high-liquidity names

**Moderate:**
- Balanced mix of growth and stability
- Diversified across sectors
- Moderate volatility tolerance

**Aggressive:**
- May select higher-volatility stocks
- Technology and growth-focused
- Willing to trade smaller positions more frequently

### Minimum Requirements

For FSD mode to work properly:
- **Minimum symbols**: 10+ stocks (more is better!)
- **Minimum bars**: 100+ (preferably 365+ for daily data)
- **Recommended timeframe**: 1-2 years of history
- **Recommended universe**: 20-50 stocks across multiple sectors

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
