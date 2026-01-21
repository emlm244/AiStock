# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AIStock Robot v2.0 is a Full Self-Driving (FSD) AI trading system powered by Q-Learning Reinforcement Learning. It autonomously makes trading decisions, learns from every trade, and manages risk without manual intervention.

**Tech Stack**: Python 3.10+, NumPy/Pandas, IBAPI (Interactive Brokers), Tkinter GUI, Pytest, Ruff, BasedPyright (strict type checking)

## Core Architecture

### Protocol-Based Dependency Injection

The system uses Protocol-based interfaces enabling implementation swapping. Key protocols defined in `aistock/interfaces/`:
- `BrokerProtocol`: Paper trading and IBKR integration
- `DecisionEngineProtocol`: AI decision making
- `PortfolioProtocol`: Position tracking
- `RiskEngineProtocol`: Risk management
- `StateManagerProtocol`: State persistence
- `MarketDataProviderProtocol`: Market data feeds

### Core Components Flow

```
Market Data → BarProcessor → FSD (Q-Learning) → OrderExecution → Portfolio → Risk → Checkpoint
                ↓                                      ↓             ↓
            Coordinator ← SessionFactory (DI) → BrokerProtocol → Reconciliation
```

**Decision Engine** (`fsd.py`): Q-Learning RL agent with 2,250 states, 5 actions (BUY/SELL/INCREASE/DECREASE/HOLD). Uses LRU cache (200k state limit) for Q-table.

**Execution Layer** (`engine.py`, `execution.py`): Custom trading engine (no BackTrader dependency). Supports Market/Limit/Stop orders with partial fills.

**Portfolio & Risk** (`portfolio.py`, `risk/engine.py`): Thread-safe components with kill switches, daily loss limits, drawdown protection. Uses `threading.Lock()` for IBKR async callbacks.

**Capital Management** (`capital_management.py`): Fixed capital mode with automatic profit withdrawal. Maintains target trading capital by withdrawing excess profits on schedule (daily/weekly/monthly). Supports compounding strategy for traditional reinvestment. Thread-safe with complete audit trail.

**Stop Control** (`stop_control.py`): Manual stop button and end-of-day (EOD) auto-flatten functionality. Features graceful shutdown with order cancellation, position liquidation, and advanced fill monitoring with automatic retry (up to 3 attempts). Handles early market closes (1 PM ET) and regular closes (4 PM ET) correctly.

**Session Orchestration** (`session/coordinator.py`): Lightweight orchestrator routing bars, handling fills, coordinating async checkpoint queue. Automatically resets EOD flatten daily and checks for profit withdrawals every 12 hours.

**Factories** (`factories/session_factory.py`): Top-level DI factory creating complete trading system with all dependencies wired.

## Development Commands

### Setup
```bash
pip install -r requirements.txt          # Runtime dependencies
pip install -r requirements-dev.txt      # Dev tools (ruff, basedpyright, pytest)
```

### Code Quality
```bash
ruff check aistock tests                 # Lint
ruff format aistock tests                # Auto-format
basedpyright                             # Type check (strict mode)
```

### Testing
```bash
pytest tests                             # Run all 440+ tests
pytest -k test_name                      # Run specific test
pytest tests/test_engine_pnl.py          # Run single test file
pytest --cov=. --cov-report=xml          # Coverage report
```

### Run
```bash
python -m aistock                        # Launch FSD GUI
python launch_gui.py                     # Alternative entry point
```

## Critical Development Constraints

### Thread Safety
- **Always use `threading.Lock()`** when modifying shared state accessed by IBKR callbacks
- Portfolio and RiskEngine methods are already thread-safe
- Checkpoint queue uses async writes to prevent blocking trades
- Never block the trading loop with I/O operations

### Financial Data Handling
- **Use `Decimal` for money/prices** (avoid float precision issues)
- **All timestamps must be timezone-aware** (UTC required)
- Validate calculations against broker reconciliation
- Commission tracking must be precise (affects P&L)

### State Management
- Configurations are immutable dataclasses
- State persistence via async checkpointing (non-blocking)
- Idempotency tracking prevents duplicate orders (`idempotency.py`)
- Validate configs with `.validate()` method before use

### Type Safety
- Strict type checking with BasedPyright (no implicit Any, require explicit types)
- Explicit imports only (no star imports)
- Protocol implementations must match interface signatures exactly

## Testing Conventions

