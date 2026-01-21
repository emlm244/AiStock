# Scripts Directory

Automation tools for AIStock trading system maintenance and operations.

---

## Backtest Management

### `run_full_workflow.py` ⭐ **NEW**

End-to-end workflow demonstration for the complete P&L fix process.

**Usage**:
```bash
python scripts/run_full_workflow.py
```

**What it does**:
1. Generates sample backtest with corrected P&L
2. Compares old (broken) vs new (corrected) results
3. Generates prioritized rerun plan
4. Shows step-by-step walkthrough

**Perfect for**: Testing, validation, and understanding the complete workflow.

---

### `run_sample_backtest.py` ⭐ **NEW**

Generates sample backtest using corrected TradingEngine P&L calculation.

**Usage**:
```bash
python scripts/run_sample_backtest.py
```

**Validates**: P&L calculation is correct (expected: $550, actual: $550 ✓)

---

### `compare_backtest_results.py` ⭐ **NEW**

Compares old (INVALID) vs new (corrected) backtest results side-by-side.

**Usage**:
```bash
python scripts/compare_backtest_results.py old.INVALID.json new.json --detailed
```

**Output**:
- Side-by-side metric comparison
- Percentage changes
- Alerts for significant discrepancies
- Trade-by-trade P&L diff (optional)

**Example**:
```
Total Return:  6.00% -> 0.55% (-90.8%)
[CRITICAL] Old results OVERSTATED performance by 90.8%
```

---

### `rerun_backtests.py`

Automates backtest reruns after the critical P&L bug fix (commit da36960).

**Usage**:

```bash
# Mark pre-fix results as invalid
python scripts/rerun_backtests.py --results-dir backtest_results --mark-invalid

# Generate prioritized rerun plan
python scripts/rerun_backtests.py --results-dir backtest_results --generate-plan plan.json
```

**Features**:
- Identifies pre-fix backtest results
- Marks them with `.INVALID.json` suffix
- Generates prioritized rerun plan based on:
  - Total return magnitude
  - Number of trades
  - Production strategy flag

**See**: `docs/BACKTEST_RERUN_GUIDE.md` for full workflow

---

## Duplicate Monitoring

### `monitor_duplicates.py`

Monitors logs for duplicate order patterns to validate Option D (time-boxed idempotency).

**Usage**:

```bash
# Analyze log file
python monitor_duplicates.py logs/aistock.log

# Generate alerts
python monitor_duplicates.py logs/aistock.log --alert

# Save analysis to JSON
python monitor_duplicates.py logs/aistock.log --output analysis.json
```

**Alerts**:
- 🚨 **CRITICAL**: Same-session duplicates (Option D failed)
- ⚠️ **HIGH**: Cross-restart duplicates <5min (time-box failed)
- ⚠️ **WARNING**: Retry rate >10% (possible data/broker issues)

**Expected Behavior**:
- Same-session duplicates: **ZERO**
- Cross-restart <5min: **ZERO**
- Retries >5min: **Expected** (valid retry after expiration)

---

## Other Scripts

### `run_smoke_backtest.py`

Quick smoke test for backtest engine (existing script).

```bash
python scripts/run_smoke_backtest.py
```

---

## Script Development Guidelines

When adding new scripts:

1. **Shebang**: Use `#!/usr/bin/env python3`
2. **Docstring**: Include purpose, usage, and examples
3. **Logging**: Prefer `logging` for long-running scripts; small demo scripts may use `print`
4. **Error Handling**: Graceful failures with meaningful messages
5. **CLI**: Use `argparse` for arguments
6. **Output**: Support JSON output for automation
7. **Documentation**: Update this README

---

## Dependencies

Most scripts require the aistock package:

```bash
pip install -r requirements.txt
```

Scripts use standard project dependencies from `requirements.txt`.

---

## Cron Jobs / Scheduled Tasks

### Duplicate Monitoring (Daily)

```cron
# Run daily at 2 AM
0 2 * * * /path/to/venv/bin/python /path/to/scripts/monitor_duplicates.py \
  /path/to/logs/aistock.log --alert >> /path/to/logs/duplicate_monitor.log 2>&1
```

### Backtest Smoke Test (Weekly)

```cron
# Run weekly on Sundays at 3 AM
0 3 * * 0 /path/to/venv/bin/python /path/to/scripts/run_smoke_backtest.py \
  >> /path/to/logs/backtest_smoke.log 2>&1
```

---

## Maintenance

- Review script logs weekly
- Update scripts when core engine changes
- Archive obsolete scripts to `scripts/archive/`
- Document breaking changes in commit messages
