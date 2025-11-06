# Code Quality Issues - Quick Reference

## CRITICAL ISSUES (Fix Immediately)

### 1. Edge Case Handler Parameter Mismatch
- **File:** `aistock/fsd.py`
- **Line:** 669
- **Problem:** Second call to `edge_case_handler.check_edge_cases()` is missing required parameters
- **Current:**
  ```python
  edge_result = self.edge_case_handler.check_edge_cases(symbol, bars)
  ```
- **Should be:**
  ```python
  edge_result = self.edge_case_handler.check_edge_cases(
      symbol=symbol,
      bars=bars,
      timeframe_data=timeframe_data if self.timeframe_manager else None,
      current_time=datetime.now(timezone.utc),
  )
  ```
- **Impact:** Loss of timeframe and time-based edge case detection on second invocation

---

## HIGH SEVERITY ISSUES

### 2. Incomplete Error Handling in update_position()
- **File:** `aistock/portfolio.py`
- **Lines:** 138-166
- **Problem:** Exception handler in try-except doesn't actually recover or log errors
- **Impact:** Risk of position state corruption if `pos.realise()` fails
- **Fix:** Backup position state before modification and restore on exception; add logging

### 3. Duplicate P&L Calculation Logic
- **Files:** `aistock/engine.py` (lines 101-110) + `aistock/portfolio.py` (lines 207-227)
- **Problem:** P&L is calculated independently in two places
- **Impact:** Calculations could diverge; violates "TradingEngine is authoritative" principle
- **Fix:** Remove from Portfolio, pass calculated value from caller

---

## MEDIUM SEVERITY ISSUES

### 4. Inconsistent Float/Decimal Conversion
- **File:** `aistock/fsd.py`
- **Lines:** 1128-1131 (warmup_from_historical)
- **Problem:** Unnecessary float→Decimal round-trip loses precision
- **Current:**
  ```python
  current_price = float(window[-1].close)
  self.extract_state(symbol, window, {symbol: Decimal(str(current_price))})
  ```
- **Should be:**
  ```python
  self.extract_state(symbol, window, {symbol: window[-1].close})
  ```

### 5. Hardcoded Position Normalization
- **File:** `aistock/fsd.py`
- **Line:** 854 (handle_fill)
- **Problem:** Uses arbitrary hardcoded 1000.0 for position normalization
- **Current:**
  ```python
  next_state['position_pct'] = new_position / 1000.0  # Why 1000?
  ```
- **Should be:** Normalize by equity like in extract_state()

---

## LOW SEVERITY ISSUES

### 6. Unnecessary Defensive Check
- **File:** `aistock/engine.py`
- **Lines:** 134-137
- **Issue:** Impossible condition (`total_qty == 0`) - can be safely removed

### 7. Missing Timestamp Validation
- **File:** `aistock/engine.py`
- **Line:** 22-30 (Trade dataclass)
- **Issue:** No validation that timestamp is timezone-aware
- **Recommendation:** Add `__post_init__` validation per CLAUDE.md requirements

---

## PASSING AREAS ✓

- **Thread Safety:** Excellent - all shared state properly locked
- **Timezone Handling:** Excellent - consistent use of `datetime.now(timezone.utc)`
- **Decimal Precision:** Strong in engine.py and portfolio.py
- **Q-Learning:** Mathematically correct implementation
- **Cost Basis Tracking:** All edge cases (reversals, additions, reductions) handled correctly
- **Error Recovery:** Good defensive patterns in FSD learning pipeline

---

## PRIORITY CHECKLIST

Priority: **DO BEFORE NEXT TRADING SESSION**
- [ ] Fix Issue #1 (Edge case handler) - 2 minutes
- [ ] Fix Issue #2 (Error handling) - 15 minutes  
- [ ] Fix Issue #3 (Duplicate P&L) - 30 minutes

Nice to Have: **NEXT REFACTORING PASS**
- [ ] Fix Issue #4 (Float/Decimal conversion) - 5 minutes
- [ ] Fix Issue #5 (Position normalization) - 5 minutes
- [ ] Fix Issue #6 (Defensive check) - 2 minutes
- [ ] Fix Issue #7 (Timestamp validation) - 5 minutes

---

## TEST RECOMMENDATIONS

After fixes, run:
```bash
# Regression tests
pytest tests/test_critical_fixes_regression.py -v
pytest tests/test_engine_pnl.py -v
pytest tests/test_portfolio.py -v
pytest tests/test_engine_edge_cases.py -v

# Thread safety tests
pytest tests/test_concurrency_stress.py -v
```

