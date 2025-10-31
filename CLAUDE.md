# CLAUDE.md

This file provides guidance to Claude Code when working with the AIStock trading system.

## Project Overview

**AIStock Robot v2.x** – Autonomous trading system powered by Reinforcement Learning (Q-Learning) in Full Self-Driving (FSD) mode. Current focus: reliable, local-only operation with performance improvements.

### Core Architecture (4 Layers)

1. **FSD RL Agent** (`aistock/fsd.py`) - Q-Learning decision engine
2. **Professional Trading** (`aistock/timeframes.py`, `aistock/patterns.py`, `aistock/professional.py`)
3. **Risk & Portfolio** (`aistock/risk.py`, `aistock/portfolio.py`)
4. **Broker Integration** (`aistock/brokers/`) - Paper trading + Interactive Brokers (IBKR)

### Key Design Principles

- FSD-only architecture
- Defensive stack: edge cases → professional safeguards → risk engine → minimum balance
- Graceful degradation instead of crash-or-stop
- Idempotent orders for crash-safe deduplication
- Safety caps configurable in the GUI (daily loss/drawdown, trade count, chase/news thresholds)
- **Backlog:** IBKR callbacks still mutate shared state directly; queue-based handoff planned

---

## Quick Start

### Running the Application

```bash
# Launch FSD GUI (friendly control panel)
python -m aistock

# Example: quick paper trading run
python -m aistock --broker paper --symbols AAPL --capital 10000
```

### Testing

```bash
# Run all tests (requires pytest to be installed)
python -m pytest tests/ -v

# Run with minimal traceback
python -m pytest -v --tb=line

# Stop on first failure
python -m pytest -v --tb=short -x
```

### Code Quality

```bash
# Ruff/pyright are optional. Install first if needed:
# pip install ruff pyright
ruff check aistock/
pyright aistock/
```

---

## Project Status (2025-10-31 - Corrected Assessment)

### Current State
- **Architecture**: FSD-only, local operation, defensive 4-layer stack
- **October 30 Fixes**: ✅ Thread safety, atomic writes, Decimal conversion, position reconciliation implemented
- **Code Quality**: Strong foundations with proper defensive patterns

### Production Readiness Assessment (Corrected)
- ✅ **Paper Trading**: Ready - Safe to run and test
- ⚠️ **Live Trading**: Use extreme caution - Start small ($1K-2K) with conservative parameters

### What's Actually Implemented (Verified)
1. ✅ **Thread Safety** - Session, portfolio, timeframes all use proper locking
2. ✅ **Decimal Arithmetic** - Money calculations use Decimal end-to-end
3. ✅ **Atomic Persistence** - State files use atomic writes with backups
4. ✅ **Connection Resilience** - Heartbeat monitoring with auto-reconnect
5. ✅ **Position Reconciliation** - Explicit reconciliation method implemented
6. ✅ **Q-table Bounds** - LRU eviction at 10K states
7. ✅ **Order Timeouts** - 5-second timeout on order ID receipt
8. ✅ **Zero-Division Checks** - Indicators check for zero denominators

### Recommended Approach
- **Paper Trading**: Continue testing, monitor for any edge cases
- **Live Trading**: Start conservatively:
  - Initial capital: $1K-2K (NOT $10K)
  - Single symbol (AAPL)
  - Conservative FSD params (learning_rate=0.0001, min_confidence=0.8)
  - Manual monitoring for first week
  - Scale gradually based on actual performance

See `CODE_REVIEW_FIXES_IMPLEMENTATION_COMPLETE.md` for details on October 30 fixes.

---

## Configuration

### Environment Variables (.env)

**Required:**
```bash
IBKR_ACCOUNT_ID=DU1234567  # Paper (DU*) or Live (U*)
IBKR_CLIENT_ID=1001        # Unique per bot instance (REQUIRED - no default)
```

**Optional:**
```bash
IBKR_TWS_HOST=127.0.0.1
IBKR_TWS_PORT=7497         # Paper: 7497, Live: 7496
LOG_LEVEL=INFO
```

**Setup:**
```bash
cp .env.example .env
# Edit .env with your details
```

---

## FSD Decision Pipeline

```
Market Data → TimeframeManager → PatternDetector → FSDEngine
→ ProfessionalSafeguards → EdgeCaseHandler → RiskEngine → Order Execution
```

**Key Files:**
- `aistock/fsd.py` - Q-Learning agent
- `aistock/session.py` - Pipeline orchestrator
- `aistock/execution.py` - Order management

---

## Thread Safety Notes

- Core components (`portfolio`, `risk`, `timeframes`, `fsd`) use explicit locks; keep hold time short.
- IBKR callbacks currently invoke session methods directly—moving to a queue-based handoff is the next planned improvement.
- Professional safeguards now honour user-specified hard caps; the bot will refuse trades that violate them.
- Snapshot state where possible instead of holding locks across component boundaries.

### Example Pattern

```python
import threading

class MyComponent:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}

    def read_state(self):
        with self._lock:
            return self._state.copy()  # Return copy, not reference

    def write_state(self, key, value):
        with self._lock:
            self._state[key] = value
```

---

## Common Development Tasks

### Adding a New Safeguard

