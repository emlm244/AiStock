# AIStock Robot 🤖

A professional Python-based automated trading system with **3 intelligence modes**: FSD (Full Self-Driving AI), Supervised (AI-Assisted), and BOT (Manual Power User).

## 🎯 Intelligence Modes

### 1️⃣ FSD Mode (Full Self-Driving) - **RECOMMENDED**
- 🤖 **AI makes ALL decisions** using reinforcement learning (Q-Learning)
- 📚 **Learns from every trade** - gets smarter over time
- 🎯 **Fully autonomous** - no parameter tuning required
- 📈 **Stocks only** (optimal data quality)
- **Best for**: Hands-off automated trading

### 2️⃣ Supervised Mode (AI-Assisted)
- 🔧 **AI optimizes parameters**, you choose instruments
- 📊 Uses Bayesian optimization for risk/strategy tuning
- ⚙️ **Semi-autonomous** - AI assistance with human control
- 📈 **Stocks only**
- **Best for**: Active traders who want AI help

### 3️⃣ BOT Mode (Manual Power User)
- 🎛️ **Full manual control** over all parameters
- 📐 Uses rule-based strategies (MA, RSI, Momentum, ML)
- 🌍 **All asset types**: stocks, crypto, AND forex
- **Best for**: Experienced traders, strategy development

## Core Features

- **Reinforcement Learning**: Q-Learning agent that learns optimal trading policies
- **Professional Backtesting**: Backtrader integration with professional infrastructure
- **Live & Paper Trading**: Real-time trading with Interactive Brokers
- **Risk Management**: Daily loss limits, drawdown halts, position sizing
- **Bracket Orders**: Automatic stop-loss and take-profit orders
- **Adaptive Risk**: Volatility-based position sizing and stop-loss adjustment
- **Live Trading Safety**: Explicit opt-in with port detection and confirmation

## Safety & Risk Controls

**Critical safeguards built into the system:**

- **Daily Loss Limit**: Trading halts when daily loss exceeds configured threshold (default: 3% of capital)
- **Maximum Drawdown**: Trading halts at configurable drawdown level (default: 15%)
- **Position Sizing**: Risk-based sizing ensures no single trade risks more than configured amount (default: 1% of equity)
- **No Guaranteed Profits**: This is experimental software. Past performance does not guarantee future results.
- **Paper Trading First**: Always test with paper trading account before risking real capital.

## Prerequisites

- Python 3.8+
- Interactive Brokers account (Paper or Live)
- TWS (Trader Workstation) or IB Gateway running and configured
- API access enabled in TWS/Gateway settings

## Setup

### 1. Clone and Install Dependencies

```bash
git clone <repository-url>
cd AiStock
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and set **required** values:

```bash
# Required
IBKR_ACCOUNT_ID=YOUR_ACCOUNT_ID_HERE  # Your IB account ID (e.g., DU1234567)

# Optional (defaults provided)
IBKR_TWS_HOST=127.0.0.1
IBKR_TWS_PORT=7497  # 7497=Paper, 7496=Live, 4002=Gateway Paper, 4001=Gateway Live
IBKR_CLIENT_ID=1001
TIMEZONE=America/New_York
LOG_LEVEL=INFO
```

**Never commit your `.env` file.** It is already excluded via `.gitignore`.

### 3. Enable API in TWS/Gateway

1. Open TWS or IB Gateway
2. Go to **File → Global Configuration → API → Settings**
3. Enable **"Enable ActiveX and Socket Clients"**
4. Add `127.0.0.1` to **Trusted IP Addresses**
5. Set **Socket Port** to match your `IBKR_TWS_PORT` (7497 for paper trading)
6. **Uncheck** "Read-Only API" if you want to place orders
7. Click **OK** and restart TWS/Gateway

### 4. Verify Installation

Test that credentials are loaded correctly:

```bash
python -c "from config.credentials import IBKR; print(IBKR)"
```

You should see your configuration without errors.

## Usage

### Running the Trading Bot

#### Interactive Mode (RECOMMENDED for first-time users)

```bash
python main.py
```

You'll be prompted to select:
1. **Intelligence Mode**: FSD (AI), Supervised (AI-assisted), or BOT (manual)
2. **Asset Type**: Stocks (FSD/Supervised) or Stocks/Crypto/Forex (BOT)
3. **Instruments**: Which symbols to trade
4. **Live Trading**: Paper (default) or Live (requires explicit confirmation)

#### Headless Mode (for automation)

**FSD Mode (Full Self-Driving AI)**:
```bash
python main.py --headless --intelligence-mode fsd --instruments "AAPL,MSFT,GOOGL"
```

**Supervised Mode (AI-Assisted)**:
```bash
python main.py --headless --intelligence-mode supervised --instruments "SPY,QQQ,IWM"
```

**BOT Mode (Manual Control)**:
```bash
# Stocks
python main.py --headless --intelligence-mode bot --mode stock --instruments "AAPL,TSLA"

