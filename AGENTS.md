# Repository Guidelines

**Last Updated**: 2025-10-31 (Post-Modularization)
**Architecture**: Modular with Dependency Injection

---

## Project Structure & Module Organization

### Core Trading System
- **`aistock/`** - Main trading system package
  - **Modular Architecture** (New as of 2025-10-31):
    - `factories/` - Dependency injection factories (entry point for creating sessions)
    - `session/` - Decomposed session orchestration (coordinator, bar processor, reconciliation, analytics, checkpointing)
    - `interfaces/` - Protocol definitions for all major components (enables DI and testing)
    - `_legacy/` - Archived old monolithic code (for reference only)

  - **⚠️ Orphaned Modules (EXIST but NOT imported)**:
    - `config_consolidated/` - 4 files (280 lines) - Unused, scheduled for removal
    - `fsd_components/` - 5 files (598 lines) - Unused, scheduled for removal
    - `services/` - 6 files (691 lines) - Unused, scheduled for removal
    - `state_management/` - 3 files (207 lines) - Unused, scheduled for removal
    - **Status**: Fix branch `fix/remove-unused-modules` removes these, NOT merged yet
    - **Action**: Do NOT import from these modules

  - **Core Components**:
    - `fsd.py` - Q-Learning decision engine (FSD = Full Self-Driving)
    - `portfolio.py` - Portfolio management with thread-safe operations
    - `risk.py` - Risk engine with configurable limits
    - `patterns.py` - Candlestick pattern detection
    - `timeframes.py` - Multi-timeframe aggregation
    - `professional.py` - Professional trading safeguards
    - `edge_cases.py` - Edge case handling
    - `calendar.py` - Trading calendar and hours
    - `brokers/` - Broker integrations (Paper, IBKR)
    - `simple_gui.py` - Tkinter GUI (69,975 lines - candidate for decomposition)
    - `__main__.py` - Entry point (`python -m aistock`)

### Supporting Directories
- **`tests/`** - pytest test suite mirroring package layout
  - `fixtures/` - Test data and CSV samples
  - `test_*_integration.py` - Integration tests
  - `test_*_threadsafe.py` - Thread safety tests

- **`scripts/`** - Operational helpers
  - `run_smoke_backtest.py` - Quick backtest verification
  - Data generation utilities

