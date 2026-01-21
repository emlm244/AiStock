# AUDIT ISSUES TRACKER
## Quick Reference for Fixing Issues from Comprehensive Audit

**Last Updated:** November 5, 2025
**Total Issues:** 45 (10 CRITICAL, 12 HIGH, 15 MEDIUM, 8 LOW)

---

## ✅ CHECKLIST: CRITICAL ISSUES (Must Fix Before Trading)

### Thread Safety Issues
- [ ] **C-1** coordinator.py:256,317-318 - Add lock for `_order_submission_times` (10 min)
- [ ] **C-5** ibkr.py:288,306,391-394 - Add lock for `_market_handlers` (15 min)
- [ ] **C-6** ibkr.py:265,357,364 - Add lock for `_order_symbol` (10 min)
- [ ] **C-7** idempotency.py:50-73 - Fix file I/O race condition (5 min)
- [ ] **C-8** professional.py:84-85,360-361 - Add lock for `_trade_times` (10 min)

### Data Consistency Issues
- [ ] **C-2** coordinator.py:281-282 - Fix lost price update in `_handle_fill()` (15 min)
- [ ] **C-9** fsd.py:669 - Fix edge case handler parameter mismatch (2 min)
- [ ] **C-10** engine.py + portfolio.py - Address duplicate P&L calculation (30 min)

### Memory Leaks
- [ ] **C-3** analytics_reporter.py:30,56-58 - Bound `equity_curve` list (5 min)

### Data Loss Risks
- [ ] **C-4** coordinator.py:126-133 - Fix checkpoint shutdown window (5 min)

**Total Critical Fix Time:** ~2 hours

---

## ⚠️ CHECKLIST: HIGH SEVERITY ISSUES (Fix This Week)

### Memory & Resource Management
- [ ] **H-1** reconciliation.py:36,117,129 - Bound alerts list (5 min)
- [ ] **H-2** checkpointer.py:49-55,88-128 - Fix checkpoint queue race (10 min)

### Error Handling
- [ ] **H-3** portfolio.py:138-166 - Improve error recovery (20 min)

### Timezone & Validation
- [ ] **H-4** edge_cases.py:199-295 - Consistent timezone enforcement (30 min)
- [ ] **H-5** professional.py:307-340 - Add end-of-day timezone validation (10 min)
- [ ] **H-7** risk/engine.py:225-234 - Fix timestamp deserialization bug (15 min)
- [ ] **H-10** reconciliation.py:43-44,59-60 - Fix naive datetime check (15 min)

### Broker Integration
- [ ] **H-6** ibkr.py:362-371 vs paper.py:65-75 - Fix ExecutionReport consistency (1 hour)
- [ ] **H-8** ibkr.py:362-371 - Add partial fill aggregation (45 min)
- [ ] **H-9** ibkr.py:122-138 - Cancel orders on stop (20 min)

### Risk Management
- [ ] **H-11** risk/engine.py:158-168 - Fix per-trade cap for concurrent positions (45 min)

### Documentation
- [ ] **H-12** Multiple files - Add thread safety documentation (30 min)

**Total High Fix Time:** ~4 hours

---

## 📊 CHECKLIST: MEDIUM SEVERITY ISSUES (Next Sprint)

### Code Quality
- [ ] **M-1** fsd.py:1128-1131 - Remove float/Decimal round-trip (10 min)
- [ ] **M-2** fsd.py:854 - Make position normalization configurable (15 min)
- [ ] **M-10** engine.py:134-137 - Remove unnecessary defensive check (5 min)

### Performance
- [ ] **M-3** bar_processor.py:70-73 - Use deque for history trimming (20 min)

### Error Handling
- [ ] **M-4** analytics_reporter.py:64-95 - Improve exception handling (20 min)

### Configuration
- [ ] **M-5** edge_cases.py:227-228 - Make stale data threshold configurable (15 min)
- [ ] **M-7** edge_cases.py:258-259 - Make low volume threshold configurable (15 min)
- [ ] **M-9** config.py:177-186 - Add ExecutionConfig validation (20 min)

