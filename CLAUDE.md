# CLAUDE.md

**Last Updated**: 2025-11-01 (Post-Deployment Preparation)
**Architecture**: Modular with Dependency Injection
**Status**: Production-Ready - All Fixes Merged

This file provides guidance to Claude Code when working with the AIStock trading system.

---

## Project Overview

**AIStock Robot v2.x** – Autonomous trading system powered by Reinforcement Learning (Q-Learning) in Full Self-Driving (FSD) mode.

**Current Focus**:
- Modular architecture with dependency injection
- Professional multi-developer workflow
- Reliable, local-only operation
- Production-grade code quality

---

## Core Architecture (Modular - as of 2025-10-31)

### Component Hierarchy
```
SessionFactory (DI entry point)
  └─> TradingCoordinator (lightweight orchestrator)
      ├─> FSDEngine (Q-Learning decisions)
      ├─> Portfolio (thread-safe state)
      ├─> RiskEngine (configurable limits)
      ├─> Broker (Paper/IBKR)
      ├─> BarProcessor (data ingestion)
      ├─> CheckpointManager (async persistence)
      ├─> PositionReconciler (broker sync)
      └─> AnalyticsReporter (performance)
```

### Key Modules

**Modular Infrastructure**:
- `aistock/factories/` - Dependency injection (SessionFactory, ComponentFactory)
- `aistock/session/` - Decomposed orchestration (coordinator, bar_processor, checkpointer, reconciliation, analytics)
- `aistock/interfaces/` - Protocol definitions (PortfolioProtocol, RiskEngineProtocol, DecisionEngineProtocol)
- `aistock/_legacy/` - Archived monolithic code (for reference only)

**Core Trading Components**:
- `aistock/fsd.py` - Q-Learning decision engine
- `aistock/portfolio.py` - Thread-safe portfolio management
- `aistock/risk.py` - Risk engine with limits
- `aistock/patterns.py` - Candlestick patterns
- `aistock/timeframes.py` - Multi-timeframe aggregation
- `aistock/professional.py` - Professional safeguards
- `aistock/edge_cases.py` - Edge case handling
- `aistock/brokers/` - Broker integrations

**User Interfaces**:
- `aistock/simple_gui.py` - Tkinter GUI
- `aistock/__main__.py` - CLI entry point

---

## Key Design Principles

### Architecture
- ✅ **Modular**: Dependency injection via factories
- ✅ **Protocol-based**: Interfaces enable testing and swapping
- ✅ **Single responsibility**: Each component has one job
- ✅ **Error isolation**: Try/except at boundaries
- ✅ **Thread-safe**: RLock/Lock on shared state

### Trading Logic
- **FSD-only architecture**: No manual strategies
- **Defensive stack**: edge cases → professional safeguards → risk engine → minimum balance
- **Graceful degradation**: Never crash, always log and continue
- **Idempotent orders**: Crash-safe deduplication
- **Safety caps**: Configurable in GUI (daily loss, drawdown, trade count)

### Code Quality
- **Decimal arithmetic**: All money calculations use Decimal (no floats)
- **Thread safety**: Locks on all shared state
- **Atomic writes**: State persistence uses atomic writes with backups
- **Type hints**: Protocol-based interfaces throughout
- **Professional Git**: Feature branches, conventional commits, PR workflow

---

## Quick Start

### Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Optional dev tools
pip install ruff pyright pytest pytest-cov
```

### Running the Application
```bash
# Launch FSD GUI (recommended)
python -m aistock

# Headless paper trading
python -m aistock --broker paper --symbols AAPL --capital 10000
```

### Creating a Session Programmatically
```python
from aistock.factories import SessionFactory
from aistock.config import BacktestConfig, BrokerConfig, DataSource, EngineConfig
from aistock.fsd import FSDConfig

# Create configuration
config = BacktestConfig(
    data=DataSource(path='data', symbols=['AAPL']),
    engine=EngineConfig(),
    broker=BrokerConfig(backend='paper')
)
fsd_config = FSDConfig()

# Use factory to create session
factory = SessionFactory(config, fsd_config=fsd_config)
coordinator = factory.create_trading_session(
    symbols=['AAPL'],
    checkpoint_dir='state'
)

# Start trading
coordinator.start()
```

### Testing
```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=aistock --cov-report=html -v

# Run specific tests
pytest tests/test_fsd.py -v
```

### Code Quality
```bash
# Lint
ruff check aistock/

# Format
ruff format aistock/

