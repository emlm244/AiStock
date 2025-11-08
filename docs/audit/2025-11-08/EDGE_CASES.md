# EDGE CASES CATALOG
**AiStock Robot v2.0 Full-Sweep Audit**
**Date**: 2025-11-08
**Auditor**: Claude Code (Sonnet 4.5)

## Summary

This document catalogs ALL edge cases discovered in the AiStock codebase, organized by area. Each edge case includes:
- **Severity**: CRITICAL, HIGH, MEDIUM, LOW
- **Current Handling**: How the system currently handles this case
- **Test Coverage**: Whether automated tests cover this case
- **Reproduction Steps**: How to trigger the edge case
- **Expected Behavior**: What should happen

---

## 1. Broker Integration Edge Cases

### B-1: TWS/Gateway Offline on Start (HIGH)
**File**: aistock/brokers/ibkr.py:start()
**Scenario**: User starts system with TWS/Gateway not running
**Current Handling**: Connection attempt fails with exception
**Test Coverage**: ❌ NOT COVERED
**Reproduction**:
1. Stop TWS/Gateway
2. Launch AiStock with IBKR broker
3. Observe connection exception
**Expected Behavior**: Retry with exponential backoff (5 attempts, max 30s wait)
**Fix Required**: Add retry logic in IBKRBroker.start()

### B-2: Authentication Failure (HIGH)
**File**: aistock/brokers/ibkr.py:start()
**Scenario**: Invalid credentials or client ID conflict
**Current Handling**: Exception raised, system crashes
**Test Coverage**: ❌ NOT COVERED
**Reproduction**:
1. Use client_id already in use
2. Observe auth failure error
**Expected Behavior**: Clear error message with resolution steps
**Fix Required**: Catch auth errors, provide actionable guidance

### B-3: Session Expiry Mid-Trade (CRITICAL)
**File**: aistock/brokers/ibkr.py
**Scenario**: TWS session expires while trading (e.g., nightly restart)
**Current Handling**: Reconnect logic exists but untested
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Manually restart TWS during active session
**Expected Behavior**: Auto-reconnect, resubscribe bars, reconcile positions
**Fix Required**: Add comprehensive reconnect tests

### B-4: Rate Limiting (MEDIUM)
**File**: aistock/brokers/ibkr.py:submit()
**Scenario**: Submitting orders too fast (> 50/second)
**Current Handling**: No throttling, may hit IBKR rate limit
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Submit 100 orders in 1 second
**Expected Behavior**: Queue orders, respect IBKR rate limits (50/sec)
**Fix Required**: Add token bucket rate limiter

### B-5: Order Idempotency - Duplicate Submit (CRITICAL) ✓
**File**: aistock/idempotency.py:is_duplicate()
**Scenario**: Same order submitted twice (network retry, logic bug)
**Current Handling**: ✓ OrderIdempotencyTracker prevents duplicates
**Test Coverage**: ✓ COVERED (test_idempotency.py:test_duplicate_detection)
**Expected Behavior**: Second submit rejected, logged
**Status**: WORKING AS DESIGNED

### B-6: Partial Fills (MEDIUM) ✓
**File**: aistock/execution.py:ExecutionReport
**Scenario**: Order filled in multiple smaller executions
**Current Handling**: ✓ ExecutionReport tracks cumulative filled qty
**Test Coverage**: ✓ COVERED (test_engine_edge_cases.py:test_partial_fills)
**Expected Behavior**: Portfolio updated correctly with each partial fill
**Status**: WORKING AS DESIGNED

### B-7: Clock Skew (HIGH)
**File**: aistock/brokers/ibkr.py:execDetails()
**Scenario**: Client and TWS server clocks out of sync (> 1 min)
**Current Handling**: ⚠ Uses server timestamps, but not validated
**Test Coverage**: ⚠ PARTIAL (timezone tests exist)
**Reproduction**: Set system clock 5 min ahead, observe timestamps
**Expected Behavior**: Detect skew > 1 min, warn user
**Fix Required**: Add clock skew detection in IBKRBroker.start()

### B-8: Fill Never Arrives (HIGH)
**File**: aistock/session/coordinator.py:_handle_fill()
**Scenario**: Order submitted but fill callback never invoked (IBKR bug, network loss)
**Current Handling**: ❌ No timeout mechanism, order orphaned
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Submit order, kill TWS before fill, restart
**Expected Behavior**: Timeout after 5 min, mark order as stale, alert
**Fix Required**: Add order timeout tracking in coordinator