1. Add check to `aistock/professional.py:ProfessionalSafeguards.check()`
2. Return `TradingSafeguardResult` with risk level
3. Add test to `tests/test_professional_integration.py`

### Adding a Candlestick Pattern

1. Add detection to `aistock/patterns.py:PatternDetector`
2. Return `PatternSignal` (BULLISH, BEARISH, NEUTRAL)
3. Add test to `tests/test_professional_integration.py`
4. Pattern detector is thread-safe - no special handling needed

### Modifying FSD Parameters

**Key parameters in `aistock/fsd.py:FSDConfig`:**
- `learning_rate` (0.001) - Learning speed
- `discount_factor` (0.95) - Future reward weighting
- `exploration_rate` (0.1) - Random action frequency
- `min_confidence_threshold` (0.6) - Minimum confidence to trade

**Test changes:**
```bash
python -m pytest tests/test_fsd.py -v
python scripts/generate_synthetic_dataset.py
```

---

## Critical Patterns

### 1. Decimal for Money (Required)

```python
from decimal import Decimal

# WRONG
price = 100.50  # ❌ Float precision issues

# RIGHT
price = Decimal('100.50')  # ✅ Exact decimal
quantity = Decimal('10')
cost = price * quantity
```

### 2. IBKR Callback Pattern (Required)

```python
# WRONG: Direct state modification
def realtimeBar(self, ...):
    self.portfolio.update(...)  # ❌ Thread-safety issue

# RIGHT: Queue events
def realtimeBar(self, ...):
    self.bar_queue.put((reqId, time, open_, high, low, close, volume))
```

### 3. Type Annotations (Required)

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fsd import FSDEngine  # Avoid circular imports
```

---

## IBKR Connection Debugging

**Common Issues:**
1. TWS/Gateway not running → Start TWS first
2. Wrong port → Paper: 7497, Live: 7496
3. API not enabled → TWS Settings → API → Enable ActiveX and Socket Clients
4. Account ID mismatch → Check `.env` IBKR_ACCOUNT_ID

**Test connection:**
```bash
python test_ibkr_connection.py
cat .env | grep IBKR
```

---

## Critical Warnings

**DO NOT:**
1. Use BackTrader (we have custom engine)
2. Force trades (deadline feature removed)
3. Skip edge case checks
4. Bypass risk engine
5. Use floats for money (use Decimal)
6. Modify IBKR callbacks directly (use queues)
7. Hardcode timeframes (use TimeframeManager)
8. Modify shared state without locks
9. Hold locks during expensive operations
10. Save checkpoints synchronously (use queue)
11. Acquire locks in IBKR callbacks
12. Violate lock hierarchy

---

## Performance Budget

**Latency (25ms total budget):**
- Timeframe aggregation: 2ms
- Pattern detection: 5ms
- FSD decision: 10ms
- Risk checks: 1ms
- Order submission: 2ms
- Lock overhead: ~3ms
- **Total:** ~24-25ms ✅

**Memory:**
- Q-value table: ~10K states
- Multi-timeframe bars: Bounded by warmup period
- Pattern cache: 1000 entries max (LRU)

---

## Documentation

**User Docs:**
- `README.md` - Overview, quick start
- `START_HERE.md` - First-time setup
- `IBKR_REQUIREMENTS_CHECKLIST.md` - IBKR setup

**Technical Docs:**
- `docs/FSD_COMPLETE_GUIDE.md` - FSD deep dive and implementation details
- `CODE_REVIEW_FIXES_IMPLEMENTATION_COMPLETE.md` - Improvements implemented (2025-10-30)

---

## Production Deployment

**Current Status:** ⚠️ Use caution with live trading - Start small and conservative

**Paper Trading** (Safe):
```bash
python -m aistock --broker paper --symbols AAPL --capital 10000
```

**Live Trading Recommendations:**
1. **Start Small**: $1K-2K initial capital (NOT $10K)
2. **Single Symbol**: AAPL only initially
3. **Conservative Parameters**:
   - `learning_rate=0.0001` (very slow learning)
   - `min_confidence_threshold=0.8` (high confidence required)
4. **Paper Trading First**: 1-2 weeks successful paper trading
5. **Manual Monitoring**: Watch every trade for first week
6. **Scale Gradually**: Only increase capital after proven success

**Conservative Production Config:**
```json
{
  "fsd": {
    "learning_rate": 0.0001,
    "min_confidence_threshold": 0.8,
    "exploration_rate": 0.05
  },
  "risk": {
    "max_position_pct": 0.05,
    "max_concurrent_positions": 1,
    "minimum_balance_enabled": true,
    "max_daily_loss_pct": 0.02
  },
  "symbols": ["AAPL"],
  "initial_capital": 1000
}
```

**Recent Improvements (Oct 30, 2025):**
- ✅ Thread-safe portfolio and session
- ✅ Atomic state persistence with backups
- ✅ Decimal arithmetic end-to-end
- ✅ Connection resilience with heartbeat monitoring
- ✅ Position reconciliation
- ✅ Order timeouts
- ✅ Q-table bounds with LRU eviction

See `CODE_REVIEW_FIXES_IMPLEMENTATION_COMPLETE.md` for details.