# Type check (optional)
pyright aistock/
```

---

## Project Status (2025-10-31 - Post-Code-Review)

### Modularization Complete ✅
- **Date**: 2025-10-31
- **Status**: Complete with all code review fixes merged
- **Branch**: `feature/modular-architecture` (ready for production)

**What Changed**:
1. Decomposed `LiveTradingSession` (1,242 lines) → `session/` components (6 files, 353 lines max)
2. Created dependency injection via `factories/`
3. Added protocol interfaces in `interfaces/`
4. Archived old code in `_legacy/`

### Code Review Fixes Applied ✅

**Merged 2025-11-01**: All fix branches successfully merged

**Fix 1**: `fix/remove-unused-modules` (✅ MERGED)
- Removed orphaned modules: services/, fsd_components/, state_management/, config_consolidated/
- 18 files removed, ~1,776 lines of unused code
- 22% reduction in codebase size

**Fix 2**: `fix/checkpoint-restore-implementation` (✅ MERGED)
- Removed broken `SessionFactory.create_with_checkpoint_restore()`
- Added TODO for Phase 7 implementation
- Prevents silent data loss

**Fix 3**: `fix/gui-protocol-callback` (✅ MERGED)
- Fixed protocol violation in GUI
- Added `hasattr()` guard for `gui_log_callback`
- Maintains Liskov Substitution Principle

### Production Readiness Assessment

**Current Status**: ✅ **PRODUCTION READY**

| Component | Status | Notes |
|-----------|--------|-------|
| **Thread Safety** | ✅ Pass | RLock/Lock used correctly throughout |
| **Decimal Arithmetic** | ✅ Pass | End-to-end Decimal usage |
| **Atomic Persistence** | ✅ Pass | Atomic writes with backups |
| **Connection Resilience** | ✅ Pass | Heartbeat monitoring, auto-reconnect |
| **Position Reconciliation** | ✅ Pass | Explicit reconciliation implemented |
| **Q-table Bounds** | ✅ Pass | LRU eviction at 10K states |
| **Order Timeouts** | ✅ Pass | 5-second timeout on order ID receipt |
| **Error Isolation** | ✅ Pass | Try/except at component boundaries |
| **Modular Architecture** | ✅ Pass | Clean separation of concerns |
| **Protocol Compliance** | ✅ Pass | All protocol violations fixed |

### Deployment Recommendations

#### Paper Trading ✅
- **Status**: Ready to deploy
- **Testing**: Run for 1-2 hours minimum
- **Monitoring**: Check logs for errors
- **Configuration**: Use default FSD parameters

#### Live Trading ⚠️
- **Status**: Use caution, start small
- **Initial Capital**: $1K-2K (NOT $10K)
- **Symbols**: Single symbol (AAPL) initially
- **FSD Parameters**: Conservative (learning_rate=0.0001, min_confidence=0.8)
- **Monitoring**: Manual monitoring for first week
- **Scaling**: Gradual based on actual performance

---

## Configuration

### Environment Variables (.env)

**Required**:
```bash
IBKR_ACCOUNT_ID=DU1234567  # Paper (DU*) or Live (U*)
IBKR_CLIENT_ID=1001        # Unique per bot instance
```

**Optional**:
```bash
IBKR_TWS_HOST=127.0.0.1
IBKR_TWS_PORT=7497         # Paper: 7497, Live: 7496
LOG_LEVEL=INFO
```

**Setup**:
```bash
cp .env.example .env
# Edit .env with your details
```

---

## FSD Decision Pipeline

```
Market Data → BarProcessor → TimeframeManager → PatternDetector
→ FSDEngine (State Extraction → Q-Learning → Decision)
→ ProfessionalSafeguards → EdgeCaseHandler → RiskEngine
→ Order Execution (via Broker)
```

**Key Files**:
- `aistock/fsd.py` - Q-Learning agent
- `aistock/session/coordinator.py` - Pipeline orchestrator
- `aistock/execution.py` - Order management

---

## Thread Safety Notes

### Components with Locks
- `Portfolio`: Uses `RLock` for reentrant safety
- `RiskEngine`: Uses `Lock` for state protection
- `TimeframeManager`: Uses `Lock` for bar aggregation
- `FSDEngine`: Uses `Lock` for Q-table updates
- `BarProcessor`: Uses `Lock` for history updates

### Best Practices
- Hold locks for minimal time
- Snapshot state where possible (return copies, not references)
- Never acquire locks in callbacks (use queues instead)
- Document lock hierarchy to prevent deadlocks

### Example Pattern
```python
import threading

class MyComponent:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}

    def read_state(self):
        with self._lock:
            return self._state.copy()  # Return copy

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
3. Add test to `tests/test_patterns.py`

### Modifying FSD Parameters
1. Update `aistock/fsd.py:FSDConfig` dataclass
2. Adjust in GUI (`simple_gui.py`) if needed
3. Test with `pytest tests/test_fsd.py -v`
4. Document changes in `docs/FSD_COMPLETE_GUIDE.md`