# Crypto
python main.py --headless --intelligence-mode bot --mode crypto --instruments "BTC/USD,ETH/USD"

# Forex
python main.py --headless --intelligence-mode bot --mode forex --instruments "EUR/USD,GBP/USD"
```

#### Legacy Headless Mode (backwards compatible)

For backwards compatibility (defaults to BOT mode):

```bash
# Basic headless run with crypto
python main.py --headless --mode crypto --instruments "BTC/USD,ETH/USD"

# Stock trading with extended hours
python main.py --headless --mode stock --instruments "SPY" --extended-hours

# Disable autonomous features (BOT mode)
python main.py --headless --mode forex --instruments "EUR/USD" --no-autonomous
```

#### Live Trading (requires explicit opt-in)

**⚠️ SAFETY**: Live trading is DISABLED by default. You MUST add `--live-trading` flag:

```bash
# Paper trading (default - no flag needed)
python main.py --headless --intelligence-mode fsd --instruments "AAPL"

# Live trading (requires explicit flag)
python main.py --headless --intelligence-mode fsd --instruments "AAPL" --live-trading
```

In interactive mode, you'll be prompted to confirm live trading if detected.

**Headless CLI Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--headless` | Run without interactive prompts | False |
| `--intelligence-mode` | **FSD**, supervised, or bot | bot (safest) |
| `--mode` | Asset type: stock, crypto, forex | BOT mode only |
| `--instruments` | Comma-separated symbols | Mode defaults |
| `--live-trading` | **Enable live trading** (explicit opt-in) | False (paper) |
| `--autonomous` / `--no-autonomous` | Adaptive strategies/risk | True |
| `--adaptive-risk` / `--no-adaptive-risk` | Volatility-based SL/TP | True |
| `--auto-retrain` / `--no-auto-retrain` | Auto ML retraining | True |
| `--dynamic-weighting` / `--no-dynamic-weighting` | Dynamic strategy weights | True |
| `--extended-hours` | Extended hours (stocks only) | False |

The bot will:
1. Connect to Interactive Brokers API
2. Load historical data
3. Subscribe to live market data
4. Evaluate strategies and execute trades
5. Monitor risk and halt if limits breached

**Press `Ctrl+C` to stop gracefully.**

### Training the ML Model

#### Interactive Mode

```bash
python main.py
```

Select option **2** to train the machine learning model.

#### Headless Mode

```bash
python main.py --train
```

Ensure you have historical data in `data/historical_data/` or `data/live_data/`.

The training script will:
- Load and prepare data
- Engineer features
- Train a classifier
- Save the model to `models/ml_model.joblib`

### Backtesting

Run strategies against historical data using the **same feature pipeline** as live trading:

```bash
# Basic backtest
python backtest.py --symbols "BTC/USD,ETH/USD"

# Specify data directory and date range
python backtest.py --symbols "AAPL,MSFT" \
  --data-dir data/historical_data \
  --start-date 2024-01-01 \
  --end-date 2024-12-31

# Save results to custom directory
python backtest.py --symbols "EUR/USD" \
  --output-dir results/forex_backtest
```

**Input Data Format:**

Place CSV files in `data/live_data/` or `data/historical_data/` with this structure:

```csv
timestamp,open,high,low,close,volume
2024-01-01 00:00:00,42000.5,42100.0,41900.0,42050.0,1234.5
2024-01-01 00:30:00,42050.0,42200.0,42000.0,42150.0,2345.6
```

- Timestamp must be parseable by pandas (UTC assumed)
- Filenames: `{SYMBOL}.csv` (slashes replaced with underscores, e.g., `BTC_USD.csv`)

**Output:**

Results saved to `data/backtest_results/` (or `--output-dir`):
- `trades_TIMESTAMP.csv` - All executed trades
- `equity_curve_TIMESTAMP.csv` - Equity over time
- `summary_TIMESTAMP.txt` - Performance statistics

**Backtest Metrics:**
- Total return, Sharpe ratio, max drawdown
- Number of trades, win rate, profit factor
- Average win/loss per trade

**Important:** Backtest uses the same indicators, strategies, and feature engineering as live trading, ensuring results reflect production behavior.

## Configuration

All configuration is in `config/settings.py`. Key settings include:

- **Risk Management**: `MAX_DAILY_LOSS`, `MAX_DRAWDOWN_LIMIT`, `RISK_PER_TRADE`
- **Strategies**: `ENABLED_STRATEGIES` - enable/disable individual strategies
- **Indicators**: RSI, MACD, ATR periods and thresholds
- **Stop Loss/Take Profit**: `STOP_LOSS_TYPE`, `TAKE_PROFIT_TYPE`, multipliers
- **Timeframe**: `TIMEFRAME` - bar aggregation period (e.g., '30 secs', '5 mins')

**Do not weaken risk controls.** The default limits are conservative for safety.

## Project Structure

