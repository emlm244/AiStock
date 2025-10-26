# AIStock Robot (Pro Baseline)

> **Disclaimer:** This project offers tooling for disciplined research, backtesting, and
> paper-trading automation. Markets remain uncertain. No configuration here can
> guarantee profits for any account size. Always validate changes and deploy
> responsibly.

## 🚀 Three Trading Modes

### 1️⃣ BOT Mode - Strategy Autopilot
Rule-based trading with ML-augmented confidence scoring. Uses traditional technical indicators, mean reversion, momentum, and trend-following strategies with machine learning predictions.

**Best for:** Consistent rule-based trading with predictable behavior.

### 2️⃣ Headless Mode - Supervised Autopilot
Fully autonomous operation with automated decision gates, model promotion, and risk adjustments. Removes human intervention while maintaining safety through multi-stage validation.

**Best for:** Hands-off trading with automated supervision and safety gates.

### 3️⃣ FSD Mode - Full Self-Driving AI ⭐
Tesla-inspired reinforcement learning mode that learns from every trade. The AI makes all trading decisions autonomously based on continuous learning from market outcomes.

- ✅ Only 2 hard constraints: max_capital, time_limit
- ✅ AI decides when to trade (can choose NOT to trade)
- ✅ Learns from every trade outcome (PnL is the teacher)
- ✅ Saves state between sessions (persistent learning)
- ✅ Q-Learning with epsilon-greedy exploration

**Best for:** Cutting-edge AI trading that improves over time through experience.

**See:** `docs/FSD_VERIFICATION.md` for complete feature verification.

---

## 🎯 Two Interface Modes

### Simple Mode (Beginner-Friendly) 🌟

Perfect for beginners who want to "just turn on the robot and relax":

```bash
# Option 1: Use the launcher (recommended)
python launch_gui.py

# Option 2: Direct launch
python -m aistock              # Defaults to Simple Mode
python -m aistock --simple     # Explicit Simple Mode
python -m aistock.simple_gui   # Direct module launch
```

**What you get:**
- ✅ **3 Simple Questions:**
  1. How much money to start with? (e.g., $200)
  2. Risk level? (Conservative / Moderate / Aggressive)
  3. Click **START ROBOT** button

- ✅ **Auto-Configuration:** Risk presets automatically configure:
  - Conservative: Uses max 30% of capital, tight safety limits
  - Moderate: Uses max 50% of capital, balanced approach
  - Aggressive: Uses max 70% of capital, faster gains

- ✅ **Clean Dashboard:** See your balance, profit/loss, and AI status in real-time

- ✅ **FSD Mode Enabled:** Full Self-Driving AI does everything automatically

- ✅ **Switch Anytime:** Click "Advanced Options" to access full control

### Advanced Mode (Power Users)

Full control center with all features:

```bash
# Option 1: Use the launcher
python launch_gui.py  # Select option 2

# Option 2: Direct launch
python -m aistock --advanced
python -m aistock.gui
```

**What you get:**
- ✅ All 7 tabs: Welcome, Backtesting, Scenario Lab, ML Lab, Live Control, Risk Console, Logs
- ✅ Full configuration control
- ✅ ML model training
- ✅ Scenario stress testing
- ✅ Complete strategy customization
- ✅ Switch to Simple Mode anytime

---

## Highlights

- **Three autonomous modes:** BOT (rule-based), Headless (supervised autopilot), FSD (reinforcement learning AI)
- **Deterministic core:** End-to-end pipeline implemented in the Python 3.12
  standard library. Every run is reproducible by configuration and data
  snapshot alone.
- **Structured observability:** JSON logs, built-in performance analytics
  (Sharpe/Sortino/expectancy), and equity curve exports for rapid diagnostics.
- **Risk-first execution:** Hard stops on drawdowns, daily loss, gross exposure,
  leverage, holding period, and per-symbol caps enforced via
  `aistock.risk.RiskEngine`.
- **Adaptive oversight:** Closed-loop agent monitors live results, validates new
  configurations in simulation, and only deploys safer strategy adjustments when
  performance drifts.
- **Adaptive universe:** Optional momentum/volatility/volume ranking selects the
  highest scoring symbols from any CSV directory—no hard-coded tickers.
- **Professional workflows:** Scenario runner (gaps, missing data, volatility
  spikes), paper broker with idempotent fills, optional IBKR adapter, and
  persistence-ready portfolio snapshots support research ➜ paper hand-offs.
- **Extensible strategies:** Strategy suite composes multiple signal models
  (moving-average crossover, RSI reversion out of the box) while preserving a
  single risk/equity path.
