# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AIStock Robot v2.0** is a Full Self-Driving (FSD) AI trading system powered by Q-Learning reinforcement learning. The system makes autonomous trading decisions, learns from every trade, and adapts its strategy over time. It supports both paper trading and live trading via Interactive Brokers (IBKR).

**Key Characteristics:**
- Pure FSD mode (removed BOT and Supervised modes in v2.0)
- Custom trading engine (no BackTrader dependency)
- Thread-safe architecture for IBKR callbacks
- Comprehensive edge case handling and professional safeguards
- Multi-timeframe analysis and pattern recognition

---

## Development Commands

### Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Install dev dependencies (for testing)
pip install -r requirements-dev.txt  # if exists
```

### Running the Application
```bash
# Launch GUI (FSD Mode)
python -m aistock

# Test FSD import
python -c "from aistock.fsd import FSDEngine; print('✅ OK')"
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_engine_pnl.py

# Run with verbose output
pytest -v tests/

# Run with coverage
pytest --cov=aistock tests/
```

### Important Test Files
- `tests/test_critical_fixes_regression.py` - Regression tests for critical P&L and timezone bugs
- `tests/test_engine_edge_cases.py` - Edge case validation
- `tests/test_concurrency_stress.py` - Concurrent access stress tests
- `tests/test_broker_failure_modes.py` - Broker failure handling

---

## Architecture Overview

### Core Components

**1. FSD Engine (`aistock/fsd.py`)**
- Q-Learning RL agent for autonomous trading decisions
- State extraction from market data (price changes, volume, trends, volatility)
- Multi-timeframe analysis integration
- Per-symbol performance tracking and adaptive confidence
- Thread-safe Q-value updates (concurrent IBKR callback protection)

**2. Trading Engine (`aistock/engine.py`)**
- Custom execution engine (replaced BackTrader)
- P&L calculation using cost basis tracking
- Critical: Uses **entry price** (cost basis) for realized P&L, NOT last known price
- Handles position reversals, partial fills, weighted average cost

**3. Portfolio (`aistock/portfolio.py`)**
- Thread-safe position tracking (Lock-protected for IBKR callbacks)
- Realized/unrealized P&L calculation
- Average entry price tracking

**4. Trading Coordinator (`aistock/session/coordinator.py`)**
- Lightweight orchestrator (does NOT do component work)
- Routes bars through pipeline
- Handles order submission and fills
- Coordinates checkpointing, reconciliation, analytics

**5. Risk Engine (`aistock/risk.py`)**
- Pre-trade risk checks (position limits, daily loss, drawdown)
- Order rate limiting
- Kill switch protection
- Thread-safe accounting

**6. Brokers (`aistock/brokers/`)**
- `paper.py` - Paper trading broker with realistic simulation
- `ibkr.py` - Interactive Brokers TWS/Gateway integration
- Both use `ExecutionConfig` for setup

**7. Professional Modules**
- `timeframes.py` - Multi-timeframe correlation analysis
- `patterns.py` - Candlestick pattern recognition
- `professional.py` - Trading safeguards (halt detection, cooldown)
- `edge_cases.py` - Edge case detection (stale data, volatility spikes, low liquidity)

**8. Session Components (`aistock/session/`)**
- `bar_processor.py` - Bar ingestion and history management
- `checkpointer.py` - Async checkpoint saves (async queue)
- `reconciliation.py` - Position reconciliation with broker
- `analytics_reporter.py` - Performance analytics

---

## Critical Implementation Details

### 1. P&L Calculation (CRITICAL - Fixed in Recent Commits)

**The Realized P&L Bug (Fixed):**
Prior to commit `da36960`, the TradingEngine calculated realized P&L using the **last known price** instead of the **entry price (cost basis)**. This made ALL analytics invalid.

**Correct Implementation:**
```python
# aistock/engine.py:100-110
if current_position > 0:
    # Closing long: profit = (exit_price - entry_price) * qty
    realised_pnl = closed_qty * (price - current_basis)
else:
    # Closing short: profit = (entry_price - exit_price) * qty
    realised_pnl = closed_qty * (current_basis - price)