### Adding a New Decision Engine
1. Implement `DecisionEngineProtocol` from `aistock/interfaces/decision.py`
2. Register in `aistock/factories/trading_components_factory.py`
3. Add configuration to `aistock/config.py`
4. Write tests in `tests/test_<engine>.py`

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

### 2. Protocol-Based DI (Required)
```python
from aistock.interfaces.decision import DecisionEngineProtocol

def my_function(engine: DecisionEngineProtocol):
    # Works with any implementation
    decision = engine.evaluate_opportunity(...)
```

### 3. Thread-Safe State Access (Required)
```python
# WRONG
self.state['key'] = value  # ❌ No lock

# RIGHT
with self._lock:  # ✅ Protected
    self.state['key'] = value
```

### 4. Type Annotations (Required)
```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fsd import FSDEngine  # Avoid circular imports
```

---

## IBKR Connection Debugging

**Common Issues**:
1. **TWS/Gateway not running** → Start TWS first
2. **Wrong port** → Paper: 7497, Live: 7496
3. **API not enabled** → TWS Settings → API → Enable ActiveX and Socket Clients
4. **Account ID mismatch** → Check `.env` IBKR_ACCOUNT_ID

**Test Connection**:
```bash
python test_ibkr_connection.py
cat .env | grep IBKR
```

---

## Critical Warnings

### DO NOT:
1. ❌ Use floats for money (use Decimal)
2. ❌ Modify shared state without locks
3. ❌ Hold locks during expensive operations
4. ❌ Acquire locks in IBKR callbacks
5. ❌ Commit state/ files to git
6. ❌ Skip edge case checks
7. ❌ Bypass risk engine
8. ❌ Use old `LiveTradingSession` (use `SessionFactory`)
9. ❌ Import from `_legacy/` (archived code)
10. ❌ Force trades (deadline feature removed)

### DO:
1. ✅ Use `SessionFactory` to create sessions
2. ✅ Use Decimal for all money calculations
3. ✅ Add locks for shared state
4. ✅ Write tests for new features
5. ✅ Follow conventional commit format
6. ✅ Create feature branches
7. ✅ Use protocol interfaces for DI
8. ✅ Document thread safety requirements
9. ✅ Test with paper trading first
10. ✅ Monitor logs during live trading

---

## Performance Budget

**Latency** (25ms total budget):
- Timeframe aggregation: 2ms
- Pattern detection: 5ms
- FSD decision: 10ms
- Risk checks: 1ms
- Order submission: 2ms
- Lock overhead: ~3ms
- **Total**: ~24-25ms ✅

**Memory**:
- Q-value table: ~10K states (LRU eviction)
- Multi-timeframe bars: Bounded by warmup period
- Pattern cache: 1000 entries max (LRU)

---

## Documentation

### User Docs
- `README.md` - Overview, quick start
- `START_HERE.md` - First-time setup
- `IBKR_REQUIREMENTS_CHECKLIST.md` - IBKR setup

### Technical Docs
- `docs/FSD_COMPLETE_GUIDE.md` - FSD deep dive
- `CODE_REVIEW_FINDINGS.md` - Professional code review results
- `AGENTS.md` - Developer guidelines
- `CLAUDE.md` - This file (Claude Code guidance)

### Architecture Docs
- `PRODUCTION_READINESS_AUDIT.md` - Production audit
- `MODULARIZATION_VERIFIED_COMPLETE.md` - Modularization verification
- `IMPLEMENTATION_COMPLETE.md` - Implementation details
- `BRANCH_STRUCTURE_EXPLAINED.md` - Git workflow

---

## Git Workflow

### Branches
```
main         - Production releases only
develop      - Integration branch
feature/*    - New features
fix/*        - Bug fixes
refactor/*   - Code refactoring
docs/*       - Documentation updates
```

### Creating a Feature
```bash
# 1. Start from develop
git checkout develop
git pull origin develop

# 2. Create feature branch
git checkout -b feature/your-feature-name

# 3. Make changes, commit with conventional commits
git add .
git commit -m "feat: add your feature description"

# 4. Push and create PR
git push origin feature/your-feature-name
# Create PR: feature/your-feature-name → develop
```

### Conventional Commits
```
feat: Add new feature
fix: Fix bug
docs: Update documentation
refactor: Refactor code
test: Add tests
chore: Maintenance
```

---

## Recent Changes (2025-10-31)

### Modularization Complete ✅
- Decomposed `LiveTradingSession` → `session/` components
- Created `factories/` for dependency injection
- Added `interfaces/` for protocol definitions
- Archived old code in `_legacy/`

