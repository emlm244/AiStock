# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AIStock Robot v2.0 is a Full Self-Driving (FSD) AI trading system powered by Q-Learning reinforcement learning. The system makes autonomous trading decisions, learns from every trade, and manages risk automatically. It supports both paper trading and live trading via Interactive Brokers (IBKR).

**Key Philosophy**: FSD-only architecture (v2.0 removed BOT and Supervised modes) with a custom trading engine (no BackTrader dependency). The core is a Q-Learning agent that discretizes market state, selects actions via ε-greedy policy, and continuously updates Q-values based on reward signals.

---

## Development Commands

### Setup
```bash
pip install -r requirements.txt              # Production dependencies
pip install -r requirements-dev.txt          # Development tools (pytest, ruff, mypy, etc.)
```

### Running the Application
```bash
python -m aistock                            # Launch FSD engine (headless/CLI mode)
python launch_gui.py                         # Launch Tkinter GUI for manual control
```

### Testing
```bash
pytest tests/                                # Run all tests
pytest tests/test_fsd.py                     # Run specific test file
pytest -k test_portfolio_update              # Run tests matching pattern
pytest -v                                    # Verbose output
pytest --cov=aistock --cov-report=html       # Generate coverage report
pytest -x                                    # Stop on first failure
pytest -n auto                               # Parallel testing (requires pytest-xdist)
```

### Linting & Formatting
```bash
ruff check aistock tests                     # Run linter (config in ruff.toml)
ruff check --fix aistock tests               # Auto-fix linting issues
ruff format aistock tests                    # Format code (single quotes, 120 char line length)
```

### Type Checking
```bash
pyright                                      # Run type checking (config in pyrightconfig.json)
mypy aistock                                 # Alternative type checker
```

### Interactive Brokers Testing
```bash
python test_ibkr_connection.py               # Test IBKR TWS/Gateway connection
```

### Backtesting & Workflow Scripts
```bash
python scripts/run_sample_backtest.py        # Run sample backtest
python scripts/run_full_workflow.py          # Full workflow test
python scripts/rerun_backtests.py            # Rerun backtests per docs/BACKTEST_RERUN_GUIDE.md
python scripts/compare_backtest_results.py   # Compare backtest results
```

---

## Architecture & Core Components

### Component Hierarchy

```
SessionFactory (creates entire trading system)
    ├── TradingComponentsFactory (creates individual components)
    └── TradingCoordinator (orchestrates execution)
        ├── Portfolio (position tracking, thread-safe)
        ├── RiskEngine (limits, drawdown, halts, thread-safe)
        ├── FSDEngine (Q-Learning decision engine)
        ├── BaseBroker (paper.py or ibkr.py)
        ├── BarProcessor (market data pipeline)
        ├── PositionReconciler (broker sync)
        ├── CheckpointManager (state persistence)
        └── AnalyticsReporter (metrics)
```

### Core Modules

**aistock/fsd.py** - FSD Reinforcement Learning Engine
- `FSDEngine`: Q-Learning agent with state discretization, ε-greedy action selection
- `FSDConfig`: Learning rate, exploration rate, confidence thresholds, position limits
- State space: price change, volume ratio, trend, volatility, position percentage (~2,250 states)
- Action space: BUY, SELL, INCREASE_SIZE, DECREASE_SIZE, HOLD
- Reward calculation: P&L - risk penalty - transaction costs
- Q-table persistence: saves/loads learned strategies
- **Important**: Q-values decay over time (configurable) to prevent "nostalgia" for old market patterns
- LRU eviction when Q-table exceeds `max_q_table_states` (default 200k)

**aistock/engine.py** - Custom Trading Engine
- `TradingEngine`: Executes trades, tracks portfolio state, calculates P&L
- `Trade`: Trade record with realized P&L
- `BacktestResult`: Backtest metrics (return, drawdown, win rate, equity curve)
- Replaces BackTrader with lightweight, FSD-focused implementation

**aistock/portfolio.py** - Thread-Safe Portfolio Tracking
- `Portfolio`: Tracks positions, cash, equity (uses threading.Lock for IBKR callback safety)
- `Position`: Position details with average price, entry time, volume
- Methods: `update_position()`, `get_equity()`, `get_position()`

**aistock/risk.py** - Thread-Safe Risk Management
- `RiskEngine`: Enforces daily loss limits, max drawdown, position sizing, order rate limiting
- `RiskState`: Serializable risk state for persistence
- `RiskViolation`: Exception raised on limit breach
- **Minimum balance protection**: Prevents trading below user-defined threshold (configurable)