- Tests mirror source structure: `tests/test_engine.py` covers `aistock/engine.py`
- Name tests as `test_<behavior>` (e.g., `test_buy_order_updates_portfolio`)
- Use parametrization for scenario coverage
- Shared fixtures in `conftest.py`
- Property-based testing with Hypothesis for invariants
- All tests must pass before submitting PR

## Code Style

- 4-space indentation, snake_case modules, PascalCase classes
- Single quotes for strings (enforced by ruff)
- Line length: 120 characters
- Dataclasses for configuration and data structures
- Conventional Commits: `type: summary` (feat, fix, chore, style, docs, test)

## Key Files to Understand

- `aistock/fsd.py`: Q-Learning RL engine (AI brain) - see `docs/FSD_COMPLETE_GUIDE.md` for algorithm details
- `aistock/engine.py`: Custom trading engine core
- `aistock/factories/session_factory.py`: System-wide dependency injection and component wiring
- `aistock/session/coordinator.py`: Session orchestration and event routing
- `aistock/brokers/paper.py` & `ibkr.py`: Broker implementations
- `aistock/config.py`: Configuration dataclasses with validation
- `aistock/portfolio.py`: Thread-safe position tracking with multiplier support
- `aistock/futures/`: Futures contract management (rollover, validation, preflight)
- `tests/conftest.py`: Shared test fixtures

## Directory Structure

```
aistock/                   # Main package (see PASS0_MANIFEST for current counts)
├── backtest/              # Backtest orchestrator + execution model
├── brokers/               # Paper trading + IBKR integration
├── factories/             # DI factories
├── futures/               # Futures contract management (rollover, validation)
├── interfaces/            # Protocol definitions
├── providers/             # Massive.com data + caching
├── risk/                  # Thread-safe risk management
├── session/               # Session orchestration
├── ml/                    # Machine learning (excluded from type checking)
├── _legacy/               # Deprecated code (excluded)
├── fsd.py                 # Q-Learning RL engine (CORE)
├── engine.py              # Trading engine
├── log_config.py          # Logging config (no stdlib shadowing)
├── portfolio.py           # Thread-safe portfolio with multiplier support
├── capital_management.py  # Profit withdrawal strategies
├── stop_control.py        # Manual stop controls
└── simple_gui.py          # Tkinter GUI

tests/                     # 440+ tests
configs/                   # Runtime configuration templates
docs/                      # Technical documentation
state/                     # Runtime: Checkpoints (gitignored)
logs/                      # Runtime: Logs (gitignored)
models/                    # Runtime: Q-tables (gitignored)
```

## CI/CD

GitHub Actions runs on every push:
- Ruff linting
- BasedPyright type checking
- Pytest on Python 3.10/3.11/3.12

All checks must pass before merge.

## Capital Management & Stop Controls

### Fixed Capital with Profit Withdrawal

**Purpose**: Maintain fixed trading capital by automatically withdrawing excess profits, preventing position sizes from growing indefinitely and locking in gains.

**Configuration**:
```python
from aistock.capital_management import CapitalManagementConfig

config = CapitalManagementConfig(
    target_capital=Decimal('100000'),  # Maintain $100k trading capital
    withdrawal_threshold=Decimal('5000'),  # Withdraw when profit > $5k
    withdrawal_frequency='daily',  # daily, weekly, or monthly
    enabled=True
)
```

**How it works**:
1. Every 12 hours, checks if `portfolio.total_equity() > target_capital + withdrawal_threshold`
2. If true, withdraws excess: `withdrawn = equity - target_capital`
3. Only withdraws available cash (never liquidates positions)
4. Records withdrawal with timestamp and running total

**Use Cases**:
- Lock in profits regularly without manual intervention
- Prevent psychological bias from growing account size
- Maintain consistent position sizing relative to capital
- Fund external expenses from trading profits

### Stop Controls & Graceful Shutdown

**Purpose**: Enable manual emergency stops and automatic end-of-day position flattening with guaranteed order cancellation and position closure.

**Configuration**:
```python
from aistock.stop_control import StopConfig
from datetime import time

config = StopConfig(
    enable_manual_stop=True,  # Allow emergency stop button
    enable_eod_flatten=True,  # Auto-flatten before close
    eod_flatten_time=time(15, 45),  # 3:45 PM ET (15 min before close)
    emergency_liquidation_timeout=30.0  # Max wait per retry (seconds)
)
```

**Manual Stop Trigger**:
```python
# In GUI or CLI
coordinator.stop_controller.request_stop('user_manual_stop')
# Next bar processing will detect stop and initiate graceful shutdown
```