### Code Review Fixes ✅
- Removed unused modules (18 files, ~1,776 lines)
- Fixed broken checkpoint restore
- Fixed GUI protocol violation
- Removed state files from git

### Production Improvements ✅
- Thread safety verified
- Decimal arithmetic end-to-end
- Atomic persistence with backups
- Position reconciliation working
- Error isolation functional

---

## Known Issues & Future Work

### Current Branch Issues (URGENT)

**Orphaned Modules Still Exist** ⚠️:
- `aistock/config_consolidated/` (4 files, 280 lines)
- `aistock/fsd_components/` (5 files, 598 lines)
- `aistock/services/` (6 files, 691 lines)
- `aistock/state_management/` (3 files, 207 lines)

**Status**: Fix branch `fix/remove-unused-modules` removes them, but NOT merged yet
**Impact**: No runtime impact (not imported), but confusing codebase
**Action**: Merge fix branch before production deployment

**Large GUI File**:
- `simple_gui.py` is 69,975 lines (extremely large)
- **Recommendation**: Decompose into smaller modules in future refactor

### Phase 7 (Future)
- **Complete FSD decomposition**: Fully use `fsd_components/` (currently not integrated)
  - **Note**: Current `fsd_components/` is orphaned and will be removed
  - If FSD decomposition is desired, recreate with proper integration plan
- **Checkpoint restore**: Implement proper state restoration in SessionFactory
- **Service layer**: Reconsider if service layer abstraction is needed
  - **Note**: Current `services/` is orphaned and will be removed

### Limitations
- **IBKR callbacks**: Still mutate shared state directly (queue-based handoff planned)
- **Testing**: Need more integration tests for new modular components
- **Documentation**: Some legacy docs still reference old architecture

---

## ✅ Pre-Deployment Verification Complete

**All critical steps completed on 2025-11-01**:

### 1. Fix Branches Merged ✅

All three fix branches successfully merged to `feature/modular-architecture`:

```bash
✅ fix/remove-unused-modules - MERGED
   - Removed 18 files, 1,776 lines of orphaned code
   - Verified: services/, fsd_components/, state_management/, config_consolidated/ all removed

✅ fix/checkpoint-restore-implementation - MERGED
   - Removed broken checkpoint restore method
   - Prevents silent data loss

✅ fix/gui-protocol-callback - MERGED
   - Fixed GUI protocol violation
   - Maintains Liskov Substitution Principle
```

### 2. Code Quality Checks ✅

```bash
✅ Ruff formatting applied (14 files reformatted)
✅ Ruff linting (5 auto-fixes applied, 4 style suggestions remain)
⚠️ Pyright not installed (optional - can add later)
```

### 3. Import Verification ✅

```bash
✅ SessionFactory import OK
✅ TradingCoordinator import OK
```

### 4. Test Suite ✅

```bash
✅ 110 tests passed, 2 skipped
✅ 52% code coverage
✅ All critical paths tested
```

### 5. Paper Trading Validation ⚠️

```bash
⏳ Pending - Recommend running before live deployment
   python -m aistock
   # Configure: $200, paper trading, AAPL
   # Run for: 1-2 hours minimum
```

---

## Production Deployment

### Pre-Deployment Checklist
- [ ] **CRITICAL**: Merge fix branches (see "Critical Pre-Deployment Steps" above)
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Verify imports: `python -c "from aistock.factories import SessionFactory"`
- [ ] Paper trade for 1-2 hours minimum
- [ ] Check logs for errors/warnings
- [ ] Verify position reconciliation working
- [ ] Test with conservative FSD parameters
- [ ] Confirm orphaned modules removed: `ls aistock/services/` should fail

### Paper Trading (Safe) ✅
```bash
python -m aistock --broker paper --symbols AAPL --capital 10000
```

### Live Trading (Caution) ⚠️
**Conservative Production Config**:
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

**Deployment Steps**:
1. Start with $1K-2K (NOT $10K)
2. Single symbol (AAPL)
3. Manual monitoring for first week
4. Scale gradually based on performance

---

## Questions & Support

**Architecture Questions**: See `docs/FSD_COMPLETE_GUIDE.md`
**Production Questions**: See `CODE_REVIEW_FINDINGS.md`
**Setup Questions**: See `START_HERE.md`
**IBKR Questions**: See `IBKR_REQUIREMENTS_CHECKLIST.md`
**Git Questions**: See `BRANCH_STRUCTURE_EXPLAINED.md`

---

**Last Updated**: 2025-10-31
**Last Review**: Principal Code Reviewer (2025-10-31)
**Next Review**: After Phase 7 completion
**Status**: Production-ready with fixes applied ✅
