# Data Provenance & Quality Standards

**P1 Enhancement: Comprehensive data documentation for production trading.**

---

## Overview

This document establishes standards for data provenance, quality assurance, and adjustment methodology. All historical data used for backtesting MUST follow these standards to ensure reproducible, leak-free research.

---

## Data Requirements

### 1. Source Documentation

Every dataset MUST include:

| Attribute | Description | Example |
|-----------|-------------|---------|
| **Provider** | Data vendor/source | Alpha Vantage, IBKR, Yahoo Finance |
| **Fetch Date** | When data was downloaded | 2025-01-15 |
| **Data Range** | Start and end dates | 2020-01-01 to 2024-12-31 |
| **Frequency** | Bar interval | 1-minute, 5-minute, 1-day |
| **Timezone** | Original timezone | America/New_York (EST/EDT) |
| **Adjustment Type** | Price adjustment method | Split-adjusted, dividend-adjusted, both, unadjusted |

**Example: `data/2024-01/README.txt`**
```
Provider: Interactive Brokers
Fetch Date: 2025-01-15
Data Range: 2024-01-01 to 2024-01-31
Frequency: 1-minute bars
Timezone: America/New_York (converted to UTC in CSV)
Adjustment: Split-adjusted and dividend-adjusted (backward)
Symbols: AAPL, MSFT, GOOGL (50 symbols total)
Notes: Data includes pre-market (4am-9:30am) and after-hours (4pm-8pm) sessions.
```

---

## 2. CSV Schema

**Required Columns:**
```csv
timestamp,open,high,low,close,volume
```

**Format Rules:**
- `timestamp`: ISO-8601 format, UTC timezone (e.g., `2024-01-15T14:30:00+00:00` or `2024-01-15T14:30:00Z`)
- `open`, `high`, `low`, `close`: Decimal prices (up to 6 decimal places)
- `volume`: Integer (no commas, no scientific notation)

**Example:**
```csv
timestamp,open,high,low,close,volume
2024-01-02T09:30:00+00:00,185.50,186.25,185.40,186.10,1250000
2024-01-02T09:31:00+00:00,186.10,186.50,186.00,186.45,980000
```

---

## 3. Adjustment Methodology

### Split Adjustments

**Backward Adjustment (Recommended):**
- All prices BEFORE the split date are divided by the split ratio
- Post-split prices remain unchanged
- Preserves recent price levels (useful for live trading transition)

**Example: AAPL 4:1 split on 2024-08-31**
```
Date         Unadjusted  Split-Adjusted (Backward)
2024-08-30   $500.00     $125.00  (divided by 4)
2024-08-31   $125.00     $125.00  (no change)
```

### Dividend Adjustments

**Backward Adjustment (Optional):**
- All prices BEFORE the ex-dividend date have the dividend added back
- Post-dividend prices remain unchanged
- Less critical for intraday trading (more important for long-term buy-and-hold)

**Example: MSFT $0.75 dividend on 2024-02-21**
```
Date         Unadjusted  Dividend-Adjusted (Backward)
2024-02-20   $415.00     $415.75  (+ $0.75)
2024-02-21   $414.25     $414.25  (no change, price drops naturally)
```

### Recommended Approach

✅ **For Backtesting:** Use split + dividend adjusted data (backward adjustment)
✅ **For Live Trading:** Use unadjusted data + corporate action tracker
⚠️ **Never Mix:** Ensure all symbols use same adjustment methodology

---

## 4. Survivorship Bias

**Definition:** Including only stocks that survived to the present day, excluding delisted/bankrupt companies.

**Risk:** Overstates historical performance (dead stocks often had poor returns)

**Mitigation:**
1. Use survivorship-bias-free datasets (e.g., CRSP, Sharadar)
2. Include delisting events in corporate action tracker
3. Document symbol universe selection criteria
4. Report backtest as "survivorship-biased" if using current index constituents

**Example: S&P 500 Backtest**
```
Universe: S&P 500 constituents as of 2025-01-15
Survivorship Bias: YES (only current constituents, no historical removals)
Impact: Likely overestimates returns by 1-3% annually
Recommendation: Use point-in-time constituent data or apply survivorship penalty
```

---

## 5. Corporate Actions Tracking

Use `aistock.corporate_actions.CorporateActionTracker` to document splits/dividends:

**CSV Format:** `data/corporate_actions.csv`
```csv
symbol,ex_date,action_type,ratio,amount,description
AAPL,2024-08-31,split,4.0,,4-for-1 stock split
MSFT,2024-02-21,dividend,,0.75,Q1 2024 dividend
NVDA,2024-06-10,split,10.0,,10-for-1 stock split
```

**Usage:**
```python
from aistock.corporate_actions import CorporateActionTracker, create_split

tracker = CorporateActionTracker.load_from_csv("data/corporate_actions.csv")

# Add new action
tracker.add_action(create_split("TSLA", date(2024, 03, 15), Decimal("3.0")))

# Check for action
action = tracker.check_for_action("AAPL", datetime(2024, 8, 31, tzinfo=timezone.utc))
if action:
    print(f"Corporate action on {action.ex_date}: {action.description}")

# Adjust price
adjusted_price = tracker.adjust_price("AAPL", Decimal("500.0"), datetime(2024, 8, 30, tzinfo=timezone.utc))
print(f"Adjusted price: {adjusted_price}")  # $125.00 (backward adjusted for 4:1 split)
```

---

## 6. Data Quality Checks