```

**Testing:** `tests/test_engine_pnl.py` validates this fix.

### 2. Timezone Discipline (CRITICAL - Fixed in Recent Commits)

**All datetime objects MUST be timezone-aware (UTC).**

**Common Issues:**
- `datetime.now()` → WRONG
- `datetime.now(timezone.utc)` → CORRECT
- Naive timestamps cause `TypeError` in edge case handlers and professional safeguards

**Key Locations:**
- IBKR broker uses `fromtimestamp(_, tz=timezone.utc)`
- Paper broker receives timestamps from coordinator (which uses UTC)
- All test fixtures use `tzinfo=timezone.utc`

**Testing:** `tests/test_timezone_edge_cases.py` validates timezone handling.

### 3. Idempotency (Order Deduplication)

**System:** `OrderIdempotencyTracker` (`aistock/idempotency.py`)

**Critical Fix (Commit `225a596`):**
Order idempotency checks MUST happen **before** risk accounting, not after. Otherwise, duplicate orders bypass rate limits.

**Correct Flow:**
1. Generate `client_order_id` (deterministic hash)
2. Check idempotency tracker
3. If duplicate, reject immediately
4. If not duplicate, perform risk checks
5. Submit order
6. Mark as submitted in tracker

**Key Detail:** Uses **submission time** (wall-clock UTC), NOT bar time, for TTL expiration.

### 4. Thread Safety

**Concurrent Access Points:**
- IBKR callbacks run on separate thread
- Portfolio, RiskEngine, FSDEngine use `threading.Lock`

**Protected Operations:**
- Portfolio position updates (`aistock/portfolio.py:96`)
- Q-value updates (`aistock/fsd.py:170`)
- Risk accounting (`aistock/risk.py`)

### 5. Checkpoint System

**Implementation:** `CheckpointManager` (`aistock/session/checkpointer.py`)

**Critical Fix (Commit `3ef7d68`):**
Checkpoint saves are async (queued) to avoid blocking trade execution. Must drain queue on shutdown to prevent data loss.

**Atomic Writes:**
Uses `_atomic_write_json()` to prevent corruption on crash (writes to temp file, then renames).

**Signal Handling:**
`aistock/__main__.py` registers `SIGINT`/`SIGTERM` handlers to drain checkpoint queue on CTRL+C.

### 6. Cost Basis Tracking (Position Management)

**Key Scenarios:**
- **Opening:** Cost basis = entry price
- **Adding:** Weighted average cost basis
- **Reducing:** Cost basis unchanged
- **Reversal (crossing zero):** Cost basis reset to new entry price
- **Full close:** Cost basis deleted

**Edge Case:** Must check for reversals BEFORE checking magnitude increase (otherwise reversals that also increase magnitude are misclassified).

```python
# aistock/engine.py:120-124
# Check reversal FIRST (before magnitude comparison)
if (current_position > 0 and new_position < 0) or (current_position < 0 and new_position > 0):
    # REVERSAL: reset cost basis
    self.cost_basis[symbol] = price
```

---

## Configuration System

### Key Config Classes (`aistock/config.py`)

**1. `FSDConfig`** (`aistock/fsd.py:36`)
- Learning parameters (learning_rate, discount_factor, exploration_rate)
- Constraints (max_capital, min_confidence_threshold)
- Advanced features (max_concurrent_positions, per-symbol adaptation)
- Volatility bias ('balanced', 'high', 'low')
- **MUST call `.validate()` before use**

**2. `RiskLimits`** (`aistock/config.py:50`)
- Daily loss limits, drawdown limits
- Position sizing limits
- Order rate limits
- Kill switch settings
- **MUST call `.validate()` before use**

**3. `BacktestConfig`** (composition of DataSource, RiskLimits, ExecutionConfig, etc.)

---

## Testing Strategy

### Test Organization
- `tests/test_*.py` - Unit tests for each module
- `tests/test_*_regression.py` - Regression tests for critical bugs
- `tests/test_*_edge_cases.py` - Edge case validation
- `tests/test_*_stress.py` - Concurrency and stress tests

### Running Regression Tests (Important!)
After any changes to engine, portfolio, or risk modules:
```bash
pytest tests/test_critical_fixes_regression.py -v
pytest tests/test_engine_pnl.py -v
pytest tests/test_timezone_edge_cases.py -v
```

### Testing with Paper Broker
```python
from aistock.config import ExecutionConfig
from aistock.brokers.paper import PaperBroker