```
AIStock/
├── aistock/           # 🆕 Backtrader integration + FSD engine
│   ├── backtrader_integration.py  # Professional backtesting
│   ├── fsd.py                      # 🤖 Q-Learning RL agent
│   ├── config.py                   # Backtest configurations
│   ├── data.py                     # Bar dataclass + loading
│   ├── portfolio.py                # Portfolio tracking
│   ├── performance.py              # Metrics (Sharpe, Sortino, etc.)
│   ├── risk.py                     # Risk engine
│   ├── strategy.py                 # Strategy suite
│   └── logging.py                  # Structured logging
│
├── aggregator/        # Tick-to-bar data aggregation
├── api/              # Interactive Brokers API wrapper
├── config/           # Settings and credentials (env-based)
├── data/             # Market data storage (excluded from git)
├── indicators/       # Technical indicators (RSI, MACD, ATR, etc.)
├── logs/             # Application logs (excluded from git)
├── managers/         # Order, portfolio, risk, strategy managers
├── models/           # Trained ML models (excluded from git)
├── persistence/      # State management
├── strategies/       # Trading strategy implementations
├── tests/            # Test suite (pytest)
├── utils/            # Utilities (logging, data utils, etc.)
│
├── .env.example      # 🆕 Environment template (COPY TO .env)
├── main.py           # ✅ UPDATED - 3-mode selection
├── backtest.py       # Legacy backtesting (will be deprecated)
├── train_model.py    # ML model training script
└── requirements.txt  # ✅ UPDATED - Added backtrader
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IBKR_ACCOUNT_ID` | **Yes** | None | Your IB account ID |
| `IBKR_TWS_HOST` | No | `127.0.0.1` | TWS/Gateway host |
| `IBKR_TWS_PORT` | No | `7497` | TWS/Gateway port |
| `IBKR_CLIENT_ID` | No | `1001` | Unique client ID |
| `TIMEZONE` | No | `America/New_York` | Timezone for logs and resets |
| `LOG_LEVEL` | No | `DEBUG` | Logging verbosity |

## Testing

Automated tests using pytest cover critical functionality:

### Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_risk_manager.py

# Run tests matching a pattern
pytest -k "test_bracket"
```

### Test Coverage

- **Bar Aggregation** (`test_aggregator.py`): Tick-to-bar conversion edge cases, boundary conditions, thread safety
- **Risk Management** (`test_risk_manager.py`): Daily loss limits, drawdown halts, recovery conditions
- **Order Assembly** (`test_orders.py`): Bracket order creation, parameter validation, tracking
- **Indicators** (`test_indicators.py`): RSI, MACD, ATR, SMA/EMA calculations, edge cases

### Writing Tests

Place new tests in `tests/test_*.py`. Follow existing patterns:

```python
import pytest

def test_my_feature():
    # Arrange
    input_data = ...

    # Act
    result = my_function(input_data)

    # Assert
    assert result == expected_value
```

## CI/CD

Continuous Integration via GitHub Actions runs on every push and pull request:

### Workflow Steps

1. **Linting**: Ruff checks code style and common errors
2. **Testing**: Pytest runs test suite on Python 3.9, 3.10, 3.11
3. **Coverage**: Coverage reports uploaded (Python 3.9 only)

### Running Locally

```bash
# Lint code
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Format code
ruff format .

# Check formatting without modifying
ruff format --check .
```

### CI Configuration

- Workflow: `.github/workflows/ci.yml`
- Linting config: `ruff.toml`
- Test config: `pytest.ini`

The CI pipeline fails if:
- Linting errors are detected
- Any test fails
- Code formatting doesn't match ruff standards

## Security Notes

- **Never commit secrets**: The `.env` file is excluded via `.gitignore`
- **Never print secrets**: The code does not log sensitive credentials
- **Use environment variables only**: All credentials must be set via `.env` or exported environment variables
- **Review your `.env`**: Ensure `IBKR_ACCOUNT_ID` and port are correct before starting

## Troubleshooting

### "IBKR_ACCOUNT_ID environment variable is required"
- Ensure you copied `.env.example` to `.env`
- Set `IBKR_ACCOUNT_ID=YOUR_ACCOUNT_ID` in `.env`

### "API connection timeout"
- Verify TWS/Gateway is running
- Check that API settings are enabled (see Setup step 3)
- Confirm `IBKR_TWS_PORT` matches TWS port configuration

### "Trading halted - Max daily loss"
- Risk manager has halted trading due to daily loss exceeding limit
- Check `logs/app.log` for details
- Review `MAX_DAILY_LOSS` setting in `config/settings.py`
- Resets automatically at start of next trading day

### Data subscription errors
- Some symbols may not be available or require market data subscriptions
- Check TWS market data subscriptions for the asset class you're trading

## License

See [LICENSE](LICENSE) file.

## Disclaimer

**This software is for educational and research purposes only.**

- No warranty or guarantee of profits
- Trading involves substantial risk of loss
- Past performance is not indicative of future results
- Test thoroughly with paper trading before using real capital
- The authors are not responsible for any financial losses

**Use at your own risk.**
