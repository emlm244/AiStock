# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AIStocker is a Python-based automated trading system that connects to Interactive Brokers, implements multiple trading strategies (including ML-based), and executes bracket orders with comprehensive risk management. The system supports stocks, crypto, and forex trading with autonomous adaptation features.

## Essential Commands

### Development & Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_risk_manager.py

# Run tests matching a pattern
pytest -k "test_bracket"

# Lint code
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Format code
ruff format .
```

### Running the System
```bash
# Interactive mode (prompts for configuration)
python main.py

# Headless mode (production/CI)
python main.py --headless --mode crypto --instruments "BTC/USD,ETH/USD"

# Train ML model
python main.py --train

# Backtest strategies
python backtest.py --symbols "BTC/USD,ETH/USD" --start-date 2024-01-01
```

### Configuration
- Environment variables are loaded from `.env` file (NEVER commit this)
- Required: `IBKR_ACCOUNT_ID`
- Optional: `IBKR_TWS_HOST`, `IBKR_TWS_PORT`, `TIMEZONE`, `LOG_LEVEL`
- All settings in `config/settings.py` can be overridden via prompts or CLI args

## Architecture & Key Components

### Data Flow (Critical Understanding)
1. **IBKR API** (`api/ibkr_api.py`) receives live tick data ’ pushes to `live_ticks_queue`
2. **Data Aggregator** (`aggregator/data_aggregator.py`) consumes ticks ’ builds time-based bars ’ pushes to symbol-specific `bar_queues`
3. **Main Loop** (`main.py::TradingBot.main_loop`) consumes bars ’ updates `self.market_data` dictionary
4. **Strategy Manager** evaluates bars ’ generates signals
5. **Order Manager** executes bracket orders via API

**Important**: All timestamps are UTC-aware throughout the system. Use `datetime.now(pytz.utc)` for current time.

### Manager Responsibilities

**PortfolioManager** (`managers/portfolio_manager.py`)
- Tracks positions, equity, daily PnL, drawdown
- Maintains latest price cache (UTC timestamps)
- Source of truth for position sizing decisions

**RiskManager** (`managers/risk_manager.py`)
- Enforces daily loss limits and max drawdown halts
- Pre-trade risk checks (position size, available funds)
- Trading can be halted globally; check `risk_manager.is_trading_halted()`

**StrategyManager** (`managers/strategy_manager.py`)
- Loads enabled strategies from `settings.ENABLED_STRATEGIES`
- Calculates dynamic strategy weights based on regime and performance
- Aggregates signals using weighted voting

**OrderManager** (`managers/order_manager.py`)
- Creates bracket orders (parent + stop-loss + take-profit)
- Tracks order states and handles fills/cancellations
- All order IDs are managed through `api.get_next_req_id()`

### State Management & Persistence

**StateManager** (`persistence/state_manager.py`)
- Saves/loads bot state to `data/bot_state.json`
- Includes portfolio positions, orders, equity tracking
- Auto-saves every `STATE_SAVE_INTERVAL_SECONDS` (default: 300)

**BackupManager** (`persistence/backup_manager.py`)
- Creates timestamped backups of state files
- Rotates old backups based on retention policy

### Autonomous Features

When `AUTONOMOUS_MODE = True` (configurable at startup):

**Adaptive Risk** (`ENABLE_ADAPTIVE_RISK`)
- Adjusts stop-loss/take-profit based on volatility regime
- Uses ATR multipliers scaled by volatility level
- Volatility regimes: Low, Normal, High, Squeeze

**Auto ML Retraining** (`ENABLE_AUTO_RETRAINING`)
- Triggers when ML win rate drops below threshold OR time interval elapsed
- Runs in background thread pool executor
- MLStrategy signals retraining via class-level flag

**Dynamic Strategy Weighting** (`ENABLE_DYNAMIC_STRATEGY_WEIGHTING`)
- Adjusts strategy weights based on recent performance + market regime
- Regime detection influences base weights (trend vs ranging)
- Performance calculated over `STRAT_PERF_LOOKBACK_DAYS`

### Market Regime Detection

**MarketRegimeDetector** (`utils/market_analyzer.py`)
- Detects trend direction: Trending Up/Down/Ranging
- Detects volatility level: Low/Normal/High/Squeeze
- Updated periodically in main loop (every `MARKET_REGIME_UPDATE_INTERVAL_SECONDS`)
- Influences strategy weights and risk parameters

### Contract Handling (Critical)

**Contract Utilities** (`contract_utils.py`)
- `create_contract(symbol, api)`: Creates Contract object with heuristic/cached details
- `get_contract_details(symbol, api)`: Retrieves ContractDetails from cache
- `get_min_tick(symbol, api)`: Gets minimum price increment
- `get_min_trade_size(symbol, api)`: Gets minimum tradeable quantity
- `round_price(price, min_tick)`: Rounds price to valid tick increment
- `round_quantity(qty, min_size)`: Rounds quantity to valid size increment

**Always** round prices and quantities before placing orders to avoid rejections.

## Critical Patterns & Conventions

### Threading & Locks
- Main trading loop runs in `bot.main_thread` (daemon)
- API message loop runs in `api.api_thread` (daemon)
- Data aggregator runs in `data_aggregator.thread` (daemon)
- Use `self._lock` for accessing shared state in TradingBot
- Use `api.api_lock` for API state access
- Use `data_aggregator._subscribe_lock` for subscription state

### Startup Sequence (Important)
1. Load settings & setup logging
2. Initialize managers (PM ’ RM/SM/OM)
3. Initialize API connection
4. **Wait for `api.api_ready` event** (blocks until connected + initial data received)
5. Request contract details, wait for completion
6. Request historical data for instruments
7. Start main loop

Violating this order causes failures (e.g., requesting data before connection ready).

### Error Handling Philosophy
- Log errors comprehensively (`error_logger.error()` with `exc_info=True`)
- Graceful degradation: aggregator continues on errors (doesn't halt)
- Circuit breaker pattern used for API calls (`@with_circuit_breaker`)
- Retries with exponential backoff via `tenacity` library

### Stop Loss & Take Profit Calculation
Types: `PERCENT`, `ATR`, or `RATIO` (for TP)

**ATR-based** (preferred when `ENABLE_ADAPTIVE_RISK`):
```python
sl_distance = STOP_LOSS_ATR_MULTIPLIER * vol_multiplier * current_atr
stop_loss_price = entry_price - sl_distance  # for BUY
stop_loss_price = entry_price + sl_distance  # for SELL
```

**Always validate**:
- SL must be worse than entry (BUY: SL < entry; SELL: SL > entry)
- TP must be better than entry (BUY: TP > entry; SELL: TP < entry)
- Round to min_tick after calculation

### Position Sizing (Critical)
See `utils/data_utils.py::calculate_position_size()`

1. Calculate risk per unit: `|entry_price - stop_loss_price|`
2. Risk capital: `total_equity * RISK_PER_TRADE` (default 1%)
3. Initial quantity: `risk_capital / risk_per_unit`
4. Adjust for available funds, commission, slippage
5. **Round to min_trade_size increment**
6. Validate quantity > 0 and within limits

## Testing Strategy

### Test Coverage
- `test_aggregator.py`: Tick-to-bar aggregation, edge cases, thread safety
- `test_risk_manager.py`: Daily loss limits, drawdown halts, recovery
- `test_orders.py`: Bracket order assembly, validation, tracking
- `test_indicators.py`: Technical indicator calculations

### Testing Best Practices
- Use `pytest.mark.parametrize` for edge cases
- Mock IBKR API calls to avoid real connections
- Test with aware UTC datetimes (use `pytz.utc`)
- Verify thread safety where applicable

## Common Development Scenarios

### Adding a New Strategy
1. Create class in `strategies/` inheriting from base strategy interface
2. Implement `generate_signal(symbol, market_data)` returning -1/0/1
3. Define `min_data_points` property
4. Add to `settings.ENABLED_STRATEGIES`
5. Update `StrategyManager._load_strategies()` to instantiate
6. Add regime weights in `StrategyManager.regime_base_weights`

### Adding a New Indicator
1. Create function in appropriate `indicators/` module
2. Accept DataFrame with OHLCV columns and UTC DatetimeIndex
3. Return pandas Series with same index
4. Handle edge cases (insufficient data, NaN values)
5. Add tests in `tests/test_indicators.py`

### Modifying Risk Parameters
- **Never weaken** `MAX_DAILY_LOSS` or `MAX_DRAWDOWN_LIMIT` without explicit user request
- Document reasoning for any risk parameter changes
- Test with backtesting before deploying to live trading

### Debugging Connection Issues
1. Verify TWS/IB Gateway is running
2. Check API is enabled in TWS settings (File ’ Global Configuration ’ API)
3. Confirm port matches `IBKR_TWS_PORT` (7497=Paper, 7496=Live)
4. Check `logs/app.log` for connection status messages
5. Validate `IBKR_ACCOUNT_ID` matches your account

## Data File Formats

### Historical/Live Data CSVs
Location: `data/historical_data/` or `data/live_data/`
Format:
```csv
timestamp,open,high,low,close,volume
2024-01-01 00:00:00,42000.5,42100.0,41900.0,42050.0,1234.5
```
- UTC timestamps (parseable by pandas)
- Filename: `{SYMBOL}.csv` (slashes ’ underscores, e.g., `BTC_USD.csv`)

### State File
Location: `data/bot_state.json`
- Contains: positions, orders, equity snapshots, last update time
- Auto-saved periodically
- Loaded on startup for state recovery

## Security & Deployment Notes

- **Never commit** `.env` or files containing credentials
- API keys/secrets managed via `config/credentials.py` (loads from `.env`)
- Use environment variables for all sensitive config
- Paper trading port: 7497 (TWS) or 4002 (Gateway)
- Live trading port: 7496 (TWS) or 4001 (Gateway)

## CI/CD Pipeline

GitHub Actions workflow (`.github/workflows/ci.yml`):
1. **Lint**: Ruff checks code style/errors
2. **Test**: Pytest on Python 3.9, 3.10, 3.11
3. **Coverage**: Upload coverage reports (Python 3.9 only)

Pipeline fails if:
- Linting errors detected
- Any test fails
- Code formatting doesn't match ruff standards

## Important Caveats

### Market Hours & Pauses
- Stock market hours checked using exchange timezone
- Crypto assumed 24/7
- Forex closes Friday 5PM ET ’ Sunday 5PM ET
- Trading paused if: market closed, stale data, or subscription errors
- Check `self.symbol_trading_paused[symbol]` before evaluation

### ATR Requirements
- ATR needed when `STOP_LOSS_TYPE='ATR'` or `TAKE_PROFIT_TYPE='ATR'`
- Requires `ATR_PERIOD + 1` bars minimum
- Falls back to last valid ATR if current calculation fails
- Minimum valid ATR threshold: `MIN_ATR_VALUE` (default: 0.0001)

### Headless Mode
- Requires `--mode` argument (stock/crypto/forex)
- Optional: `--instruments`, `--autonomous`, `--adaptive-risk`, etc.
- Suitable for production deployment, Docker, CI
- Example: `python main.py --headless --mode crypto --instruments "BTC/USD"`

### Known Limitations
- Holiday calendars not implemented (uses time-based market hours only)
- Some contract details require manual heuristics if IBKR cache unavailable
- ML model must exist at `models/ml_model.joblib` for ML strategy to load
