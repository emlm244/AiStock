# State Management & Concurrency Edge Cases Audit

**AIStock Trading System - 2025-11-03**

## EXECUTIVE SUMMARY

Conducted comprehensive exploration of state management and concurrency across:
- Threading & locks (Portfolio, RiskEngine, CheckpointManager, TimeframeManager, BarProcessor)
- Idempotency tracking (TTL boundaries, duplicate detection, concurrent submissions)
- Checkpoint/persistence (atomic writes, worker lifecycle)
- Shared state (Portfolio, RiskEngine, Coordinator consistency)
- Queue-based workers (Checkpoint worker shutdown, sentinel handling)

**Critical Issues Found: 2**
**High Priority Issues Found: 5**
**Medium Priority Issues Found: 2**
**Test Coverage Gaps: 14+ scenarios**

---

## CRITICAL ISSUES

### Issue 1: CLOCK JUMP IN IDEMPOTENCY (CRITICAL)

**File**: aistock/idempotency.py:146-149

**Problem**: No guard against negative age_ms when system clock jumps backward
- If clock adjusted backward (NTP correction): age_ms becomes negative
- Example: submitted_ts_ms=1000, current_ts_ms=800 after clock jump
- age_ms = -200, comparison: -200 < 300000 returns True (incorrect)

**Recommended Fix**: 
```python
age_ms = current_ts_ms - submitted_ts_ms
if age_ms < 0:
    return True  # Conservative: treat as duplicate if clock jumped
return age_ms < self.expiration_ms
```

**Impact**: Order duplication during NTP correction events
**Test Status**: NOT COVERED

---

### Issue 2: DOUBLE SHUTDOWN DEADLOCK (CRITICAL)

**File**: aistock/session/checkpointer.py:89-119

**Problem**: shutdown() not idempotent - second call may timeout/hang
- First shutdown sends sentinel successfully
- Second shutdown tries to put(None) again
- If queue full, put() times out after 2s
- Sentinel never queued, join() may hang forever

**Recommended Fix**: Add _shutdown_in_progress flag
```python
def shutdown(self):
    if self._shutdown_in_progress:
        return
    self._shutdown_in_progress = True
    # ... rest of shutdown
```

**Impact**: Graceful termination may hang
**Test Status**: NOT COVERED

---

## HIGH PRIORITY ISSUES

### Issue 3: WORKER THREAD CRASH LOSS

**File**: aistock/session/checkpointer.py:58-87

**Problem**: Unhandled exception in worker causes immediate exit without processing remaining queue
- Remaining checkpoint items permanently lost
- join() in shutdown() waits forever for task_done() calls that never come

**Recommended Fix**: Wrap in try/finally to ensure task_done() on all items

**Impact**: Trading history/state not persisted
**Test Status**: NOT COVERED

---

### Issue 4: SENTINEL PUT TIMEOUT

**File**: aistock/session/checkpointer.py:100-103

**Problem**: Queue.Full exception not retried during shutdown
- If queue full with pending checkpoints, put(None, timeout=2.0) times out
- Sentinel never queued, join() hangs

**Recommended Fix**: Drain queue before putting sentinel or increase timeout with retry logic

**Impact**: shutdown() hangs indefinitely
**Test Status**: NOT COVERED

---

### Issue 5: TIMEZONE COERCION (HIGH)

**File**: aistock/edge_cases.py:219, 275

**Problem**: Uses replace(tzinfo=...) instead of astimezone()
- Naive datetime + replace() = silent 5-hour error on non-UTC machines
- Example: "10:00 EST" naive -> replace(tz=UTC) = "10:00 UTC" (wrong!)

**Recommended Fix**: Use astimezone() or reject naive timestamps

**Impact**: Stale data checks off by 5+ hours
**Test Status**: PARTIALLY COVERED

---

### Issue 6: BROKER FAILURE TRACKING GAP

**File**: aistock/session/coordinator.py:250-256

**Problem**: If record_order_submission() fails after broker.submit():
- Order IS in market
- But NOT in rate limiting
- NOT persisted to idempotency
- Restart may duplicate order

**Recommended Fix**: Wrap both in try/except with error logging

**Impact**: Silent order duplication on restart
**Test Status**: NOT COVERED

---