- **`configs/`** - JSON configuration templates
  - `fsd_mode_example.json` - Example FSD configuration
  - Copy and customize (don't edit in place)

- **`docs/`** - Documentation
  - `FSD_COMPLETE_GUIDE.md` - Comprehensive FSD guide
  - Production readiness assessments
  - Architecture documentation

- **`state/`** - Runtime state (NOT in git)
  - Generated Q-learning data
  - Each developer has their own
  - Excluded from version control

---

## ⚠️ Current Branch Status & Known Issues

### Branch: `feature/modular-architecture`

**Status**: Functional but contains orphaned code awaiting cleanup

**Pending Merge**: Three fix branches created (2025-10-31) but NOT yet merged:
1. `fix/remove-unused-modules` - Removes 18 orphaned files (1,776 lines)
2. `fix/checkpoint-restore-implementation` - Removes broken checkpoint restore method
3. `fix/gui-protocol-callback` - Fixes protocol violation in GUI

**Impact**:
- ✅ **Runtime**: No impact (orphaned code not imported)
- ⚠️ **Codebase Clarity**: Confusing to see unused modules
- ⚠️ **Documentation**: Docs claim modules removed, but they still exist

**Recommendation**: Merge fix branches OR manually delete orphaned directories before production deployment

```bash
# Option 1: Merge fix branches
git checkout feature/modular-architecture
git merge fix/remove-unused-modules
git merge fix/checkpoint-restore-implementation
git merge fix/gui-protocol-callback

# Option 2: Manual cleanup
rm -rf aistock/config_consolidated
rm -rf aistock/fsd_components
rm -rf aistock/services
rm -rf aistock/state_management
git add -A
git commit -m "chore: remove orphaned modules"
```

---

## Starting Points for Development

### Creating a Trading Session (Recommended Approach)
```python
from aistock.factories import SessionFactory
from aistock.config import BacktestConfig, BrokerConfig, DataSource, EngineConfig
from aistock.fsd import FSDConfig

# 1. Create configuration
config = BacktestConfig(
    data=DataSource(path='data', symbols=['AAPL']),
    engine=EngineConfig(),
    broker=BrokerConfig(backend='paper')
)
fsd_config = FSDConfig()

# 2. Use factory to create session
factory = SessionFactory(config, fsd_config=fsd_config)
coordinator = factory.create_trading_session(
    symbols=['AAPL'],
    checkpoint_dir='state'
)

# 3. Start trading
coordinator.start()
```

### Understanding the Modular Architecture

**Old Way** (Deprecated):
```python
from aistock.session import LiveTradingSession  # ❌ Don't use
session = LiveTradingSession(...)  # Monolithic god object
```

**New Way** (Current):
```python
from aistock.factories import SessionFactory  # ✅ Use this
factory = SessionFactory(config, fsd_config)
coordinator = factory.create_trading_session(...)  # Modular components
```

**Key Modules to Understand**:
1. **`factories/session_factory.py`** - Creates fully configured trading sessions
2. **`session/coordinator.py`** - Orchestrates trading (replaces old LiveTradingSession)
3. **`session/bar_processor.py`** - Handles market data ingestion
4. **`session/checkpointer.py`** - Async state persistence
5. **`interfaces/`** - Protocol definitions (for DI and testing)

---

## Build, Test, and Development Commands

### Installation
```bash
# Install runtime dependencies
pip install -r requirements.txt

# Install dev dependencies (optional)
pip install ruff pyright pytest pytest-cov
```

### Running the Application
```bash
# Launch FSD GUI (recommended for first-time users)
python -m aistock

# Headless paper trading
python -m aistock --broker paper --symbols AAPL --capital 10000

# Run smoke backtest
python scripts/run_smoke_backtest.py
```

### Testing
```bash
# Run full test suite
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=aistock --cov-report=html -v

# Run specific test file
pytest tests/test_fsd.py -v

# Stop on first failure
pytest tests/ -v --tb=short -x

# Run only integration tests
pytest tests/ -v -k integration
```

### Code Quality
```bash
# Lint with ruff
ruff check aistock/

# Auto-format with ruff
ruff format aistock/

# Type checking with pyright (optional)
pyright aistock/
```

---

## Coding Style & Naming Conventions

### General Style
- **Formatter**: Ruff (4-space indentation, 120-char lines, single quotes)
- **Python Version**: 3.9+ syntax required
- **Type Hints**: Use throughout (see `interfaces/` for protocol examples)
- **Imports**: Organized by ruff (stdlib, third-party, local)

### Naming Conventions
- **Files**: `lowercase_with_underscores.py` (e.g., `risk.py`, `session_factory.py`)
- **Classes**: `CapWords` (e.g., `FSDEngine`, `RiskManager`, `TradingCoordinator`)
- **Functions/Methods**: `lowercase_with_underscores` (e.g., `create_trading_session`)
- **Constants**: `UPPERCASE_WITH_UNDERSCORES` (e.g., `MAX_POSITION_SIZE`)
- **Private**: Prefix with `_` (e.g., `_handle_fill`, `_persistence_lock`)

### Module Organization
Follow existing patterns:
- **Core domain logic**: Root level files (`portfolio.py`, `risk.py`, `fsd.py`)
- **Infrastructure**: Subdirectories (`session/`, `factories/`, `interfaces/`)
- **Integration**: `brokers/` subdirectory
- **Helpers**: Utility functions in dedicated files

### Broker Integration
Retain upstream casing for broker callbacks:
```python
# IBKR callbacks use camelCase (keep it):
def realtimeBar(self, reqId, time, open_, high, low, close, volume):
    pass
```

---

## Testing Guidelines

### Test Organization
- Mirror module structure: `tests/test_<module>.py` tests `aistock/<module>.py`
- Integration tests: `tests/test_*_integration.py`
- Thread safety tests: `tests/test_*_threadsafe.py`
- Fixtures in `tests/fixtures/`

### Test Naming
Use descriptive names:
```python
def test_fsd_updates_q_values_after_fill():
    """Verify FSD updates Q-table when trade completes."""
    pass

def test_risk_engine_blocks_overleveraged_trade():
    """Verify risk engine rejects trades exceeding position limits."""
    pass
```

### Testing Best Practices
- Use fixtures for market data samples
- Test thread safety with `threading` module
- Test with both Decimal and float inputs
- Mock broker calls for unit tests
- Use integration tests for end-to-end flows

### Coverage
```bash
# Generate HTML coverage report
pytest --cov=aistock --cov-report=html tests/

# View coverage
open htmlcov/index.html  # macOS
start htmlcov/index.html # Windows
```

**Target**: Keep coverage steady (currently ~70-80%)

---

## Commit & Pull Request Guidelines

### Commit Message Format
Follow Conventional Commits:
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `test`: Adding or updating tests
- `chore`: Maintenance (deps, config, etc.)

**Examples**:
```
feat(fsd): add momentum indicator to state extraction

fix(risk): prevent negative position sizes in risk checks

docs: update CLAUDE.md with modular architecture

refactor(session): extract bar processing to separate module

test: add thread safety tests for portfolio
```

### Pull Request Guidelines
1. **Title**: Clear, descriptive (`feat: Add ML strategy support`)
2. **Description**:
   - Summarize intent
   - Link issues if applicable
   - List verification steps
3. **Verification**: Include test results, screenshots (for GUI changes), logs
4. **Scope**: Keep changes focused (single feature/fix per PR)
5. **Review**: Tag reviewer, address feedback
6. **Merge**: Squash noisy commits before merging

### Branch Naming
```
feature/<description>  - New features
fix/<description>      - Bug fixes
refactor/<description> - Code refactoring
docs/<description>     - Documentation updates
```

**Examples**:
- `feature/ml-strategy-integration`
- `fix/risk-calculation-overflow`
- `refactor/session-decomposition`
- `docs/update-architecture-guide`

---

## Security & Configuration Tips

### Credentials Management
- **Never commit**: `.env`, credentials files, API tokens
- **Use**: Environment variables or secrets managers
- **Reference**: Via `aistock.config` module
- **IBKR**: Store in `.env`:
  ```
  IBKR_ACCOUNT_ID=DU1234567
  IBKR_CLIENT_ID=1001
  IBKR_TWS_HOST=127.0.0.1
  IBKR_TWS_PORT=7497
  ```

### State Files
- **Never commit**: `state/` directory contents
- **Gitignore**: `state/**/*.json`, `state/**/*.pkl`
- **Reason**: User-specific learned FSD data
- **Each developer**: Generates their own state locally

### Configuration Files
- **Templates**: `configs/*.json` (in git)
- **Personal copies**: Copy and customize outside `configs/`
- **Runtime**: Pass via command line or environment variables

### Production Safety
- Review `CODE_REVIEW_FINDINGS.md` before deploying
- Start with paper trading, verify for 1+ week
- Use conservative parameters initially
- Monitor first 24 hours of live trading closely

---

## Architecture Notes

### Modular Design (as of 2025-10-31)

**Component Hierarchy**:
```
SessionFactory (DI)
  └─> TradingCoordinator (orchestration)
      ├─> Portfolio (thread-safe)
      ├─> RiskEngine (configurable limits)
      ├─> FSDEngine (decision making)
      ├─> Broker (paper/IBKR)
      ├─> BarProcessor (data ingestion)
      ├─> CheckpointManager (async persistence)
      ├─> PositionReconciler (broker sync)
      └─> AnalyticsReporter (performance tracking)
```

**Key Design Patterns**:
- **Dependency Injection**: Via `factories/`
- **Protocol-based interfaces**: In `interfaces/`
- **Single Responsibility**: Each session component has one job
- **Thread Safety**: RLock/Lock on shared state
- **Error Isolation**: Try/except at component boundaries

### Code Organization
- **Subdirectories**: Infrastructure (session/, factories/, interfaces/)
- **Root Files**: Domain logic (fsd.py, portfolio.py, risk.py)
- **This is Clean Architecture**: Separation of concerns by layer

---

## Common Development Tasks

### Adding a New Trading Strategy
1. Implement `DecisionEngineProtocol` from `interfaces/decision.py`
2. Register in `factories/trading_components_factory.py`
3. Add configuration to `config.py`
4. Write tests in `tests/test_<strategy>.py`
5. Update GUI if needed

### Adding a New Safeguard
1. Add check to `professional.py:ProfessionalSafeguards.check()`
2. Return `TradingSafeguardResult` with risk level
3. Add test to `tests/test_professional_integration.py`
4. Update configuration if needed

### Adding a Candlestick Pattern
1. Add detection to `patterns.py:PatternDetector`
2. Return `PatternSignal` (BULLISH, BEARISH, NEUTRAL)
3. Add test to `tests/test_patterns.py`
4. Thread safety handled automatically

### Modifying FSD Parameters
1. Update `fsd.py:FSDConfig` dataclass
2. Adjust in GUI (`simple_gui.py`) if needed
3. Test with `pytest tests/test_fsd.py -v`
4. Document changes in `docs/FSD_COMPLETE_GUIDE.md`

---

## Critical Patterns

### 1. Use Decimal for Money
```python
from decimal import Decimal

# WRONG
price = 100.50  # ❌ Float precision issues

# RIGHT
price = Decimal('100.50')  # ✅ Exact decimal
quantity = Decimal('10')
cost = price * quantity
```

### 2. Thread Safety
```python
import threading

class MyComponent:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}

    def update(self, key, value):
        with self._lock:
            self._state[key] = value
```

### 3. Protocol-Based DI
```python
from typing import Protocol

class MyProtocol(Protocol):
    def do_something(self) -> None: ...

def my_function(component: MyProtocol):
    # Works with any class that implements do_something()
    component.do_something()
```

---

## Recent Changes (2025-10-31)

### Modularization Complete
- ✅ Decomposed `LiveTradingSession` → `session/` components
- ✅ Created `factories/` for dependency injection
- ✅ Added `interfaces/` for protocol definitions
- ✅ Archived old code in `_legacy/`

### Code Review Fixes (IN FIX BRANCHES - NOT YET MERGED)
- 🔄 **fix/remove-unused-modules**: Removes 18 orphaned files (1,776 lines)
  - ⚠️ Modules still exist on feature branch until merged
- 🔄 **fix/checkpoint-restore-implementation**: Removes broken checkpoint restore
  - Method loaded checkpoint but didn't use it (silent data loss)
- 🔄 **fix/gui-protocol-callback**: Fixes protocol violation
  - Added hasattr() guard for gui_log_callback
- ✅ **Merged**: State files removed from git tracking

### Production Readiness
- ✅ Thread safety verified
- ✅ Decimal arithmetic end-to-end
- ✅ Atomic persistence with backups
- ✅ Position reconciliation working
- ✅ Error isolation functional
- ⚠️ **Pending**: Merge fix branches for final cleanup

---

## Questions?

- **Architecture**: See `docs/FSD_COMPLETE_GUIDE.md`
- **Production**: See `CODE_REVIEW_FINDINGS.md`
- **Setup**: See `START_HERE.md`
- **IBKR**: See `IBKR_REQUIREMENTS_CHECKLIST.md`
- **Changes**: See git commit history

---

**Last Professional Review**: 2025-10-31
**Next Review**: After Phase 7 (FSD decomposition completion)