### Visibility
- [ ] **M-6** professional.py:114-130 - Collect all violations instead of early return (25 min)

### Risk Management
- [ ] **M-8** risk/engine.py:214-223 - Clarify halt status reset behavior (30 min)

**Total Medium Fix Time:** ~3 hours

---

## 📝 CHECKLIST: LOW SEVERITY ISSUES (Nice to Have)

- [ ] **L-1** engine.py - Add timestamp validation to Trade dataclass (10 min)
- [ ] **L-2** idempotency.py:50-89 - Use atomic writes (15 min)
- [ ] **L-3** Multiple files - Make hardcoded thresholds configurable (varies)
- [ ] **L-4** checkpointer.py:62-79,119-128 - Accept double checkpoint as-is (0 min)

**Total Low Fix Time:** ~1 hour

---

## 🧪 CHECKLIST: TEST COVERAGE GAPS (Next Sprint)

### Critical Test Gaps (High Priority)
- [ ] **T-1** Add coordinator integration tests (3 hours)
  - Full session lifecycle
  - Checkpoint recovery after crash
  - Concurrent bar processing with IBKR callbacks

- [ ] **T-2** Add broker integration tests (2 hours)
  - Limit order placement and cancellation
  - Partial fills and overfill rejection
  - Position tracking across multiple fills

- [ ] **T-3** Add FSD engine lifecycle tests (2 hours)
  - Q-learning convergence
  - Session start/end lifecycle
  - Handle_fill P&L calculation

- [ ] **T-4** Add risk engine edge case tests (1 hour)
  - Drawdown recovery and reset
  - Order timestamp validation
  - Pre-market position carry-forward

- [ ] **T-5** Add session/checkpointer stress tests (1 hour)
  - Async checkpoint queue under high load
  - Signal handler (SIGINT/SIGTERM) integration
  - Checkpoint file corruption recovery

### Test Quality Fixes
- [ ] **T-6** Fix test_coordinator_regression.py line 188 placeholder (30 min)
- [ ] **T-7** Add assertions to test_edge_cases.py (15 min)
- [ ] **T-8** Fix test_broker.py ExecutionConfig parameters (10 min)

**Total Test Fix Time:** ~10 hours

---

## 📈 PROGRESS TRACKING

### By Severity
- [ ] Critical: 0/10 fixed (0%)
- [ ] High: 0/12 fixed (0%)
- [ ] Medium: 0/15 fixed (0%)
- [ ] Low: 0/8 fixed (0%)
- [ ] Tests: 0/8 fixed (0%)

### By Category
- [ ] Thread Safety: 0/5 fixed (0%)
- [ ] Data Consistency: 0/3 fixed (0%)
- [ ] Memory Leaks: 0/2 fixed (0%)
- [ ] Broker Integration: 0/3 fixed (0%)
- [ ] Configuration: 0/3 fixed (0%)
- [ ] Test Coverage: 0/8 fixed (0%)

### Total Progress
- **Issues Fixed:** 0/45 (0%)
- **Estimated Remaining Time:** 20 hours

---

## 🎯 RECOMMENDED FIX ORDER (By Priority)

### Day 1 (2 hours) - Critical Thread Safety
1. C-1: coordinator._order_submission_times lock
2. C-5: ibkr._market_handlers lock
3. C-6: ibkr._order_symbol lock
4. C-7: idempotency file I/O race
5. C-8: professional._trade_times lock

### Day 2 (2 hours) - Critical Data & Memory
6. C-2: coordinator lost price update
7. C-3: analytics equity_curve bound
8. C-4: checkpoint shutdown order
9. C-9: fsd edge case parameters
10. C-10: duplicate P&L calculation

### Day 3 (4 hours) - High Severity
11. H-1 through H-6: Memory, timezone, broker issues
12. H-7 through H-12: Risk management and documentation

### Day 4-5 (10 hours) - Tests & Medium Issues
13. T-1 through T-5: Critical test gaps
14. M-1 through M-9: Code quality and configuration

