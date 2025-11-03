# Scripts Directory

Automation tools for AIStock trading system maintenance and operations.

---

## Backtest Management

### `rerun_backtests.py`

Automates backtest reruns after the critical P&L bug fix (commit da36960).

**Usage**:

```bash
# Mark pre-fix results as invalid
python rerun_backtests.py --results-dir backtest_results --mark-invalid

# Generate prioritized rerun plan
python rerun_backtests.py --results-dir backtest_results --generate-plan plan.json
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
3. **Logging**: Use `logging` module (not print statements)
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

For production monitoring scripts, also install:

```bash
pip install -r requirements-monitoring.txt  # If it exists
```

---

## Cron Jobs / Scheduled Tasks

### Duplicate Monitoring (Daily)

```cron
# Run daily at 2 AM
0 2 * * * /path/to/venv/bin/python /path/to/scripts/monitor_duplicates.py \
  /path/to/logs/aistock.log --alert >> /path/to/logs/duplicate_monitor.log 2>&1
```

### Backtest Health Check (Weekly)

```cron
# Run weekly on Sundays at 3 AM
0 3 * * 0 /path/to/venv/bin/python /path/to/scripts/check_backtest_health.py \
  --results-dir /path/to/backtest_results >> /path/to/logs/backtest_health.log 2>&1
```

---

## Testing Scripts

Scripts should have unit tests in `tests/test_scripts/`:

```bash
pytest tests/test_scripts/test_rerun_backtests.py
```

---

## Maintenance

- Review script logs weekly
- Update scripts when core engine changes
- Archive obsolete scripts to `scripts/archive/`
- Document breaking changes in commit messages