**aistock/session/coordinator.py** - Trading Session Orchestrator
- `TradingCoordinator`: Lightweight orchestrator (does NOT do component work directly)
- Responsibilities: route bars, handle fills, coordinate startup/shutdown
- Delegates to: BarProcessor, CheckpointManager, PositionReconciler, AnalyticsReporter

**aistock/brokers/** - Broker Abstraction Layer
- `base.py`: `BaseBroker` abstract class defining broker interface
- `paper.py`: `PaperBroker` for simulated trading (instant fills, no slippage)
- `ibkr.py`: `IBKRBroker` for Interactive Brokers TWS/Gateway integration
- All brokers implement: `start()`, `stop()`, `submit()`, `cancel()`, `set_fill_handler()`

**aistock/interfaces/** - Protocol Definitions
- `broker.py`: `BrokerProtocol`
- `decision.py`: `DecisionEngineProtocol` (FSDEngine implements this)
- `portfolio.py`: `PortfolioProtocol`
- `risk.py`: `RiskEngineProtocol`
- **Design**: Protocols enable dependency injection and testing via duck typing

**aistock/factories/** - Dependency Injection
- `session_factory.py`: `SessionFactory` creates complete trading sessions with all components wired
  - `create_trading_session()`: Create fresh session
  - `create_with_checkpoint_restore()`: Create session with restored state (crash recovery)
- `trading_components_factory.py`: `TradingComponentsFactory` creates individual components
  - Supports optional `restored_state` parameter in `create_risk_engine()` for checkpoint restore

**Professional Features** (aistock/professional.py, aistock/patterns.py, aistock/timeframes.py)
- Multi-timeframe analysis and correlation
- Candlestick pattern recognition (doji, hammer, engulfing, etc.)
- Professional trading safeguards (volatility limits, correlation checks)

---

## Configuration System

**aistock/config.py**
- `BacktestConfig`: Top-level config (data, engine, risk, universe)
- `RiskLimits`: Daily loss %, max drawdown %, position size limits, order rate limits
- `EngineConfig`: Initial equity, bar interval, commission
- `DataConfig`: Data source, timeframes
- `UniverseConfig`: Symbol selection criteria

**Example Configuration** (configs/fsd_mode_example.json):
```json
{
  "fsd_config": {
    "learning_rate": 0.001,
    "exploration_rate": 0.1,
    "min_confidence_threshold": 0.6
  },
  "risk_limits": {
    "max_daily_loss_pct": 2.0,
    "max_drawdown_pct": 10.0
  }
}
```

---

## State Persistence & Checkpointing

**state/** directory contains runtime state:
- `submitted_orders.json`: Order idempotency tracking (prevents duplicate submissions)
- `portfolio.json`: Portfolio state snapshot (cash, positions, realized P&L, trade log)
- `risk_state.json`: Risk engine state (daily P&L, peak equity, halt status)
- Q-table checkpoints (FSDEngine saves learned Q-values periodically)

**aistock/session/checkpointer.py**
- `CheckpointManager`: Saves/loads portfolio and risk state
- Auto-saves on critical events (trades, risk violations)

**aistock/persistence.py**
- `save_checkpoint()`: Persist portfolio and risk state atomically
- `load_checkpoint()`: Restore state from checkpoint files (with backup fallback)
- `save_portfolio_snapshot()`: Serialize portfolio to JSON
- `load_portfolio_snapshot()`: Deserialize portfolio from JSON
- Atomic writes with backup files to prevent corruption

**aistock/idempotency.py**
- `OrderIdempotencyTracker`: Prevents duplicate order submissions (critical for live trading)

### Crash Recovery Workflow
```python
from aistock.factories import SessionFactory
from aistock.config import BacktestConfig
from aistock.fsd import FSDConfig

# Create factory
config = BacktestConfig(...)
fsd_config = FSDConfig(...)
factory = SessionFactory(config, fsd_config)

# Restore from checkpoint (crash recovery)
coordinator = factory.create_with_checkpoint_restore(
    checkpoint_dir='state',
    symbols=['AAPL', 'MSFT']
)
coordinator.start()
```

---

## Testing Philosophy & Patterns

### Test Structure
- Tests mirror module structure: `tests/test_<module>.py` covers `aistock/<module>.py`
- Use `pytest` fixtures for shared setup (avoid writing to production data/ or state/ directories)
- Parametrize tests for scenario coverage: `@pytest.mark.parametrize(...)`

### Critical Test Categories
1. **Unit tests**: Individual component behavior (test_portfolio.py, test_risk_engine.py)
2. **Integration tests**: Component interactions (test_coordinator_regression.py)
3. **Edge cases**: Timezone handling, concurrency, broker failures (test_edge_cases.py, test_concurrency_stress.py)
4. **Regression tests**: Prevent reintroduction of fixed bugs (test_critical_fixes_regression.py)

### Running Specific Test Suites
```bash
pytest tests/test_fsd.py                     # FSD engine tests
pytest tests/test_risk_engine.py             # Risk management tests
pytest tests/test_coordinator_regression.py  # Integration tests
pytest tests/test_edge_cases.py              # Edge case tests
pytest tests/test_concurrency_stress.py      # Thread safety tests
```

### Test Naming Convention
- `test_<behavior>`: Descriptive test names (e.g., `test_portfolio_update_long_position`)
- `test_<module>_<edge_case>`: Edge case tests (e.g., `test_risk_engine_minimum_balance_protection`)

---

## Code Style & Type Safety

### Style Guidelines (enforced by ruff.toml)
- **Line length**: 120 characters
- **Indentation**: 4 spaces (no tabs)
- **Quotes**: Single quotes (`'string'`)
- **Imports**: Explicit imports, alphabetically sorted (isort)
- **Naming**: snake_case for functions/variables, PascalCase for classes
- **Target**: Python 3.9+ (typing-extensions for backports)

### Type Checking (pyrightconfig.json)
- **Mode**: Strict type checking enabled
- **Scope**: aistock/ and scripts/ (excludes tests/ for flexibility)
- **Required**: Type hints on all public functions, dataclasses, protocols
- **Warning**: Avoid `Any` types when possible (reportAny: warning)

### Common Patterns
```python
from __future__ import annotations  # Enable forward references
from typing import TYPE_CHECKING    # Avoid circular imports

if TYPE_CHECKING:
    from .other_module import OtherClass

from decimal import Decimal         # Use Decimal for financial calculations
from datetime import datetime, timezone  # All timestamps must be timezone-aware
```

---

## Interactive Brokers (IBKR) Integration

### Prerequisites
1. TWS or IB Gateway running locally
2. Socket connection enabled (default: localhost:7497 for TWS, 4001 for Gateway)
3. Paper trading account recommended for testing
4. See `IBKR_REQUIREMENTS_CHECKLIST.md` for detailed setup

### Connection Testing
```bash
python test_ibkr_connection.py   # Validates connection, account, positions
```

### IBKR-Specific Considerations
- **Threading**: IBKR callbacks run on separate threads → all shared state must be thread-safe
- **Callbacks**: `IBKRBroker` implements IBKR callbacks (orderStatus, execDetails, etc.)
- **Position reconciliation**: `PositionReconciler` syncs local portfolio with IBKR positions on startup
- **Error handling**: IBKR errors logged, connection retries on failure

---

## Git Workflow & Commit Guidelines

### Commit Format (Conventional Commits)
```
<type>: <summary>

<optional body>

<optional footer>
```

**Types**: fix, feat, docs, refactor, test, chore, perf

### Examples (from git history)
```
fix: add LRU eviction for Q-table memory bounds
feat: implement minimum balance protection in RiskEngine
docs: update FSD guide with Q-value decay explanation
test: add concurrency stress tests for Portfolio
```

### Pull Request Guidelines
- **Title**: Concise problem statement
- **Body**: Solution summary, operational considerations (config changes, manual steps)
- **Checklist**: Confirm linting/testing passed, attach metrics/screenshots for GUI changes
- **Branch**: Create feature branches (not main), use descriptive names

---

## Common Development Workflows

### Adding a New Risk Limit
1. Update `RiskLimits` dataclass in `aistock/config.py`
2. Add validation logic in `RiskEngine.check_pre_trade()` (aistock/risk.py)
3. Add corresponding test in `tests/test_risk_engine.py`
4. Update `docs/` if user-facing configuration changes
5. Run `ruff format` and `pytest` before committing

### Modifying FSD Learning Parameters
1. Update `FSDConfig` in `aistock/fsd.py`
2. Add validation in `FSDConfig.validate()`
3. Test with `scripts/run_sample_backtest.py` to verify impact
4. Document parameter effects in `docs/FSD_COMPLETE_GUIDE.md`

### Adding a New Broker
1. Create `aistock/brokers/new_broker.py`
2. Inherit from `BaseBroker` and implement required methods
3. Add broker selection logic in `TradingComponentsFactory`
4. Add integration tests in `tests/test_broker.py`
5. Document setup in README.md or new broker guide

### Debugging Live Trading Issues
1. Check `logs/` directory for session logs (if logging enabled)
2. Review `state/submitted_orders.json` for order idempotency issues
3. Examine Q-table state (if FSDEngine saves checkpoints)
4. Use `test_ibkr_connection.py` to verify IBKR connectivity
5. Enable verbose logging in `aistock/logging.py` if needed

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| `README.md` | Project overview, quick start |
| `CLAUDE.md` | Developer guide (this file) |
| `AGENTS.md` | Repository guidelines (build, test, coding style) |
| `docs/FSD_COMPLETE_GUIDE.md` | FSD technical deep dive (Q-Learning, state space, action space) |
| `IBKR_REQUIREMENTS_CHECKLIST.md` | IBKR setup instructions |
| `docs/BACKTEST_RERUN_GUIDE.md` | Backtest rerun procedures |
| `docs/OPTION_F_BROKER_RECONCILIATION.md` | Position reconciliation details |
| `docs/archive/` | Historical audits and code reviews |

---

## Critical Safety Notes

### Thread Safety Requirements
- **Portfolio**: Uses `threading.Lock` for all state mutations (IBKR callbacks are threaded)
- **RiskEngine**: Uses `threading.RLock` (reentrant lock for nested halt calls)
- **OrderIdempotencyTracker**: Thread-safe order tracking

### Financial Data Precision
- **Always use `Decimal`** for prices, quantities, P&L calculations (never `float`)
- **Timezone-aware datetimes** required for all timestamps (raises `ValueError` if naive)

### Live Trading Safeguards
- Start with paper trading (PaperBroker) for 1-2 weeks minimum
- Use conservative FSD parameters initially (learning_rate=0.0001, min_confidence=0.8)
- Set strict risk limits (max_daily_loss_pct=2.0)
- Enable minimum balance protection (`RiskEngine.minimum_balance`)
- Monitor first week of live trading manually

### Order Idempotency
- Never bypass `OrderIdempotencyTracker` in live trading
- Always check `idempotency.is_duplicate()` before order submission
- `state/submitted_orders.json` must persist across sessions

---

## Known Issues & Limitations

### FSD Limitations
- Q-Learning requires sufficient exploration (cold start problem)
- Discretized state space may miss nuanced market conditions
- Performance degrades if market regime changes rapidly (Q-value decay mitigates this)

### IBKR Integration
- TWS/Gateway must be running before starting AIStock
- Connection drops require manual restart (auto-reconnect not implemented)
- IBKR rate limits apply (max 50 orders/second)

### Performance Considerations
- Q-table grows unbounded without LRU eviction (enabled by default in v2.0)
- Large Q-tables increase save/load time (checkpoint on critical events only)

---

## Troubleshooting

### FSD Not Trading
- Check `min_confidence_threshold` (lower to increase trades)
- Verify risk limits not breached (`RiskEngine.halted`)
- Ensure exploration_rate > 0 (cold start requires exploration)

### IBKR Connection Failures
```bash
python test_ibkr_connection.py   # Diagnose connection issues
```
- Verify TWS/Gateway is running
- Check socket settings (localhost:7497 or 4001)
- Confirm API connections enabled in TWS settings

### Test Failures
```bash
pytest -v --tb=short            # Verbose output with short tracebacks
pytest --lf                     # Run last failed tests only
```

### Type Checking Errors
```bash
pyright --verbose               # Show detailed type errors
```
- Check `pyrightconfig.json` for exclusions
- Tests have relaxed type rules (see executionEnvironments)

---

## Performance Optimization Notes

- **Q-table pruning**: Enable LRU eviction (`FSDConfig.max_q_table_states`)
- **Q-value decay**: Prevents obsolete market patterns from dominating decisions
- **Parallel testing**: Use `pytest -n auto` for faster test runs
- **Profiling**: Use `py-spy` or `memory-profiler` (installed in requirements-dev.txt)

---

## Security & Compliance

- **Credentials**: Store in `.env` (never commit to git, see `.gitignore`)
- **API keys**: Use environment variables for IBKR, data providers
- **Audit logs**: All trades logged with timestamps for regulatory compliance
- **Risk controls**: Mandatory for live trading (daily loss limits, drawdown halts)

---

## Future Development Areas

- Auto-reconnect for IBKR connection drops
- Multi-symbol concurrent trading (partially implemented)
- Advanced reward shaping (Sharpe ratio, risk-adjusted returns)
- Hyperparameter optimization for FSD (grid search, Bayesian optimization)
- Real-time monitoring dashboard (beyond simple_gui.py)