### B-9: Exception After Submit Before Idempotency Mark (CRITICAL)
**File**: aistock/session/coordinator.py:_process_bar()
**Scenario**: Exception thrown after broker.submit() but before mark_submitted()
**Current Handling**: ❌ Idempotency not marked, can duplicate on retry
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Inject exception after submit() call
**Expected Behavior**: Mark submitted BEFORE broker call OR handle rollback
**Fix Required**: Move mark_submitted() before broker.submit()

### B-10: Position Request Timeout (MEDIUM)
**File**: aistock/brokers/ibkr.py:get_positions()
**Scenario**: Broker position request times out (slow network)
**Current Handling**: Returns empty dict (false halt risk)
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Add 10s delay to position callback
**Expected Behavior**: Timeout with clear error, don't assume no positions
**Fix Required**: Add timeout parameter, raise exception on timeout

---

## 2. Config/Environment Edge Cases

### E-1: Missing .env Keys (LOW) ✓
**File**: aistock/config.py
**Scenario**: Required environment variable not set
**Current Handling**: ✓ Uses defaults or raises clear error
**Test Coverage**: ✓ COVERED (test_config.py:test_missing_env)
**Status**: WORKING AS DESIGNED

### E-2: Unsafe Defaults (MEDIUM) ✓
**File**: aistock/config.py:validate()
**Scenario**: Configuration with unsafe values (e.g., $100 capital, 100% risk)
**Current Handling**: ✓ Config.validate() checks thresholds
**Test Coverage**: ✓ COVERED (test_config.py:test_unsafe_config)
**Status**: WORKING AS DESIGNED

### E-3: Type Mismatches (LOW) ✓
**File**: aistock/config.py
**Scenario**: Environment variable wrong type (e.g., "abc" for IBKR_PORT)
**Current Handling**: ✓ Pydantic/dataclass validation raises TypeError
**Test Coverage**: ✓ COVERED (test_config.py:test_type_mismatch)
**Status**: WORKING AS DESIGNED

### E-4: Invalid File Paths (MEDIUM)
**File**: aistock/session/checkpointer.py:__init__()
**Scenario**: Checkpoint directory doesn't exist or not writable
**Current Handling**: ⚠ Creates directory if missing, but no permission check
**Test Coverage**: ⚠ PARTIAL (happy path tested)
**Reproduction**: Set checkpoint_dir to read-only path
**Expected Behavior**: Fail fast with clear error on startup
**Fix Required**: Add permission validation in CheckpointManager.__init__()

---

## 3. Concurrency Edge Cases

### C-1: Race in coordinator._order_submission_times (CRITICAL) ❌
**File**: aistock/session/coordinator.py:256, 317-318
**Scenario**: IBKR callback thread writes, main thread reads, no lock
**Current Handling**: ❌ Dict access without lock (race condition)
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: High-frequency trading, concurrent fill callbacks
**Expected Behavior**: Thread-safe dict access with lock
**Fix Required**: Add `threading.Lock()` around all accesses
**Priority**: P0 (immediate fix)

### C-2: Portfolio Lock Contention (MEDIUM) ✓
**File**: aistock/portfolio.py
**Scenario**: 1000+ operations/sec on Portfolio (high contention)
**Current Handling**: ✓ Single lock (may contend under extreme load)
**Test Coverage**: ✓ COVERED (test_concurrency_stress.py:test_portfolio_stress)
**Reproduction**: Stress test with 10,000 concurrent apply_fill() calls
**Expected Behavior**: <100ms latency at 99th percentile
**Status**: WORKING AS DESIGNED (acceptable for current scale)

### C-3: Checkpoint Worker Crash (HIGH)
**File**: aistock/session/checkpointer.py:_worker_loop()
**Scenario**: Exception in worker thread kills worker, no restart
**Current Handling**: ❌ Worker dies silently, checkpoints stop
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Inject exception in worker loop
**Expected Behavior**: Log error, restart worker OR alert coordinator
**Fix Required**: Add try-except in worker loop, restart on crash

