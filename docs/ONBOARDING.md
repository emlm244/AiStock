# Developer Onboarding

## Prerequisites
- Python 3.12+ (standard library only)
- Familiarity with decimal arithmetic and CSV-based datasets

## First 15 Minutes
1. Clone the repository and ensure tests pass:
   ```
   python3 -m unittest discover -s tests
   ```
2. Inspect the pro baseline architecture:
   ```
   less aistock/engine.py
   ```
3. Launch the control center:
   ```
   python3 -m aistock.gui
   ```
4. In the **Backtesting** tab, run a sample backtest using `tests/fixtures` and review the output panel.
5. Open the **Scenario Lab** tab, run the default suite (Gap/Vol/Missing) and inspect the result table.
6. On the GUI's **Live Control** tab, start a paper simulation (backend `paper`) to see
   positions and risk dashboards update in real time.
7. Explore the **ML Lab** tab to train a logistic model and load it into backtests
   or live sessions without leaving the GUI.

## Development Workflow
- Create feature branches off `main`.
- Add targeted unit tests for every behavioural change (multi-asset, risk, broker).
- Update the relevant docs in `docs/` (architecture, runbook, dependencies).
- Record configuration + data snapshot for reproducibility whenever publishing results.
- Optional: for IBKR live/paper trading, install `ibapi==9.81.1`, populate
  `BrokerConfig` (see README "Broker Integration"), and use the GUI Live tab to
  start/stop sessions safely.

## Code Quality
- Keep modules small and dependency-free.
- Prefer pure functions and dataclasses; avoid shared mutable state.
- Use `decimal.Decimal` for any monetary value and keep arithmetic deterministic.
- Document non-trivial decisions in the change log (see Final Review Packet template).

## Safety Culture
- Treat `RiskEngine` as authoritative—do not bypass or disable risk gates.
- If you need broker access, design an adapter that mirrors the interfaces here
  and submit it with a full test plan.
