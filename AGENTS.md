**Last Updated**: 2025-11-02 (Timezone Bug #7 + Strict Enforcement)
**Production Status**: ✅ Ready – `main` @ c96cdf0 (7 critical bugs resolved, timezone-safe)

---

# Repository Guidelines

This document is for automation agents (Claude, etc.) working in the AIStock repo. Treat it as the single source of truth for current architecture, guardrails, and expected workflows.

---

## 1. Branch & Release Status

- **Default branch**: `main`
- **Feature branches**: none outstanding; all modularization fixes merged
- **Critical fixes merged** (2025‑11‑01):
  1. Risk timestamp wiring (`coordinator.py`)
  2. Idempotency ordering (`coordinator.py`)
  3. Checkpoint shutdown task accounting (`checkpointer.py`)
  4. Risk rate-limit accounting (`coordinator.py`)
  5. Daily loss logic (profits no longer halt) (`risk.py`)
  6. Timezone-aware stale-data handling (`edge_cases.py`)
- **Regression tests added**: `tests/test_coordinator_regression.py`, new cases in `tests/test_risk_engine.py`

All future work should branch from `main`.

---

## 2. Project Structure (current)

```
aistock/
  acquisition.py         # Data acquisition pipeline
  analytics.py           # Reporting helpers
  audit.py               # Audit trail utilities
  brokers/               # Paper & IBKR integrations
  config.py              # Dataclasses (RiskLimits, etc.)
  data.py                # Bar loading (pandas)
  edge_cases.py          # Protective checks (timezone-safe)
  factories/             # DI factories (SessionFactory, etc.)
  fsd.py                 # Q-learning engine (uses numpy)
  interfaces/            # Protocol definitions
  portfolio.py           # Thread-safe portfolio
  professional.py        # Human safeguards (overtrading, etc.)
  risk.py                # Risk engine + rate limiting
  session/               # Coordinator, bar processor, reconciliation, analytics, checkpointing
  simple_gui.py          # Tkinter GUI entry point
  ...
tests/
  test_coordinator_regression.py
  test_risk_engine.py
  ... mirrored unit tests
docs/
  CLAUDE.md, FSD_COMPLETE_GUIDE.md, etc.
scripts/
  run_smoke_backtest.py
```

👉 _Removed directories_ (`config_consolidated/`, `fsd_components/`, `services/`, `state_management/`) no longer exist—ignore any stale references.

---

## 3. Development Quick Start

### Environment
```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt     # runtime deps (pandas, numpy, ibapi, etc.)
pip install -r requirements-dev.txt # pytest, ruff, pyright, etc.
```

### Running the App
```bash
# GUI (Full Self-Driving mode)
python -m aistock

# Headless paper trading
python -m aistock --broker paper --symbols AAPL --capital 10000

# Smoke backtest
python scripts/run_smoke_backtest.py
```

### Tests & Quality
```bash
# Full suite (requires pandas/numpy)
pytest -q

# Critical regressions
pytest tests/test_risk_engine.py tests/test_coordinator_regression.py -q

# Lint / format / type-check
ruff check aistock/ tests/
ruff format aistock/ tests/
pyright aistock/
```

> _NOTE_: Several fast-unit tests depend on pandas/numpy; install runtime deps before executing the suite.

---

## 4. Coding Standards

- **Style**: Ruff defaults (4 spaces, ≤120 chars, single quotes)
- **Types**: Use type hints; rely on `interfaces/` protocols for contracts
- **Currency math**: `decimal.Decimal` only
- **Thread safety**: Acquire locks around shared state (portfolio, risk, checkpointing)
- **Datetime**: Always timezone-aware (`datetime.now(timezone.utc)`); never `replace(tzinfo=...)` to coerce local time
- **Idempotency**: Use `OrderIdempotencyTracker` _after_ successful broker submits
- **Persistence**: `aistock.persistence` handles atomic writes; never write JSON directly

---

## 5. Testing Guidance

- Mirror module layout (`tests/test_<module>.py`)
- Regression tests for recent fixes:
  - `tests/test_coordinator_regression.py`
  - `tests/test_risk_engine.py::test_profit_does_not_trigger_daily_loss_halt`
- Integrations:
  - `tests/test_broker.py`, `tests/test_portfolio_threadsafe.py`, `tests/test_coordinator_regression.py`
- Long-running / IBKR live tests are skipped by default (`pytest -k "not live"`).

When adding new safeguards or risk controls, accompany them with regression tests under `tests/test_coordinator_regression.py` or module-specific suites.

---

## 6. Operational Checklist (agents)

1. **Before coding**
   - Confirm you’re on `main`
   - Create feature branch (`feature/<summary>`, `fix/<bug>`…)
   - Skim CLAUDE.md for assistant-specific nuances
2. **While coding**
   - Keep bug fixes isolated and well-commented when logic is non-obvious
   - Maintain timezone safety (use UTC)
   - Update docs/tests when behavior changes
3. **Before PR**
   - Run lint + tests (at minimum: regression tests above)
   - Update CHANGELOG if the process requires (none yet)
   - Summarize verification steps in PR body

---

## 7. Known Risks & TODOs

- **Checkpoint restore** (`SessionFactory.create_with_checkpoint_restore`) still a TODO (Phase‑7). Don’t re-enable without full restore flow.
- **IBKR live testing**: Run manually; CI skips anything requiring live connectivity.
- **Time-sensitive logic**: Ensure any new use of `datetime.now()` is timezone-aware; prefer injecting current time for easier testing.

---

## 8. Reference Docs

- `CLAUDE.md` – Assistant playbook (matches this doc)
- `docs/FSD_COMPLETE_GUIDE.md`
- `docs/PRODUCTION_READINESS_AUDIT.md`
- `docs/CODE_REVIEW_FINDINGS.md`

Keep this guide updated whenever architecture or safety guarantees change. #+#EOF