- **Operator friendly:** Tkinter GUI (`python3 -m aistock.gui`) for quick
  backtests, scenario stress tests, ML training, and live session management—no
  CLI required.

## Quickstart

### For Beginners: Simple Mode

Launch the beginner-friendly interface:

```bash
python launch_gui.py
# Press 1 or just hit Enter to use Simple Mode
```

**Or directly:**
```bash
python -m aistock  # Defaults to Simple Mode
```

Then:
1. Enter your starting capital (e.g., $200)
2. Choose your risk level (Conservative/Moderate/Aggressive)
3. Click **START ROBOT** and watch the AI trade!

### For Power Users: Advanced Mode

Launch the full control center:

```bash
python launch_gui.py
# Press 2 for Advanced Mode
```

**Or directly:**
```bash
python -m aistock --advanced
# or
python -m aistock.gui
```

Then explore:
1. **Welcome Tab** – read the feature map and workflow overview.
2. **Backtesting Studio** – point to historical data, configure strategy settings, optionally toggle the ML model, then run a backtest.
3. **Scenario Lab** – apply gap/missing/volatility stresses to benchmark robustness.
4. **ML Lab** – train or refresh the logistic-regression model and push the path into other tabs.
5. **Live Control** – choose `paper` for simulation or `ibkr` for live trading (requires `ibapi==9.81.1`). Monitor positions, trades, and risk KPIs in the adjacent tabs.

All analytics, stress tests, ML training, and live execution are now operated exclusively from the control center. No command-line flags are required.

## Architecture Overview

| Module              | Responsibility                                                                 |
| ------------------- | ------------------------------------------------------------------------------ |
| `aistock.config`    | Declarative configuration: risk, execution, data quality, strategy params.     |
| `aistock.data`      | CSV ingestion, validation, deterministic multi-asset feed.                     |
| `aistock.strategy`  | Strategy suite (MA crossover + RSI) returning target weights with confidence.  |
| `aistock.fsd`       | 🆕 FSD AI Mode - Reinforcement learning trading with Q-Learning.                |
| `aistock.brokers`   | Paper broker + IBKR adapter sharing a common interface.                         |
| `aistock.execution` | Order and execution data structures used across brokers.                       |
| `aistock.portfolio` | Position & cash accounting, trade log, turnover primitives.                    |
| `aistock.risk`      | Hard risk gates (daily loss, drawdown, leverage, holding period, per-symbol).  |
| `aistock.engine`    | Backtest orchestration, equity curve capture, performance metrics.             |
| `aistock.session`   | Live/paper trading session orchestrator (IBKR or simulated feeds).             |
| `aistock.scenario`  | Gap / missing data / volatility spike generators for stress testing.           |
| `aistock.logging`   | Structured logging helper (JSON).                                              |
| `aistock.gui`       | Tkinter control centre for backtests, scenarios, live trading, and dashboards. |
| `aistock.simple_gui`| 🆕 Beginner-friendly interface with FSD quick-start (3 questions only).         |

## Risk Safeguards

`RiskLimits` adds professional controls:

- `max_daily_loss_pct`, `max_drawdown_pct` – circuit breakers reset daily using
  start-of-day equity as the loss baseline.
- `max_gross_exposure`, `max_leverage` – portfolio-wide checks per trade and
  post-trade.
- `per_symbol_notional_cap`, `max_single_position_units` – limit concentration.
- `max_holding_period_bars` – prevents stale positions.
- Kill switch engages when equity ≤ 0 or drawdown exceeds tolerance; while
  halted the engine still permits flattening/covering trades so operators can
  neutralise risk.

Each guard is validated in unit tests (`tests/test_risk_engine.py`) and in the
backtest loop before orders are handed to the broker.

## Broker Integration (IBKR)

- Optional dependency: `pip install ibapi==9.81.1`.
- Configure connection via `BrokerConfig` (`ib_host`, `ib_port`, `ib_client_id`,
  `ib_account`, and per-symbol `ContractSpec`). The GUI Live tab exposes these
  fields for interactive control.
- `aistock.brokers.ibkr.IBKRBroker` wraps connection management, advanced
  contract metadata, order routing, and real-time bar subscriptions.
- `aistock.session.LiveTradingSession` composes strategies, risk, sizing, and
  broker callbacks. `snapshot()` exposes positions/equity for dashboards.
