## CLAUDE Playbook – AIStock Trading System  
**Last Updated**: 2025-11-01 (Post-Critical Bug Fixes)  
**Status**: ✅ Production-ready (`main` @ 89f191f)

This document is the operating manual for Claude Code (and similar assistants) when working in the AIStock repository. It mirrors `AGENTS.md` but emphasises assistant-specific expectations, safety constraints, and verification steps.

---

### 🔴 Critical Fix Snapshot (all merged into `main`)

| # | Issue | Location | Status | Regression Test |
|---|-------|----------|--------|-----------------|
| 1 | Risk timestamp missing (daily reset disabled) | `aistock/session/coordinator.py` | ✅ | `tests/test_coordinator_regression.py` |
| 2 | Idempotency marked before broker submit | `aistock/session/coordinator.py` | ✅ | `tests/test_coordinator_regression.py` |
| 3 | Checkpoint shutdown deadlock (missing `task_done`) | `aistock/session/checkpointer.py` | ✅ | `tests/test_coordinator_regression.py` |
| 4 | Risk counters increment on failed submit | `aistock/session/coordinator.py` | ✅ | `tests/test_coordinator_regression.py` |
| 5 | Profit triggered daily-loss halt | `aistock/risk.py` | ✅ | `tests/test_risk_engine.py::test_profit_does_not_trigger_daily_loss_halt` |
| 6 | Naive vs tz-aware datetime crash | `aistock/edge_cases.py` | ✅ | Covered by existing edge-case tests |

**Must-run before handoff** (once dependencies installed):
```bash
pytest tests/test_coordinator_regression.py tests/test_risk_engine.py -q
```

---

### 🧱 Architecture Overview

```
SessionFactory (dependency injection)
└── TradingCoordinator
    ├── FSDEngine (Q-learning, numpy)
    ├── Portfolio (thread-safe Decimal accounting)
    ├── RiskEngine (limits, rate limiting)
    ├── EdgeCaseHandler (data sanity)
    ├── ProfessionalSafeguards (overtrading/news/end-of-day)
    ├── Broker (PaperBroker / IBKRBroker)
    ├── BarProcessor (ingestion & history)
    ├── PositionReconciler (broker truth sync)
    └── CheckpointManager + AnalyticsReporter
```

Key modules (no more orphaned directories):
- `aistock/factories/`: DI entry points  
- `aistock/session/`: Coordinator + supporting infrastructure  
- `aistock/risk.py`: Enforces daily loss, drawdown, order-rate limits  
- `aistock/edge_cases.py`: Timezone-safe data hygiene  
- `aistock/professional.py`: Human safeguards (now timezone-aware)  
- `aistock/persistence.py`: Atomic checkpointing  
- `aistock/brokers/`: `PaperBroker` (partial-fill sim) & `IBKRBroker` (auto reconnect)  
- `tests/`: Mirrored suites + regression tests for the six critical fixes

---

### 🚀 Development Workflow (Claude-specific)

1. **Branching**  
   - Work from `main`; create `feature/<name>` or `fix/<name>` branches.  
   - Keep PRs scoped to one bug/feature.

2. **Environment Setup**  
   ```bash
   python -m venv .venv
   source .venv/bin/activate              # Windows: .venv\Scripts\activate
   pip install -r requirements.txt        # pandas, numpy, ibapi, etc.
   pip install -r requirements-dev.txt    # pytest, ruff, pyright, etc.
   ```

3. **Coding Guardrails**  
   - **Timezone**: generate UTC datetimes (`datetime.now(timezone.utc)`), never coerce with `replace(tzinfo=...)`.  
   - **Money math**: use `decimal.Decimal`; avoid floats.  
   - **Thread safety**: respect existing locks (`Portfolio`, `RiskEngine`, `CheckpointManager`).  
   - **Order flow**: preserve ordering—risk checks → broker submit → record submission → mark idempotency.  
   - **Persistence**: use `aistock.persistence` helpers (atomic writes + backups).

4. **Testing & Quality**  
   - Minimum regression suite: `pytest tests/test_coordinator_regression.py tests/test_risk_engine.py -q`  
   - Full suite (if time): `pytest -q` (requires pandas/numpy).  
   - Lint / format / type-check:  
     ```bash
     ruff check aistock/ tests/
     ruff format aistock/ tests/
     pyright aistock/
     ```

5. **Docs**  
   - Update `AGENTS.md`, this file, or other docs when workflows change.  
   - Maintain changelog in PR summary (list fixes + tests run).

---

### 🧪 Testing Reference

| Command | Purpose |
|---------|---------|
| `pytest -q` | Full test suite (skip IBKR live tests automatically) |
| `pytest tests/test_coordinator_regression.py -q` | Checkpoint + broker regression coverage |
| `pytest tests/test_risk_engine.py -q` | Risk engine guardrails |
| `ruff check aistock/ tests/` | Static analysis (style + lint) |
| `ruff format aistock/ tests/` | Canonical formatting |
| `pyright aistock/` | Optional static typing |

*Optional*: `pytest --cov=aistock --cov-report=html` for coverage.

---

### ⚠️ Safety & Consistency Notes

- **Timezone discipline**: Always produce real timezone-aware timestamps. Several safeguards (`ProfessionalSafeguards`, `EdgeCaseHandler`) assume UTC inputs; injecting naive datetimes will reintroduce crashes or stale-data blind spots.
- **Checkpoint lifecycle**: `CheckpointManager.shutdown()` now blocks until the queue drains. Do not short-circuit the sequence; reuse the manager or extend carefully.
- **Rate limiting**: Only successful `broker.submit()` calls should touch `RiskEngine.record_order_submission()`. If you add alternate submission paths, mirror this ordering.
- **Persistence**: Use `_atomic_write_json` or higher-level helpers; never write JSON through naive file I/O.
- **FSD state**: `FSDEngine` persists Q-table + stats; use the provided methods for load/save (already atomic).
- **Tests requiring live IBKR**: remain skipped—do not unskip in CI without instructions from maintainers.

---

### 📋 Backlog / Known TODOs

1. **Checkpoint restore flow** (`SessionFactory.create_with_checkpoint_restore`): still a stub. Requires full design before reintroducing.
2. **GUI refactor** (`simple_gui.py` ≈ 70k lines): candidate for decomposition; currently functional but unwieldy.
3. **Chaos/failure injection tests**: Broker timeouts, persistence write failures, etc., remain manual exercises—consider scripting as future work.
4. **Live IBKR validation**: Run periodically by humans; document in PR whenever live testing occurs.

---

### 🛠️ Quick Command Reference

```bash
# Launch GUI (Full Self-Driving mode)
python -m aistock

# Paper trading headless
python -m aistock --broker paper --symbols AAPL --capital 10000

# Smoke backtest
python scripts/run_smoke_backtest.py

# Regeneration of regression tests only
pytest tests/test_coordinator_regression.py tests/test_risk_engine.py -q
```

---

Keep this playbook aligned with `AGENTS.md`. If a change affects architecture, safety, or workflow, update both files within the same PR. Continuous documentation accuracy is part of the definition of done. 🟢
