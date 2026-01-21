# Backtest Rerun Guide - Post P&L Fix

**Date**: 2025-11-02
**Fix Commit**: da36960
**Impact**: ALL TradingEngine backtest results prior to this commit are INVALID

---

## Background

The TradingEngine had a critical P&L calculation bug:

```python
# OLD (WRONG):
realised_pnl = closed_qty * price  # Just the dollar value of close!

# NEW (CORRECT):
realised_pnl = (exit_price - entry_price) * qty  # Actual profit/loss
```

**Example Impact**:
- Buy 100 shares @ $50, sell @ $60
- Old: P&L = $6,000 ❌ (6x overstated)
- Correct: P&L = $1,000 ✅

This invalidates:
- Total return metrics
- Max drawdown calculations
- Win rate statistics
- Any strategy validation using these results

---

## Automation Tools

### 1. Mark Invalid Results

```bash
python scripts/rerun_backtests.py \
  --results-dir backtest_results \
  --mark-invalid
```

This scans for pre-fix results and marks them with `.INVALID.json` suffix.

### 2. Generate Prioritized Rerun Plan

```bash
python scripts/rerun_backtests.py \
  --results-dir backtest_results \
  --generate-plan rerun_plan.json
```

Creates a prioritized list based on:
- **Total return magnitude** (higher = more impact)
- **Number of trades** (more trades = more errors)
- **Production flag** (production strategies prioritized)

### 3. Monitor Duplicate Rates

```bash
python scripts/monitor_duplicates.py logs/aistock.log --alert
```

Validates Option D (time-boxed idempotency) is working correctly.

---

## Prioritization Framework

### **Tier 1: CRITICAL (Rerun Immediately)**
- Production strategies currently in use
- Strategies with >50 trades
- Strategies with |total_return| > 20%

### **Tier 2: HIGH (Rerun This Week)**
- Strategies under evaluation for production
- Strategies with >20 trades
- Strategies with |total_return| > 10%

### **Tier 3: MEDIUM (Rerun As Capacity Allows)**
- Historical analysis backtests
- Strategies with <20 trades
- Exploratory parameter sweeps

### **Tier 4: LOW (Rerun If Needed)**
- One-off experiments
- Abandoned strategies
- Debug/test runs

---

## Rerun Workflow

1. **Identify Invalid Results**:
   ```bash
   python scripts/rerun_backtests.py --mark-invalid
   ```

2. **Generate Plan**:
   ```bash
   python scripts/rerun_backtests.py --generate-plan plan.json
   ```

3. **Review Priorities**:
   - Check `plan.json` for ranked list
   - Adjust based on business priorities

4. **Bulk Rerun** (example):
   ```bash
   # For each strategy in plan.json (top priority first)
   MASSIVE_API_KEY=... python -m aistock.backtest \
     --symbols AAPL MSFT \
     --start-date 2024-01-01 \
     --end-date 2024-12-31 \
     --output-dir backtest_results
   ```

5. **Compare Results**:
   ```bash
   # Compare old (invalid) vs new (corrected) metrics
   python scripts/compare_backtest_results.py \
     old.INVALID.json \
     new.json
   ```

6. **Flag Significant Discrepancies**:
   - P&L difference >50%: Review strategy logic
   - Win rate change >10%: Revalidate entry/exit rules
   - Max drawdown change >20%: Reassess risk management

---

## Expected Discrepancies

### **Long-Bias Strategies**:
- Old results: **Overstated profits** (exit price × qty)
- New results: **Correct profits** ((exit - entry) × qty)
- **Impact**: Total return likely **lower** than old results

### **Short-Heavy Strategies**:
- Old results: **Misstated losses** (confusing entry/exit)
- New results: **Correct P&L** ((entry - exit) × qty)
- **Impact**: Could be higher or lower depending on specific trades

### **Mean-Reversion Strategies**:
- Old results: **Random errors** (depends on entry/exit sequence)
- New results: **Consistent and correct**
- **Impact**: Variable, need case-by-case review

---

## Quality Checks

After rerunning, verify:

1. **✅ Cost Basis Tracked**:
   - Check `cost_basis` field in trade logs
   - Verify weighted average for position adds

2. **✅ P&L Formula Correct**:
   - Spot-check: P&L = (exit - entry) × qty for longs
   - Spot-check: P&L = (entry - exit) × qty for shorts

3. **✅ Partial Closes Handled**:
   - Verify partial position closes use correct basis
   - Cost basis should persist when reducing positions

4. **✅ No Regressions**:
   - Run regression tests: `pytest tests/test_engine_pnl.py`
   - All 7 tests should PASS

---

## Rollback Plan (If Issues Found)

If corrected results reveal unexpected issues:

1. **Review specific trades** with large P&L discrepancies
2. **Check cost basis calculations** in trade logs
3. **Validate against broker statements** (if available)
4. **File bug report** with:
   - Strategy parameters
   - Trade sequence that triggered issue
   - Expected vs actual P&L

---

## Communication Template

**Subject**: ACTION REQUIRED - Backtest Results Invalid (P&L Bug Fix)

**Body**:
> On 2025-11-02, we identified and fixed a critical bug in TradingEngine's P&L
> calculation. The bug caused realized P&L to be calculated as `qty × price`
> instead of `(exit_price - entry_price) × qty`.
>
> **Impact**: All backtest results prior to commit da36960 are INVALID.
>
> **Action Required**:
> 1. Mark old results as invalid
> 2. Rerun backtests using corrected engine
> 3. Revalidate strategy decisions based on new metrics
>
> **Priority**: [TIER 1/2/3/4 based on strategy]
>
> **Timeline**: [Based on rerun plan]
>
> See `docs/BACKTEST_RERUN_GUIDE.md` for details.

---

## FAQs

**Q: Do I need to rerun ALL backtests?**
A: Only those used for decision-making. Exploratory runs can be deprioritized.

**Q: How do I know if my strategy is affected?**
A: All strategies are affected. Impact depends on trade count and return magnitude.

**Q: What about production trading?**
A: Production uses the Portfolio class, which was already correct. Only backtests are affected.

**Q: Can I trust new backtest results?**
A: Yes. We have 7 regression tests covering longs, shorts, partials, and weighted averages.

**Q: Should I adjust strategy parameters?**
A: Not yet. First rerun with same parameters to see actual historical performance.

---

## Support

Questions? Issues with reruns?
- Check regression tests: `pytest tests/test_engine_pnl.py -v`
- Review commit: `git show da36960`
- Contact: [Your team communication channel]