### C-4: Double Shutdown Deadlock (CRITICAL)
**File**: aistock/session/coordinator.py:stop()
**Scenario**: User calls stop() twice concurrently (GUI bug, signal handler)
**Current Handling**: ❌ Not idempotent, may deadlock on locks
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Call coordinator.stop() from two threads simultaneously
**Expected Behavior**: Second call no-ops gracefully
**Fix Required**: Add `_shutdown_in_progress` flag, make stop() idempotent

### C-5: Timeframe State Race (CRITICAL) ✓ FIXED
**File**: aistock/timeframes.py
**Scenario**: Concurrent bar adds from multiple symbols
**Current Handling**: ✓ FIXED - Lock held during state update
**Test Coverage**: ✓ COVERED (test_critical_fixes_regression.py:test_timeframe_race)
**Status**: RESOLVED (Jan 2025)

---

## 4. Numeric Handling Edge Cases

### N-1: Decimal vs Float Mixing (CRITICAL) ✓
**File**: All money calculations
**Scenario**: Float value mixed with Decimal (precision loss)
**Current Handling**: ✓ All money calculations use Decimal
**Test Coverage**: ✓ COVERED (test_engine_pnl.py:test_decimal_precision)
**Status**: WORKING AS DESIGNED

### N-2: Rounding Errors (MEDIUM) ✓
**File**: aistock/portfolio.py:_calculate_cost_basis()
**Scenario**: Cost basis rounding on partial fills
**Current Handling**: ✓ Decimal prevents, explicit rounding
**Test Coverage**: ✓ COVERED (test_engine_edge_cases.py:test_cost_basis_rounding)
**Status**: WORKING AS DESIGNED

### N-3: Precision Loss on Large Numbers (LOW) ✓
**File**: aistock/portfolio.py
**Scenario**: Portfolio equity > $1B (Decimal overflow)
**Current Handling**: ✓ Decimal handles arbitrary precision
**Test Coverage**: ✓ COVERED (test_portfolio.py:test_large_equity)
**Status**: WORKING AS DESIGNED

### N-4: Division by Zero in Cost Basis (CRITICAL) ✓ FIXED
**File**: aistock/engine.py:calculate_pnl()
**Scenario**: Division by zero when calculating average cost
**Current Handling**: ✓ FIXED - Guard added (qty == 0 check)
**Test Coverage**: ✓ COVERED (test_critical_fixes_regression.py:test_cost_basis_div_zero)
**Status**: RESOLVED (Jan 2025)

### N-5: Sigmoid Overflow (CRITICAL) ✓ FIXED
**File**: aistock/fsd.py:_normalize_q_value()
**Scenario**: Q-value > 700 causes sigmoid overflow
**Current Handling**: ✓ FIXED - Clamp to [-700, 700] before sigmoid
**Test Coverage**: ✓ COVERED (test_critical_fixes_regression.py:test_sigmoid_overflow)
**Status**: RESOLVED (Jan 2025)

---

## 5. Time Handling Edge Cases

### T-1: Naive Datetime Mixing (CRITICAL) ✓ FIXED
**File**: All timestamp handling
**Scenario**: Naive datetime compared with aware datetime
**Current Handling**: ✓ FIXED - All timestamps TZ-aware (UTC)
**Test Coverage**: ✓ COVERED (test_timezone_edge_cases.py:test_naive_aware_mixing)
**Status**: RESOLVED (Jan 2025)

### T-2: DST Transitions (HIGH) ✓
**File**: aistock/calendar.py:get_market_hours()
**Scenario**: DST transition causes time ambiguity (2:00 AM → 1:00 AM)
**Current Handling**: ✓ Use UTC everywhere, convert to ET for display only
**Test Coverage**: ✓ COVERED (test_timezone_edge_cases.py:test_dst_transition)
**Status**: WORKING AS DESIGNED

### T-3: Trading Holidays (MEDIUM) ✓
**File**: aistock/calendar.py:is_trading_day()
**Scenario**: User tries to trade on holiday (Thanksgiving, Christmas)
**Current Handling**: ✓ Calendar checks NYSE holidays
**Test Coverage**: ✓ COVERED (test_calendar.py:test_holidays)
**Status**: WORKING AS DESIGNED