**Graceful Shutdown Sequence**:
1. **Cancel all orders**: Calls `broker.cancel_all_orders()` to prevent new fills
2. **Submit liquidation orders**: Creates market orders to close all positions
3. **Monitor fills**: Polls portfolio every 0.5s, waiting up to timeout (default: 30s)
4. **Retry unfilled**: If positions remain after timeout, re-submits market orders
5. **Max 3 attempts**: Retries up to 3 times with full timeout per attempt
6. **Detailed status**: Returns dict with `fully_closed`, `partially_closed`, `failed` lists

**Early Close Handling**:
- Automatically detects early close days (1 PM ET vs 4 PM ET regular close)
- Calculates flatten time as X minutes before actual close (e.g., 15 minutes)
- Holiday early closes: If market closes at 1 PM, flattens at 12:45 PM
- Regular closes: If market closes at 4 PM, flattens at 3:45 PM

**Daily Reset**:
- EOD flatten flag automatically resets at start of each trading day
- Coordinator detects new date and calls `stop_controller.reset_eod_flatten()`

**Status Codes**:
- `success`: All positions closed successfully
- `partial`: Some positions closed, others remain
- `failed`: No positions closed (rare, indicates broker/network issues)

### Integration in SessionFactory

Both features are automatically created and wired by `SessionFactory`:
```python
factory = SessionFactory(config, fsd_config)
coordinator = factory.create_trading_session(
    symbols=['AAPL', 'MSFT'],
    checkpoint_dir='state'
)
# Capital manager and stop controller are already injected into coordinator
```

**Access in session**:
```python
# Check withdrawal stats
stats = coordinator.capital_manager.get_stats()
# {'total_withdrawn': Decimal('12345.67'), 'last_withdrawal': datetime(...), ...}

# Trigger manual stop
coordinator.stop_controller.request_stop('user_initiated')

# Check if stop requested
if coordinator.stop_controller.is_stop_requested():
    reason = coordinator.stop_controller.get_stop_reason()
```

## Futures Trading Support

The system supports futures contracts with proper P&L calculation using contract multipliers.

### Contract Multiplier Handling

Futures contracts have multipliers that affect notional value (e.g., ES = 50x, NQ = 20x). The portfolio tracks P&L correctly:

```python
# For ES futures at 5200 with multiplier=50:
# Notional = 1 contract * 5200 points * $50/point = $260,000

# Cash impact on fill:
cash_delta = -(quantity * price * multiplier) - commission

# P&L calculation:
realized_pnl = (fill_price - avg_price) * quantity * multiplier
```

### Contract Configuration

Define futures contracts in `ContractSpec`:
```python
from aistock.config import ContractSpec

es_contract = ContractSpec(
    symbol='ESH26',           # Front-month ES
    sec_type='FUT',           # Security type
    exchange='CME',
    currency='USD',
    multiplier=50,            # $50 per point
    expiration_date='20260320',  # YYYYMMDD
    underlying='ES',          # Underlying symbol
)
```

### Futures Module (`aistock/futures/`)

- **`contracts.py`**: `FuturesContractSpec` with expiration tracking
- **`rollover.py`**: `RolloverManager` for contract rollover alerts and order generation
- **`preflight.py`**: `FuturesPreflightChecker` blocks trading on expired contracts
- **`validator.py`**: Validates contracts via IBKR or offline

### Rollover Management

```python
from aistock.futures.rollover import RolloverConfig, RolloverManager

rollover_config = RolloverConfig(
    warn_days_before_expiry=7,  # Alert 7 days before
    state_dir='state',          # Persist mappings
)

# SessionFactory wires RolloverManager automatically if config provided
factory = SessionFactory(config, fsd_config, rollover_config=rollover_config)
```

**Behavior:**
- Preflight validation blocks session start if contracts are expired
- Coordinator checks rollover alerts hourly
- Rollover orders generated but executed manually (safety by design)

## Edge Cases & Risk Management

The system handles:
- Circuit breakers and trading halts (`edge_cases.py`)
- Zero/negative prices
- Position reversals (long → short)
- Broker disconnections
- Partial fills
- Daily loss limits and drawdown protection
- Graceful shutdown with retry logic (SIGINT, SIGTERM)
- Early market closes (1 PM ET holidays)
- Futures contract expiration and rollover alerts

When adding features, consider thread safety for IBKR callbacks, state persistence, and risk constraint impacts.