config = ExecutionConfig(slippage_bps=5.0, latency_ms=100.0)
broker = PaperBroker(config)  # NOT PaperBroker() - config is required!
```

---

## Common Patterns

### 1. Creating an FSD Trading Session
```python
from aistock.fsd import FSDEngine, FSDConfig
from aistock.portfolio import Portfolio

config = FSDConfig()
config.validate()  # Always validate!

portfolio = Portfolio(initial_cash=Decimal('10000'))
fsd = FSDEngine(config, portfolio)

# Start session
fsd.start_session()

# Evaluate opportunity
decision = fsd.evaluate_opportunity(symbol, bars, last_prices)

# Handle fill
fsd.handle_fill(symbol, timestamp, fill_price, realized_pnl, signed_qty, pos_before, pos_after)

# End session
fsd.end_session()
```

### 2. State Persistence
```python
# Save FSD state (Q-values, statistics)
fsd.save_state('state/fsd_state.json')

# Load FSD state
fsd.load_state('state/fsd_state.json')
```

### 3. Risk Checking
```python
from aistock.risk import RiskEngine
from aistock.config import RiskLimits

limits = RiskLimits()
limits.validate()  # Always validate!

risk = RiskEngine(limits, initial_equity=Decimal('10000'))

# Pre-trade check
risk.check_pre_trade(symbol, quantity_delta, price, current_equity, last_prices, timestamp)