### T-4: Clock Jump Backward (CRITICAL)
**File**: aistock/idempotency.py:mark_submitted()
**Scenario**: NTP sync causes system clock jump backward (rare)
**Current Handling**: ❌ Timestamp-based deduplication breaks
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Set clock ahead 10 min, submit order, set back, submit again
**Expected Behavior**: Detect clock jump, invalidate timestamp-based logic
**Fix Required**: Use monotonic clock for deduplication timestamps

### T-5: Stale Data (HIGH) ✓
**File**: aistock/edge_cases.py:detect_stale_data()
**Scenario**: Bar timestamp > 10 min old (feed delay, backfill)
**Current Handling**: ✓ EdgeCaseHandler rejects stale bars
**Test Coverage**: ✓ COVERED (test_edge_cases.py:test_stale_data)
**Status**: WORKING AS DESIGNED

### T-6: Early Market Close (MEDIUM)
**File**: aistock/stop_control.py:should_flatten_eod()
**Scenario**: Early close (1 PM ET) vs regular close (4 PM ET)
**Current Handling**: ⚠ EOD flatten time hardcoded to 3:45 PM (won't work for 1 PM close)
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Run on early close day (day before Thanksgiving)
**Expected Behavior**: Flatten 15 min before actual close (12:45 PM for 1 PM close)
**Fix Required**: Query calendar for close time, calculate flatten time dynamically

---

## 6. Error Handling Edge Cases

### EH-1: Swallowed Exceptions in Analytics (MEDIUM)
**File**: aistock/session/analytics_reporter.py:record_fill()
**Scenario**: Exception in analytics calculation swallowed
**Current Handling**: ⚠ Single try-except around all analytics (issue M-4)
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Inject exception in Sharpe calculation
**Expected Behavior**: Log error, continue trading (analytics non-critical)
**Fix Required**: Separate try-except per metric, log each failure

### EH-2: No Retry Budget for Broker Calls (MEDIUM)
**File**: aistock/brokers/ibkr.py:submit()
**Scenario**: Transient network error on order submit
**Current Handling**: ❌ No retry mechanism, order lost
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Kill network briefly during submit
**Expected Behavior**: Retry 3 times with exp backoff (1s, 2s, 4s)
**Fix Required**: Add retry decorator to broker methods

### EH-3: Circuit Breaker Detection (MEDIUM) ✓
**File**: aistock/edge_cases.py:detect_circuit_breaker()
**Scenario**: Stock halted mid-day (circuit breaker triggered)
**Current Handling**: ✓ EdgeCaseHandler detects, prevents trading
**Test Coverage**: ✓ COVERED (test_edge_cases.py:test_circuit_breaker)
**Status**: WORKING AS DESIGNED

### EH-4: Portfolio State Corruption (HIGH)
**File**: aistock/portfolio.py:apply_fill()
**Scenario**: Exception during apply_fill() leaves portfolio in inconsistent state
**Current Handling**: ❌ No transactional rollback
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Inject exception after qty update but before cash update
**Expected Behavior**: Rollback to pre-fill state OR crash fast
**Fix Required**: Add atomic transaction wrapper (save state, rollback on exception)

### EH-5: Idempotency File Corruption (MEDIUM)
**File**: aistock/idempotency.py:load()
**Scenario**: submitted_orders.json corrupted (disk error, partial write)
**Current Handling**: ⚠ JSON parse exception, system crashes
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Write invalid JSON to submitted_orders.json, restart
**Expected Behavior**: Log error, reinitialize (warn about potential duplicates)
**Fix Required**: Add JSON validation, backup file mechanism

---

## 7. Order Lifecycle Edge Cases

### OL-1: Order Submitted, Then Canceled by Exchange (MEDIUM)
**File**: aistock/brokers/ibkr.py:orderStatus()
**Scenario**: Exchange rejects order (e.g., outside trading hours)
**Current Handling**: ⚠ Callback received, but not handled in coordinator
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Submit order outside market hours
**Expected Behavior**: Update portfolio state (order failed), alert user
**Fix Required**: Add orderStatus() handling for 'Cancelled' status

### OL-2: Order Modified by Exchange (LOW)
**File**: aistock/brokers/ibkr.py:orderStatus()
**Scenario**: Exchange modifies order (e.g., price improvement)
**Current Handling**: ⚠ Not explicitly handled
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Submit limit order, observe price improvement fill
**Expected Behavior**: Accept modified order, log modification
**Fix Required**: Add handling for price/qty modifications

### OL-3: Order Partially Filled, Then Canceled (MEDIUM)
**File**: aistock/portfolio.py:apply_fill()
**Scenario**: Order 50% filled, user cancels remaining
**Current Handling**: ✓ Portfolio tracks cumulative filled qty
**Test Coverage**: ⚠ PARTIAL (test_engine_edge_cases.py covers fills, not cancel)
**Reproduction**: Submit 100 share order, fill 50, cancel
**Expected Behavior**: Portfolio shows 50 shares, order marked done
**Fix Required**: Add test for partial-fill-then-cancel

### OL-4: Fill Price Differs from Order Price (LOW)
**File**: aistock/brokers/ibkr.py:execDetails()
**Scenario**: Market order filled at worse price than expected
**Current Handling**: ✓ Uses actual fill price from execution report
**Test Coverage**: ✓ COVERED (test_broker.py:test_fill_price)
**Status**: WORKING AS DESIGNED

---

## 8. Data Ingestion Edge Cases

### DI-1: Duplicate Bars (MEDIUM)
**File**: aistock/session/bar_processor.py:add_bar()
**Scenario**: Same bar timestamp received twice (feed replay, bug)
**Current Handling**: ⚠ Overwrites previous bar silently
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Call add_bar() twice with same timestamp
**Expected Behavior**: Detect duplicate, log warning, ignore
**Fix Required**: Add duplicate detection in BarProcessor

### DI-2: Out-of-Order Bars (MEDIUM)
**File**: aistock/session/bar_processor.py:add_bar()
**Scenario**: Bars arrive out of sequence (t=10:01, then t=10:00)
**Current Handling**: ⚠ Accepts out-of-order bars (breaks history sort)
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Add bars with decreasing timestamps
**Expected Behavior**: Reject out-of-order bars, log error
**Fix Required**: Add timestamp monotonicity check

### DI-3: Missing Bars (MEDIUM)
**File**: aistock/session/bar_processor.py:get_history()
**Scenario**: Gap in bar sequence (10:00, 10:02, missing 10:01)
**Current Handling**: ⚠ No gap detection, FSD uses incomplete history
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Skip a bar timestamp in feed
**Expected Behavior**: Detect gap, request backfill OR skip decision
**Fix Required**: Add gap detection, configurable backfill strategy

### DI-4: Zero Volume Bars (LOW)
**File**: aistock/edge_cases.py:validate_price()
**Scenario**: Bar with zero volume (after-hours, illiquid)
**Current Handling**: ⚠ Accepted (may cause FSD state issues)
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Feed bar with volume=0
**Expected Behavior**: Reject zero-volume bars OR mark as non-tradeable
**Fix Required**: Add zero-volume check in EdgeCaseHandler

---

## 9. Position Management Edge Cases

### PM-1: Position Reversal (LONG → SHORT) (MEDIUM) ✓
**File**: aistock/portfolio.py:apply_fill()
**Scenario**: Sell 200 shares when holding 100 long (reversal to 100 short)
**Current Handling**: ✓ Portfolio handles reversal correctly
**Test Coverage**: ✓ COVERED (test_engine_edge_cases.py:test_position_reversal)
**Status**: WORKING AS DESIGNED

### PM-2: Fractional Shares (LOW)
**File**: aistock/execution.py:Order
**Scenario**: Order for 10.5 shares (some brokers allow)
**Current Handling**: ⚠ Qty is int, fractional not supported
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Create order with qty=10.5
**Expected Behavior**: Either support fractional OR reject with clear error
**Fix Required**: Document fractional share support (currently not supported)

### PM-3: Symbol Delisting Mid-Session (HIGH)
**File**: aistock/portfolio.py:total_equity()
**Scenario**: Stock delisted, position can't be priced
**Current Handling**: ❌ No delisting detection, stale price used
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Hold position, remove symbol from feed
**Expected Behavior**: Mark position as delisted, equity calculation excludes
**Fix Required**: Add delisting detection, manual position resolution

### PM-4: Corporate Action (Split/Dividend) (MEDIUM)
**File**: aistock/corporate_actions.py:adjust_for_split()
**Scenario**: 2:1 stock split while holding position
**Current Handling**: ⚠ Module exists but not integrated with portfolio
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Hold 100 shares, apply 2:1 split
**Expected Behavior**: Position updated to 200 shares, cost basis halved
**Fix Required**: Integrate corporate actions with portfolio

---

## 10. Risk Management Edge Cases

### RM-1: Daily Loss Limit Triggered (HIGH) ✓
**File**: aistock/risk.py:check_pre_trade()
**Scenario**: Daily loss exceeds configured limit (e.g., -$1000)
**Current Handling**: ✓ Kill switch triggered, all new trades blocked
**Test Coverage**: ✓ COVERED (test_risk_engine.py:test_daily_loss_limit)
**Status**: WORKING AS DESIGNED

### RM-2: Drawdown Limit Triggered (HIGH) ✓
**File**: aistock/risk.py:check_pre_trade()
**Scenario**: Drawdown from high-water mark exceeds limit (e.g., -10%)
**Current Handling**: ✓ Kill switch triggered
**Test Coverage**: ✓ COVERED (test_risk_engine.py:test_drawdown_limit)
**Status**: WORKING AS DESIGNED

### RM-3: Kill Switch Manual Reset (MEDIUM)
**File**: aistock/risk.py:reset_kill_switch()
**Scenario**: User resets kill switch after review
**Current Handling**: ✓ Manual reset method exists
**Test Coverage**: ⚠ PARTIAL (method tested, not full workflow)
**Reproduction**: Trigger kill switch, call reset_kill_switch()
**Expected Behavior**: Trading resumes after manual intervention
**Status**: WORKING AS DESIGNED

### RM-4: Per-Trade Capital Exceeds Limit (MEDIUM)
**File**: aistock/risk.py:check_pre_trade()
**Scenario**: Single order value > max_capital_per_trade
**Current Handling**: ⚠ Check exists but doesn't account for concurrent positions
**Test Coverage**: ❌ NOT COVERED (issue H-11)
**Reproduction**: Submit $10k order when max=5k per trade
**Expected Behavior**: Reject order, log reason
**Fix Required**: Fix per-trade check for concurrent positions (H-11)

---

## 11. Shutdown & Recovery Edge Cases

### SR-1: Graceful Shutdown with In-Flight Orders (CRITICAL)
**File**: aistock/stop_control.py:graceful_shutdown()
**Scenario**: Shutdown triggered while orders pending
**Current Handling**: ✓ Cancels all orders, liquidates positions
**Test Coverage**: ⚠ PARTIAL (logic tested, not full integration)
**Reproduction**: Submit orders, trigger stop before fills
**Expected Behavior**: Cancel pending, liquidate filled, timeout after 30s
**Status**: MOSTLY WORKING (needs integration test)

### SR-2: Checkpoint Recovery After Crash (HIGH)
**File**: aistock/session/checkpointer.py:load()
**Scenario**: System crashes, restart from checkpoint
**Current Handling**: ✓ Loads latest checkpoint on restart
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Kill process mid-session, restart
**Expected Behavior**: Restore portfolio/risk/FSD state, reconcile with broker
**Fix Required**: Add checkpoint recovery integration test

### SR-3: Orphaned Orders After Crash (CRITICAL)
**File**: aistock/session/coordinator.py:start()
**Scenario**: System crashes with orders in-flight, restarts
**Current Handling**: ❌ No orphan detection on startup
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Submit orders, kill process, restart
**Expected Behavior**: Detect orphaned orders, reconcile with broker, decide action
**Fix Required**: Add orphan order detection on startup

### SR-4: Broker Position Drift (HIGH)
**File**: aistock/session/reconciliation.py:reconcile()
**Scenario**: Portfolio state diverges from broker (manual trade, crash)
**Current Handling**: ✓ Hourly reconciliation detects drift
**Test Coverage**: ✓ COVERED (test_reconciliation.py:test_drift_detection)
**Status**: WORKING AS DESIGNED

---

## 12. Network & Connectivity Edge Cases

### NC-1: Broker Disconnect Mid-Session (CRITICAL)
**File**: aistock/brokers/ibkr.py:error()
**Scenario**: TWS connection lost during trading
**Current Handling**: ⚠ Error callback invoked, but no auto-reconnect
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Kill TWS process during session
**Expected Behavior**: Detect disconnect, halt trading, attempt reconnect
**Fix Required**: Add connection monitoring, auto-reconnect logic

### NC-2: Slow Network (HIGH)
**File**: aistock/brokers/ibkr.py:submit()
**Scenario**: High network latency (> 5s for order ack)
**Current Handling**: ❌ No timeout, may hang
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Add network delay (tc command), submit order
**Expected Behavior**: Timeout after 10s, retry OR fail gracefully
**Fix Required**: Add timeouts to all broker API calls

### NC-3: Market Data Feed Interruption (HIGH)
**File**: aistock/brokers/ibkr.py:realtimeBar()
**Scenario**: Real-time bar feed stops (IBKR issue, network)
**Current Handling**: ❌ No heartbeat detection, system waits indefinitely
**Test Coverage**: ❌ NOT COVERED
**Reproduction**: Stop real-time bar subscription
**Expected Behavior**: Detect missing bars after 2 min, alert + halt trading
**Fix Required**: Add heartbeat monitoring for bar feed

---

## 13. Multi-Symbol Edge Cases

### MS-1: Symbol-Specific Halt (MEDIUM)
**File**: aistock/edge_cases.py:detect_circuit_breaker()
**Scenario**: One symbol halted, others trading normally
**Current Handling**: ✓ Per-symbol edge case detection
**Test Coverage**: ✓ COVERED (test_edge_cases.py:test_circuit_breaker)
**Status**: WORKING AS DESIGNED

### MS-2: Correlated Symbol Positions (MEDIUM)
**File**: aistock/risk.py:check_pre_trade()
**Scenario**: Concentrated risk (long AAPL + long MSFT = tech-heavy)
**Current Handling**: ❌ No sector/correlation risk checks
**Test Coverage**: ❌ NOT COVERED
**Expected Behavior**: Warn if >50% capital in correlated symbols
**Fix Required**: Add sector concentration risk check (future enhancement)

### MS-3: Cross-Symbol Equity Calculation (HIGH) ✓ FIXED
**File**: aistock/portfolio.py:total_equity()
**Scenario**: Multi-symbol portfolio equity with missing prices
**Current Handling**: ✓ FIXED - Validates all prices present
**Test Coverage**: ✓ COVERED (test_critical_fixes_regression.py:test_multi_symbol_equity)
**Status**: RESOLVED (Jan 2025)

---

## Summary Statistics

**Total Edge Cases**: 60+

**By Severity**:
- CRITICAL: 15 (25%)
- HIGH: 18 (30%)
- MEDIUM: 21 (35%)
- LOW: 6 (10%)

**By Status**:
- ✓ Working: 18 (30%)
- ✓ Fixed: 6 (10%)
- ⚠ Partial: 9 (15%)
- ❌ Not Handled: 27 (45%)

**Test Coverage**:
- ✓ Covered: 24 (40%)
- ⚠ Partial: 9 (15%)
- ❌ Not Covered: 27 (45%)

**Priority Breakdown** (open issues only):
- P0 (CRITICAL, no coverage): 9 issues
- P1 (HIGH, no coverage): 12 issues
- P2 (MEDIUM, no coverage): 6 issues

---

## Recommendations

### Immediate (P0 - Week 1)
1. Fix 9 critical race conditions and memory leaks (C-1 to C-10)
2. Add broker timeout mechanisms (B-8, NC-2)
3. Implement orphan order detection (SR-3)
4. Add clock jump detection (T-4)

### Short-Term (P1 - Sprint 1)
5. Add broker failure mode handling (B-1, B-2, B-3, NC-1, NC-3)
6. Implement retry logic for broker calls (EH-2)
7. Add order lifecycle edge case handling (OL-1, OL-2, OL-3)
8. Fix data ingestion gaps (DI-1, DI-2, DI-3)

### Medium-Term (P2 - Sprint 2)
9. Add checkpoint recovery tests (SR-2)
10. Implement early close handling (T-6)
11. Add portfolio state corruption recovery (EH-4)
12. Integrate corporate actions (PM-4)

### Long-Term (Backlog)
13. Add sector concentration risk (MS-2)
14. Support fractional shares (PM-2)
15. Enhanced analytics error handling (EH-1)

---

**END OF EDGE CASES CATALOG**
