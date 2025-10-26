# Architecture Notes

## Design Goals

1. Deterministic execution without third-party dependencies.
2. Explicit, testable risk enforcement at both trade and portfolio levels.
3. Clear separation between pure computation (research/backtest) and
downstream integrations (broker, telemetry) so the safety case remains intact
as the system grows.

## Module Map

```
aistock/
├── config.py       # Dataclasses (risk, execution, strategy, data quality)
├── data.py         # CSV loader, validation, deterministic multi-symbol feed
├── execution.py    # Paper broker + order lifecycle
├── logging.py      # Structured JSON logging helpers
├── performance.py  # Sharpe/Sortino/expectancy analytics
├── portfolio.py    # Positions, cash, trade log, exposure maths
├── risk.py         # RiskEngine (daily loss, drawdown, leverage, holding period)
├── scenario.py     # Gap/missing/volatility stress generators
├── strategy.py     # Strategy suite (MA crossover, RSI, blending)
├── ml/             # Feature extraction, logistic regression, training pipeline, ML strategy
└── engine.py       # Backtest orchestration + metrics
```

## Control Flow

```
DataSource -> load_csv_directory -> DataFeed.iter_stream
    ↓                                 ↓
StrategySuite ← history buffers  Portfolio ← Broker fills
    ↓                                 ↓
Target weights                  RiskEngine pre/post-trade checks
    ↓                                 ↓
Broker (`aistock.brokers.paper` / `aistock.brokers.ibkr`) orders → ExecutionReport → Portfolio.apply_fill → Equity curve / metrics
```

- **Pre-trade:** RiskEngine validates allocation, leverage, concentration, and
  holding period before orders hit the broker.
- **Execution:** Broker adapters (`aistock.brokers.paper`, `aistock.brokers.ibkr`) apply slippage, route
  orders, and produce `ExecutionReport` events consumed by the portfolio/risk modules.
- **Post-trade:** Portfolio updates realised/unrealised P&L; RiskEngine checks
  drawdown/daily loss and can halt the session.

## Extensibility Hooks

- **Strategies:** Implement `BaseStrategy.generate` and register with
  `StrategySuite`. Confidence weighting allows hybrid signals.
- **Costs:** Replace broker slippage/commission logic (see `ExecutionConfig`).
- **Persistence:** Serialise `Portfolio.snapshot()` and `RiskState` periodically
  for restart or audit trails.
- **Observability:** Pipe structured logs into ELK/Splunk; extend
  `performance.py` with turnover, exposure histograms, etc.
- **Integrations:** A live broker adapter only needs to honour the
  `Order`/`ExecutionReport` contract and feed external fills back through the
  same portfolio/risk path. The GUI Live tab simply wraps `LiveTradingSession`
  so any compliant broker becomes manageable via the dashboard.

## Out of Scope (Future Work)

- Real-time market data ingestion or scheduling layer.
- Hyper-parameter optimisation / walk-forward analysis (planned via
  notebook-driven research).
- Machine-learning models beyond the bundled logistic-regression baseline.
- Regime detection, sector exposure limits, borrow/short availability
  modelling.

Treat these items as separate deliverables with dedicated safety and testing
plans before folding into production branches.