# Register trade
risk.register_trade(realized_pnl, commission, timestamp, current_equity, last_prices)
```

---

## Code Style & Conventions

### Decimal Usage
- **All currency/price/quantity values use `Decimal`** (not float)
- Convert to Decimal at boundaries: `Decimal(str(value))`
- Convert to float only for display or numpy operations

### Datetime Usage
- **Always use timezone-aware datetimes** (`datetime.now(timezone.utc)`)
- Never use naive datetimes
- Bar timestamps may be naive-UTC (industry standard) - use `.replace(tzinfo=timezone.utc)` if needed

### Type Hints
- Use type hints throughout
- Use `from __future__ import annotations` for forward references
- Use `TYPE_CHECKING` for circular import avoidance

### Error Handling
- Validate config objects before use (`.validate()`)
- Use descriptive error messages
- Log errors with context (symbol, timestamp, values)

---

## Recent Critical Fixes (Reference)

| Date | Commit | Fix |
|------|--------|-----|
| 2025-11-02 | da36960 | **CRITICAL:** TradingEngine realized P&L used last price instead of entry price |
| 2025-11-02 | adbe19f | **CRITICAL:** Idempotency TTL uses submission time, not bar time |
| 2025-11-02 | 225a596 | Idempotency check BEFORE risk accounting (prevents rate limit bypass) |
| 2025-11-02 | 3ef7d68 | Checkpoint queue drain on shutdown (prevents data loss) |
| 2025-11-01 | e36fe4d | Timezone enforcement (naive datetime rejection) |
| 2025-11-01 | 4dd8c4f | Integration tools for P&L fix workflow |

**See:** `FINAL_AUDIT_REPORT.md`, `CODE_REVIEW_FIXES.md`, `EDGE_CASE_FIXES_SUMMARY.md` for full details.

---

## Known Assumptions & Design Decisions

1. **Bar timestamps are naive-UTC** (industry standard for data feeds)
   - IBKR confirmed to use UTC
   - Paper broker uses coordinator's timestamps (UTC)

2. **Single-threaded bar processing** (coordinator processes bars sequentially)
   - Only IBKR callbacks are multi-threaded
   - Portfolio/Risk/FSD use locks for callback safety

3. **Q-value table is unlimited** (no LRU eviction)
   - Trades are infrequent (~30s intervals)
   - Memory usage is minimal for realistic scenarios

4. **Idempotency TTL is 30 seconds** (configurable)
   - Based on submission time (wall-clock), not bar time
   - Prevents duplicate orders from retries

5. **Cost basis tracking uses weighted average** (for adding to positions)
   - Matches industry standard accounting
   - Reversals reset cost basis

---

## Interactive Brokers (IBKR) Integration

### Setup Requirements
See `IBKR_REQUIREMENTS_CHECKLIST.md` for full setup guide.

### Connection Testing
```bash
python test_ibkr_connection.py
```

### Key Configuration
- TWS/Gateway must be running locally (localhost:7497 for paper, 7496 for live)
- Enable API connections in TWS settings
- Use correct client ID (avoid conflicts with other connections)

---

## File Organization

```
aistock/
├── fsd.py              # FSD RL Agent (CORE)
├── engine.py           # Custom trading engine
├── portfolio.py        # Position tracking (thread-safe)
├── risk.py             # Risk management
├── config.py           # Configuration classes
├── data.py             # Bar and market data structures
├── execution.py        # Order and execution report models
├── idempotency.py      # Order deduplication
├── calendar.py         # Trading hours validation
├── timeframes.py       # Multi-timeframe analysis
├── patterns.py         # Candlestick patterns
├── professional.py     # Professional safeguards
├── edge_cases.py       # Edge case detection
├── session/            # Session orchestration
│   ├── coordinator.py  # Main coordinator
│   ├── bar_processor.py
│   ├── checkpointer.py
│   ├── reconciliation.py
│   └── analytics_reporter.py
├── brokers/            # Broker integrations
│   ├── base.py
│   ├── paper.py
│   └── ibkr.py
└── simple_gui.py       # FSD GUI interface
```

---

## When Making Changes

### Before Committing
1. **Run regression tests:** `pytest tests/test_critical_fixes_regression.py -v`
2. **Validate configs:** Ensure `.validate()` is called on all config objects
3. **Check thread safety:** Any new shared state needs locks
4. **Check timezone:** All `datetime.now()` should be `datetime.now(timezone.utc)`
5. **Check Decimal usage:** Currency/price/quantity should use `Decimal`

### When Adding Features
1. **Consider edge cases:** Add to `edge_cases.py` if applicable
2. **Add tests:** Follow existing test patterns
3. **Update CLAUDE.md:** Document new patterns or critical details
4. **Validate performance:** FSD warmup should complete in <10s for 1000 bars

### When Fixing Bugs
1. **Add regression test first** (test-driven fix)
2. **Document in commit message** (reference issue number if applicable)
3. **Update relevant docs** (CLAUDE.md, README.md if user-facing)

---

## Debugging Tips

### Common Issues

**Issue:** `TypeError: can't subtract offset-naive and offset-aware datetimes`
- **Fix:** Use `datetime.now(timezone.utc)` instead of `datetime.now()`

**Issue:** P&L doesn't match expected values
- **Check:** Is cost basis being updated correctly? (see `aistock/engine.py:99-143`)
- **Test:** Run `pytest tests/test_engine_pnl.py -v`

**Issue:** Orders being rejected as duplicates
- **Check:** Idempotency TTL may be too long, or order generation is non-deterministic
- **Debug:** Check `state/submitted_orders.json`

**Issue:** Checkpoint data loss on crash
- **Check:** Is `checkpointer.shutdown()` being called? (signal handlers registered?)
- **Debug:** Check for `SIGINT`/`SIGTERM` handler in `__main__.py`

**Issue:** Thread safety violations
- **Check:** Are Portfolio/RiskEngine/FSDEngine updates using locks?
- **Test:** Run `pytest tests/test_concurrency_stress.py -v`

---

## Resources

- **Main README:** `README.md` - User-facing quick start
- **FSD Guide:** `docs/FSD_COMPLETE_GUIDE.md` - Technical deep dive
- **IBKR Setup:** `IBKR_REQUIREMENTS_CHECKLIST.md` - Broker connection guide
- **Audit Report:** `FINAL_AUDIT_REPORT.md` - Recent fixes and validation
- **Edge Cases:** `EDGE_CASE_FIXES_SUMMARY.md` - Edge case handling details