- Example skeleton:

  ```python
  from datetime import timezone
  from aistock.config import BacktestConfig, BrokerConfig, ContractSpec, DataSource
  from aistock.session import LiveTradingSession

  config = BacktestConfig(
      data=DataSource(path="data/live", timezone=timezone.utc, symbols=["MSFT"], warmup_bars=60),
      broker=BrokerConfig(
          backend="ibkr",
          ib_host="127.0.0.1",
          ib_port=7497,
          ib_client_id=7,
          contracts={
              "MSFT": ContractSpec(symbol="MSFT", sec_type="STK", exchange="SMART", currency="USD"),
          },
      ),
  )
  session = LiveTradingSession(config)
  session.start()
  # session.stop() when finished
  ```

  Risk controls remain active in live mode; any violation halts future orders
  and surfaces in the GUI Risk Dashboard.

## Dynamic Universe Selection

Leave `DataSource.symbols` empty and supply a `UniverseConfig` to rank all
available CSVs automatically. The selector scores each instrument by blended
momentum, volatility, and average volume, then returns the strongest
opportunities—perfect for broad paper tests before promoting a curated list to
live trading.

```python
from aistock.config import BacktestConfig, DataSource, EngineConfig, UniverseConfig
from aistock.engine import BacktestRunner

config = BacktestConfig(
    data=DataSource(path="data/usa_equities", warmup_bars=120, enforce_trading_hours=False),
    engine=EngineConfig(),
    universe=UniverseConfig(max_symbols=5, min_avg_volume=50_000, lookback_bars=180),
)

runner = BacktestRunner(config)
result = runner.run()
print(result.metrics)
```

The same configuration can initialise `LiveTradingSession`; resolved symbols are
logged before trading begins so operators can audit the picks.

## Autonomous Adaptation Loop

Wire up `AdaptiveAgent` to keep the session aligned with operator intent:

```python
from aistock import AdaptiveAgent, ObjectiveThresholds, LiveTradingSession

agent = AdaptiveAgent(
    training_config=backtest_config,  # Historical dataset for validation
    objectives=ObjectiveThresholds(min_sharpe=0.8, max_drawdown=0.18),
)

decision = agent.evaluate_and_adapt(live_session)
if decision:
    print("Applied:", decision.applied_config.engine.strategy)
```

The agent:

- Monitors fills, equity curve, and risk state to detect degradations.
- Generates conservative strategy/risk adjustments (e.g., longer windows, ML
  enablement, tighter exposure caps).
- Runs a full backtest on historical data before touching the live session.
- Applies the new configuration only if simulation clears the thresholds.

## Preparing Multi-Asset Datasets

Give the adaptive loop the broadest picture you can. If you do not yet have a
clean multi-year feed on hand, bootstrap one locally:

```bash
python3 scripts/generate_synthetic_dataset.py \
  --out data/simulated/us_equities \
  --symbols AAPL MSFT NVDA AMZN META \
  --start 2020-01-02 --end 2023-12-29 --frequency daily
```

That produces ready-to-use CSVs (one per symbol) compatible with
`load_csv_directory`. Point both the backtest config and the adaptive agent’s
`training_config` at the generated directory for fast validation. When you later
swap in production-grade data, match the same folder layout and rerun the agent
simulation to confirm metrics hold.

## Calibrating Objective Thresholds

Baseline thresholds should reflect your risk policy, not guesses. Run a
representative backtest and ask the calibration helper to convert its outcomes
into actionable guardrails:

```bash
python3 scripts/calibrate_objectives.py \
  --data data/simulated/us_equities \
  --symbols AAPL MSFT NVDA AMZN META \
  --frequency daily \
  --output calibration.json
```

The JSON output maps directly to `ObjectiveThresholds`; feed it to
`AdaptiveAgent` so the live monitor knows when to intervene. Re-run calibration
whenever strategy parameters or datasets change materially.

## Scheduled Autopilot Run

Glue everything together with the autopilot pipeline—it ingests new CSV drops,
re-trains the ML model, backtests, and emits fresh thresholds/state in one go:

```bash
python3 scripts/generate_synthetic_dataset.py --out data/simulated/us_equities \
  --symbols AAPL MSFT NVDA AMZN META --start 2020-01-02 --end 2023-12-29
```

Or programmatically:

```python
from aistock import (
    AutoCalibrationConfig,
    AutoPilot,
    AutoTrainingConfig,
    PipelineConfig,
    DataIngestionConfig,
    EngineConfig,
    StrategyConfig,
    RiskLimits,
)

pipeline = PipelineConfig(
    symbols=["AAPL", "MSFT"],
    ingestion=DataIngestionConfig(
        staging_dir="data/staging",
        curated_dir="data/curated",
        manifest_path="state/ingestion_manifest.json",
    ),
    training=AutoTrainingConfig(model_path="models/autopilot_model.json"),
    calibration=AutoCalibrationConfig(output_path="state/thresholds.json"),
    engine=EngineConfig(strategy=StrategyConfig(short_window=5, long_window=12)),
)

autopilot = AutoPilot(pipeline)
report = autopilot.run_once()
print(report.thresholds)
```