**Pre-Backtest Validation:**
1. ✅ No missing timestamps (or forward-filled with `allow_nan=True`)
2. ✅ No negative prices or volumes
3. ✅ No gaps > `max_gap_bars` threshold
4. ✅ Monotonic timestamps (chronologically ordered)
5. ✅ Low/high relationships valid (`low <= high`)
6. ✅ All timestamps in UTC
7. ✅ No duplicate timestamps

**Example: Validation Script**
```python
from aistock.data import load_csv_directory
from aistock.config import DataSource, DataQualityConfig

source = DataSource(
    path="data/2024-01",
    symbols=["AAPL", "MSFT"],
    timezone=timezone.utc,
)
quality = DataQualityConfig(
    max_gap_bars=5,
    require_monotonic_timestamps=True,
    zero_volume_allowed=False,
)

try:
    data = load_csv_directory(source, quality)
    print(f"✅ Loaded {len(data)} symbols, validation passed")
except ValueError as e:
    print(f"❌ Data quality issue: {e}")
```

---

## 7. Retention & Archival

**Best Practices:**
1. **Immutable Storage:** Once fetched, never modify original files
2. **Versioning:** Use timestamped directories (e.g., `data/2024-01-fetched-20250115/`)
3. **Compression:** Archive old datasets (gzip, zip) to save space
4. **Backup:** Store datasets in multiple locations (local + cloud)
5. **Retention Policy:** Keep at least 2 years of historical data for walk-forward validation

**Directory Structure:**
```
data/
├── 2024-01-fetched-20250115/  # Original fetch
│   ├── README.txt              # Provenance metadata
│   ├── AAPL.csv
│   ├── MSFT.csv
│   └── corporate_actions.csv
├── 2024-01-fetched-20250115.zip  # Archived
└── latest/                     # Symlink to most recent
    ├── AAPL.csv
    └── MSFT.csv
```

---

## 8. Leakage Prevention

**Common Leakage Sources:**
1. **Future Data in Features:** Features use bars after prediction time
2. **Corporate Actions:** Using post-split prices without adjustment
3. **Survivorship Bias:** Only including stocks that survived
4. **Index Rebalancing:** Using current S&P 500 constituents for 2020 backtest
5. **Look-ahead Indicators:** Indicators that use future bars (e.g., future highs)

**Mitigation:**
- Use `extract_features(bars, as_of_timestamp=...)` for automatic leakage detection
- Assert `label_timestamp > feature_timestamp` in dataset construction
- Document universe selection as "point-in-time" or "survivorship-biased"
- Audit all indicators for look-ahead bias

---

## 9. Data Provider Comparison

| Provider | Pros | Cons | Recommended Use |
|----------|------|------|-----------------|
| **Interactive Brokers** | Live data, high quality, multiple exchanges | Requires account, limited history | Live trading, recent backtests |
| **Alpha Vantage** | Free API, decent coverage | Rate limits, 5-year history | Research, small datasets |
| **Yahoo Finance** | Free, wide coverage | Survivorship bias, data quality issues | Quick prototypes only |
| **Polygon.io** | Professional grade, clean data | Paid, expensive | Production backtests |
| **CRSP / Sharadar** | Survivorship-bias-free, academic quality | Very expensive | Research, publications |

---

## 10. Compliance & Licensing

**Legal Considerations:**
- Data usage subject to provider's terms of service
- Redistribution typically prohibited
- Commercial use may require paid license
- Real-time data has stricter rules than delayed/historical

**Documentation:**
- Store copy of data license agreement in `data/licenses/`
- Document data usage terms in README
- Ensure compliance with FINRA/SEC regulations if applicable

---

## 11. Example: Complete Provenance Record

**File:** `data/2024-Q1/PROVENANCE.json`
```json
{
  "provider": "Interactive Brokers",
  "fetch_date": "2025-01-15T10:30:00Z",
  "data_range": {
    "start": "2024-01-01",
    "end": "2024-03-31"
  },
  "frequency": "1-minute",
  "timezone": "UTC",
  "adjustment": {
    "splits": true,
    "dividends": true,
    "method": "backward"
  },
  "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
  "survivorship_bias": true,
  "universe": "S&P 500 constituents as of 2025-01-15",
  "data_quality": {
    "missing_bars": 0,
    "gaps_filled": false,
    "zero_volume_bars": 0
  },
  "corporate_actions_file": "data/2024-Q1/corporate_actions.csv",
  "license": "Interactive Brokers Market Data Subscriber Agreement",
  "notes": "Data includes extended hours (4am-8pm ET). All timestamps converted to UTC."
}
```

---

## 12. Checklist: Production-Ready Dataset

✅ **Provenance documented** (provider, fetch date, adjustment methodology)
✅ **CSV schema valid** (ISO-8601 timestamps, correct columns)
✅ **Quality checks passed** (no gaps, monotonic, valid OHLC relationships)
✅ **Corporate actions tracked** (splits/dividends documented)
✅ **Survivorship bias disclosed** (if applicable)
✅ **Timezone consistent** (all timestamps UTC)
✅ **Backup created** (archived and versioned)
✅ **License verified** (usage terms documented)

---

## Contact & Support

For data quality issues or questions:
1. Review dataset README
2. Check data quality validation logs
3. Inspect `load_csv_directory()` error messages
4. File issue with dataset provider if data is corrupted

---

**Last Updated:** 2025-01-15 (P1 Enhancement)
**Maintained By:** AIStock Robot Data Team