## MEDIUM PRIORITY ISSUES

### Issue 7: PORTFOLIO LOCK CONTENTION

**File**: aistock/portfolio.py:97-281

**Problem**: Single lock for all operations, high contention under 1000+ ops/sec

**Test Status**: NOT COVERED - missing stress test

---

### Issue 8: ORDER SUBMISSION TIMES UNPROTECTED

**File**: aistock/session/coordinator.py:73, 256, 318

**Problem**: Dictionary accessed without lock (single-threaded currently, but fragile)

**Test Status**: OK for now (single-threaded), but document assumption

---

## TESTING GAPS

### Critical Stress Tests Missing:

1. **Idempotency**
   - [ ] Clock jump backward (NTP correction)
   - [ ] Order at exactly TTL boundary
   - [ ] Corrupted idempotency file
   - [ ] Concurrent tracker instances

2. **Checkpoint Worker**
   - [ ] Worker thread crash (unhandled exception)
   - [ ] Double shutdown() calls
   - [ ] Queue saturation during shutdown
   - [ ] Broker failure + persistence failure

3. **High-Frequency**
   - [ ] 1000 bars/second ingestion
   - [ ] 100 concurrent order submissions
   - [ ] Checkpoint queue full scenario

4. **Timezone**
   - [ ] Non-UTC bar timestamps
   - [ ] Mixed naive/aware timestamps
   - [ ] Daylight savings transition

---

## DETAILED FINDINGS BY COMPONENT

### Portfolio (SAFE)
- Lock() correctly wraps all operations
- Position copies returned (defensive)
- Thread-safe under normal load
- Stress test needed: concurrent fills + equity reads

### RiskEngine (SAFE)
- RLock() correctly used
- All critical methods protected
- Thread-safe
- Stress test needed: concurrent halt() calls

### CheckpointManager (UNSAFE - has 3 issues)
- Sentinel mechanism correct
- task_done() called correctly
- ISSUES: #2 (double shutdown), #3 (worker crash), #4 (sentinel timeout)

### TimeframeManager (SAFE)
- Lock correctly protects add_bar() + get_bars()
- Bars copied under lock before calculations
- Thread-safe
- Stress test needed: 1000 bars/sec

### BarProcessor (SAFE)
- Lock protects history + prices
- Copies returned
- Thread-safe
- Stress test needed: concurrent process_bar() + warmup()

### OrderIdempotencyTracker (SAFE with issue #1)
- Lock correctly protects reads/writes
- Disk persistence atomic
- ISSUE: #1 (no clock jump guard)

### Coordinator (MOSTLY SAFE with issue #6)
- Portfolio/RiskEngine thread-safe
- ISSUE: #6 (broker failure tracking)
- Timing: uses wall-clock for submission (correct!)

### EdgeCaseHandler (UNSAFE - issue #5)
- Uses replace(tzinfo=) - dangerous!
- Should use astimezone() like reconciliation.py

### Persistence (SAFE)
- Global lock protects writes
- Atomic temp file + rename
- Good pattern

---

## RECOMMENDATIONS

### CRITICAL (fix immediately):
1. Add negative age check in idempotency.py:146
2. Make shutdown() idempotent (add flag)
3. Wrap _worker_loop() in try/finally
4. Test broker failure paths

### HIGH (fix in next release):
1. Sentinel put() timeout handling
2. Timezone coercion audit
3. Worker health monitoring

### MEDIUM (next sprint):
1. Stress tests (1000 bars/sec, 100 concurrent orders)
2. Clock jump detection
3. Documentation updates

---

## FILES WITH CONCURRENCY ISSUES

- aistock/idempotency.py - Issue #1
- aistock/session/checkpointer.py - Issues #2, #3, #4
- aistock/edge_cases.py - Issue #5
- aistock/session/coordinator.py - Issues #6, #8
- aistock/portfolio.py - Issue #7

---

## FILES THAT ARE THREAD-SAFE (verified)

- aistock/portfolio.py (Lock correctly used)
- aistock/risk/engine.py (RLock correctly used)
- aistock/timeframes.py (Lock correctly used)
- aistock/session/bar_processor.py (Lock correctly used)
- aistock/session/reconciliation.py (No locks needed, validated inputs)
- aistock/persistence.py (Global lock correctly used)