Hook `AutoPilot.run_once()` into cron/Airflow/etc. to keep the dataset, model,
and guardrails fresh without manual babysitting.

## Asset-Class Risk Policies

Different desks, different limits. Pass a `dict` of `AssetClassPolicy` objects
to `AdaptiveAgent` to tighten exposure automatically for sensitive asset
classes (e.g., crypto, leveraged ETFs). Policies override contract metadata
and cap per-symbol allocation whenever a symbol in that asset class triggers an
adaptation. Smoke tests ensure the agent reconfigures both `ContractSpec` and
risk limits before orders resume.

## GUI Quick Look

- Launch with `python3 -m aistock.gui`.
- Use the hero header's **Start Guided Tour** for a step-by-step orientation of every workspace.
- Jump between tabs with the quick links bar; the context panel updates with plain-language instructions per tab.
- Browse to a data directory, specify symbols/windows, and run backtests or scenarios directly from the GUI.
- Results (P&L, drawdown, Sharpe) stream into the console panel for quick iteration, while live sessions update trades and risk dashboards in real time.

## Scenario & Stress Testing

Built-in scenarios:

- `gap` — introduce opening gaps (default +5%).
- `vol` — widen high/low ranges for volatility spikes.
- `missing` — stochastic bar drops to test resiliency to data holes.

Run results are emitted per scenario, making it easy to compare max drawdown,
return, and secondary metrics. The GUI Scenario Lab tab wraps the same engine
for point-and-click experimentation.

## Machine Learning Workflow (GUI)

1. Open the **ML Lab** tab.
2. Choose a dataset directory and list of symbols to include.
3. Configure feature lookback, prediction horizon, epochs, and learning rate.
4. Click *Train Model* to build a deterministic logistic-regression classifier.
5. Press *Load Model into Sessions* to push the resulting JSON path into the Backtesting and Live tabs.

The ML strategy automatically blends with rule-based signals once `ml_enabled`
is toggled and a model path is provided. Accuracy statistics are displayed
after every training run, giving immediate feedback on model quality.

## Development Workflow

1. **Data hygiene** – place ISO-8601 OHLCV CSVs under a timestamped directory.
2. **Unit tests** – `python3 -m unittest discover -s tests` (all standard
   library; no pip installs needed).
3. **Backtest** – iterate in the GUI Backtesting Studio or instantiate `BacktestRunner`
   programmatically, optionally passing pre-loaded data for notebook workflows.
4. **Stress** – run targeted scenarios before promoting changes to paper/live.

## Extending Strategies

```python
from decimal import Decimal
from aistock.strategy import BaseStrategy, StrategyContext, TargetPosition

class BreakoutStrategy(BaseStrategy):
    name = "Breakout"

    def min_history(self) -> int:
        return 50

    def generate(self, context: StrategyContext) -> TargetPosition:
        highs = [bar.high for bar in context.history[-50:]]
        breakout = max(highs)
        if context.history[-1].close > breakout:
            return TargetPosition(context.symbol, Decimal("1"), confidence=0.7)
        return TargetPosition(context.symbol, Decimal("0"), confidence=0.0)
```

Register the strategy through the `StrategySuite` (see `aistock.engine`). Always
add regression tests and scenario coverage for new logic.

## Testing

```
python3 -m unittest discover -s tests
```

Coverage includes:

- Data validation and timestamp handling (`tests/test_data_loader.py`).
- Risk gates & pre-trade checks (`tests/test_risk_engine.py`).
- Paper broker order fills (`tests/test_broker.py`).
- Scenario transformations (`tests/test_scenario.py`).
- End-to-end backtest integration (`tests/test_backtest.py`).

Add new tests under `tests/`—all suites run quickly and require no external
resources.

## Next Steps (Optional)

- Extend IBKR integration with advanced order types, contract routing, and
  richer market data subscriptions.
- Persist portfolio/risk snapshots (e.g., SQLite) for restart resilience.
- Expand metrics (turnover, exposure heatmaps) or integrate with external
  telemetry sinks.
- Introduce walk-forward optimisation pipelines and multiple-testing deflation.
- Add plug-in strategy modules (ML, reinforcement learning) once the research
  stack is in place.

Remember: sophisticated tooling increases discipline and transparency, not
certainty. Always limit risk to capital you can afford to lose.