---

## 📋 VALIDATION CHECKLIST

After each fix, run relevant tests:

### Thread Safety Fixes (C-1, C-5, C-6, C-7, C-8)
```bash
pytest tests/test_concurrency_stress.py -v
pytest tests/test_portfolio_threadsafe.py -v
```

### Data Consistency Fixes (C-2, C-9, C-10)
```bash
pytest tests/test_engine_pnl.py -v
pytest tests/test_critical_fixes_regression.py -v
```

### Memory Leak Fixes (C-3, H-1)
```bash
# Manual memory profiling
python -c "from aistock.session.analytics_reporter import AnalyticsReporter; import sys; print(sys.getsizeof(AnalyticsReporter().equity_curve))"
```

### Timezone Fixes (H-4, H-5, H-7, H-10)
```bash
pytest tests/test_timezone_edge_cases.py -v
```

### Broker Fixes (H-6, H-8, H-9)
```bash
pytest tests/test_broker.py -v
# Add new broker integration tests
```

### Full Regression Suite
```bash
pytest tests/test_critical_fixes_regression.py -v
pytest tests/test_engine_pnl.py -v
pytest tests/test_timezone_edge_cases.py -v
pytest tests/test_coordinator_regression.py -v
pytest tests/test_professional_integration.py -v
```

---

## 🔍 ISSUE LOOKUP BY FILE

### coordinator.py
- C-1 (lines 256, 317-318): _order_submission_times race
- C-2 (lines 281-282): Lost price update
- C-4 (lines 126-133): Checkpoint shutdown window

### ibkr.py
- C-5 (lines 288, 306, 391-394): _market_handlers race
- C-6 (lines 265, 357, 364): _order_symbol race
- H-6 (lines 362-371): ExecutionReport inconsistency
- H-8 (lines 362-371): No partial fill aggregation
- H-9 (lines 122-138): No order cancellation on stop

### fsd.py
- C-9 (line 669): Edge case handler parameters
- M-1 (lines 1128-1131): Float/Decimal round-trip
- M-2 (line 854): Hardcoded normalization

### portfolio.py
- C-10 (lines 138-166): Duplicate P&L calculation
- H-3 (lines 138-166): Incomplete error recovery

### analytics_reporter.py
- C-3 (lines 30, 56-58): Unbounded equity_curve
- M-4 (lines 64-95): Exception swallowing

### idempotency.py
- C-7 (lines 50-73): File I/O race
- L-2 (lines 50-89): Missing atomic writes

### professional.py
- C-8 (lines 84-85, 360-361): Missing thread lock
- H-5 (lines 307-340): End-of-day timezone validation
- M-6 (lines 114-130): Early return hides violations

### risk/engine.py

- H-7 (lines 225-234): Timestamp deserialization
- H-11 (lines 158-168): Per-trade cap ignores concurrent positions
- M-8 (lines 214-223): Halt status reset behavior

### edge_cases.py
- H-4 (lines 199-295): Inconsistent timezone enforcement
- M-5 (lines 227-228): Stale data threshold hardcoded
- M-7 (lines 258-259): Low volume threshold hardcoded

### reconciliation.py
- H-1 (lines 36, 117, 129): Unbounded alerts list
- H-10 (lines 43-44, 59-60): Naive datetime check

### checkpointer.py
- H-2 (lines 49-55, 88-128): Checkpoint queue race

### config.py
- M-9 (lines 177-186): ExecutionConfig missing validate()

---

## 📞 QUICK REFERENCE

**Critical Issues:** Fix in 2 hours before next trading session
**High Issues:** Fix in 4 hours this week
**Medium Issues:** Fix in 3 hours next sprint
**Low Issues:** Fix in 1 hour as time permits
**Test Gaps:** Address in 10 hours over next sprint

**Total Estimated Fix Time:** 20 hours

---

**For detailed descriptions of each issue, see:** `COMPREHENSIVE_CODEBASE_AUDIT_2025.md`
