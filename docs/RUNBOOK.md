# AIStock Robot Runbook

## Overview

The production run path currently supports the **Pro Baseline** in research
and paper modes. Live trading still requires an explicit integration effort with
a broker adapter that mirrors the interfaces in `aistock.brokers.paper.PaperBroker`
and the risk/portfolio modules.

All timestamps are processed as UTC. Historical CSV data *must* be
pre-adjusted (splits/dividends) and free of survivorship bias before it is
ingested.

## Startup Checklist

1. Verify Python ≥ 3.12 is available (no third-party packages needed).
2. Ensure the data directory contains ISO-8601 timestamped CSVs with the schema:

   ```
   timestamp,open,high,low,close,volume
   ```

3. Launch the GUI:

   ```
   python3 -m aistock.gui
   ```

   Use the Backtest or Scenario tabs for research and the Live tab for paper/IBKR control.
4. Review the GUI dashboards for trade counts, drawdowns, Sharpe/Sortino, and save CSV artefacts via the Backtest tab if needed.

## Daily Operations (Research / Backtest)

| Step | Action | Owner |
| ---- | ------ | ----- |
| 1 | Pull latest data snapshot into local directory. | Data Ops |
| 2 | Run `python3 -m unittest discover -s tests` to validate code before analysis. | Dev |
| 3 | Backtest via GUI (Backtest tab); export logs/CSV artefacts as needed. | Quant |
| 4 | Run Scenario Lab before promoting changes to live. | Quant |
| 5 | Archive configuration, scenario parameters, and data fingerprint for reproducibility. | DevOps |
| 6 | Train/refresh ML models in the GUI ML tab before enabling ML strategy. | Quant |

## Kill Switch Behaviour

- `RiskEngine` halts trading when:
  - Daily loss exceeds configured percentage of start-of-day equity.
  - Portfolio drawdown breaches the limit.
  - Equity drops to or below zero (absolute kill switch).
- When halted, only flattening/covering trades are allowed; any attempt to
  increase or reverse exposure raises `RiskViolation`. Reset occurs
  automatically on the next session boundary.

## Restart / Recovery

1. Persist the `Portfolio` snapshot (cash, positions, realised PnL).
2. Persist the accompanying `RiskState` (daily PnL, peak equity, halt status).
3. On restart, recreate `Portfolio` and `RiskEngine` from those snapshots before
   processing new market data (same as paper broker flow). The Live tab will
   reflect the restored state after the session resumes.
4. Client order deduplication is automatic: `OrderIdempotencyTracker` uses deterministic
   IDs (symbol + timestamp + signed quantity) and prunes stale IDs on the first bar
   of every session day, so restarts can safely resume without manual cleanup.

## Incident Response

- **Unexpected halt**: Inspect `risk.halt_reason()` and confirm whether limits
  were genuinely hit. If not, validate configuration and input data integrity.
- **Data gap**: Remove or repair offending rows. The loader fails fast with
  descriptive errors.
- **Metric divergence**: Reproduce with the saved configuration and dataset.
  Compare structured log timelines (`Backtest` logger) for unexpected fills.

## Live Session Notes

- **Paper simulation:** Load a dataset directory in the GUI Live tab and press
  *Start Session* (backend `paper`). Bars are replayed with the configured
  delay, positions/trades update in real time, and risk metrics refresh every
  second.
- **IBKR session:** Install `ibapi`, set backend to `ibkr`, and fill host/port/
  client/account fields. Press *Start Session* to connect; the risk dashboard
  reflects fills as they arrive from TWS/Gateway. Use *Stop Session* for a clean
  disconnect.
- **Safety:** If `RiskEngine` halts trading, the GUI shows `Risk Halted=True`
  along with the halt reason. Resolve the issue, then restart the session.

## Open Tasks for Production Hardening

1. Persistent storage for trades, equity curve, and risk state (SQLite or Postgres).
2. Heartbeats + connectivity watchdog with automatic broker reconnect & alerts.
3. Structured logging/metrics pipeline (e.g., OTLP, Prometheus).
4. Advanced order management (modifies, partials) surfaced in GUI tables.
5. Automated incident playbooks integrating with on-call tooling.
