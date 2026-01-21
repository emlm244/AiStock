# Pass-1 Review Status

- Timestamp: 2025-11-03T09:20:45Z
- Legend: Read = full review, Skimmed = cursory scan, Queued = pending

## Repository Root

- README.md — Read: High-level marketing-style overview; needs alignment with current architecture/safety doc.
- AGENTS.md — Read: Assistant playbook covering critical fixes, workflows, verification steps, and primary repository guidelines.
- CODE_REVIEW_FIXES.md — Read: Historical record of test suite corrections and validation coverage.
- CONCURRENCY_EDGE_CASES_AUDIT.md — Read: Audit enumerating concurrency issues, many now resolved; serves as historical reference.
- EDGE_CASE_FIXES_SUMMARY.md — Read: Summary of edge-case fixes, test suites, and recommendations from Jan 2025 review.
- FINAL_AUDIT_REPORT.md — Read: Repo-wide audit snapshot (Nov 2025) with cleanup status and readiness verdict.
- IBKR_REQUIREMENTS_CHECKLIST.md — Read: Checklist for configuring IBKR integration, includes code references and operational steps.
- LICENSE — Read: MIT License, 2025 Arctic Hat.
- .env.example — Read: Environment template for IBKR credentials and runtime settings with security notes.
- launch_gui.py — Read: CLI entry wrapper around `SimpleGUI` with minimal error handling.
- pyrightconfig.json — Read: Strict type-check config targeting Python 3.11 with per-env overrides.
- ruff.toml — Read: Lint/format config; includes outdated per-file ignores referencing missing modules.
- requirements.txt — Read: Minimal runtime deps (pandas, numpy, ibapi).
- requirements-dev.txt — Read: Extensive dev/test toolchain referencing pytest, hypothesis, mypy, bandit, sphinx, etc.
- test_ibkr_connection.py — Read: Manual IBKR connectivity smoke harness with logging and real-time data subscription test.
- .gitignore — Read: Standard Python/data ignore patterns.
- .github/ — Read: Workflows reviewed (CI).
- .claude/ — Skimmed: Local CLI settings (unchanged).

## docs/

- docs/FSD_COMPLETE_GUIDE.md — Read: Legacy deep-dive on Q-learning FSD mode; diverges from current architecture and safeguards.
- docs/BACKTEST_RERUN_GUIDE.md — Read: Post-P&L-fix rerun workflow with tooling references (scripts/rerun_backtests.py, compare_backtest_results.py).
- docs/OPTION_F_BROKER_RECONCILIATION.md — Read: TODO blueprint for broker reconciliation (Option F) with implementation phases.

## aistock/ (root modules)

- aistock/__init__.py — Read: Package re-export list still advertises legacy FSD enhancements.
- aistock/__main__.py — Read: CLI entrypoint wiring GUI start with signal-based graceful shutdown.
- aistock/acquisition.py — Read: File-system acquisition pipeline with validation and metadata logging (includes P0 price anomaly checks).
- aistock/analytics.py — Read: Reporting helpers for trade stats/drawdown; pure functions with Decimal usage.
- aistock/audit.py — Read: Audit logger, state store, alert dispatcher utilities.
- aistock/calendar.py — Read: Hardcoded NYSE calendar + trading-hours helpers (DST handling via custom logic).
- aistock/config.py — Read: Dataclasses for data/risk/broker configs; validates risk/broker settings.
- aistock/corporate_actions.py — Read: Standalone corporate action tracker; noted as not integrated.
- aistock/data.py — Read: Bar dataclass, CSV loaders, DataFeed iterator; relies on pandas and includes forward-fill option.
- aistock/edge_cases.py — Read: Edge-case detection pipeline with timezone-safe stale-data checks.
- aistock/engine.py — Read: Trading engine tracking cost basis and equity with critical regression fixes.
- aistock/execution.py — Read: Order/Execution primitives with partial fill tracking.
- aistock/fsd.py — Read: RL trading agent and FSDEngine (legacy FSD focus) with adaptive features.
- aistock/idempotency.py — Read: Time-boxed order idempotency tracker with TTL persistence.
- aistock/ingestion.py — Read: Deterministic CSV ingestion and manifest maintenance.
- aistock/log_config.py — Read: Structured logging helper providing JSON/console formatters.
- aistock/patterns.py — Read: Candlestick pattern detector using Decimal operations and LRU cache.
- aistock/performance.py — Read: Performance metrics (returns, Sharpe/Sortino, drawdown).
- aistock/portfolio.py — Read: Thread-safe portfolio with reversal handling and P&L calculations.
- aistock/professional.py — Read: Safeguards for overtrading, news events, EOD risk.
- aistock/risk/engine.py — Read: Thread-safe risk engine enforcing drawdown, rate limits, minimum balance.
- aistock/scanner.py — Read: IBKR market scanner wrapper with optional ibapi dependency.
- aistock/simple_gui.py — Read: Tkinter FSD UI tied to SessionFactory; heavy FSD messaging.
- aistock/timeframes.py — Read: Multi-timeframe manager with lock-guarded aggregation and confluence analysis.
- aistock/universe.py — Read: Legacy placeholder universe selector returning manual results.

### aistock/session/

- aistock/session/__init__.py — Read: Aggregates core session components.
- aistock/session/analytics_reporter.py — Read: Shutdown analytics exporter (CSV outputs, capital sizing log).
- aistock/session/bar_processor.py — Read: Thread-safe bar ingest + multi-timeframe forwarding.
- aistock/session/checkpointer.py — Read: Async checkpoint queue worker with shutdown sentinel.
- aistock/session/coordinator.py — Read: Orchestrates decision engine, risk, idempotency, reconciliation.
- aistock/session/reconciliation.py — Read: Periodic broker vs portfolio reconciliation with halt on mismatches.

### aistock/brokers/

- aistock/brokers/__init__.py — Read: Exposes BaseBroker, PaperBroker, IBKRBroker.
- aistock/brokers/base.py — Read: Abstract broker base with fill handler + position interface.
- aistock/brokers/management.py — Read: Contract registry and reconciliation utilities with audit logging.
- aistock/brokers/paper.py — Read: Deterministic paper broker supporting partial fills and reconciliation snapshot.
- aistock/brokers/ibkr.py — Read: Full IBKR adapter with reconnect, heartbeat, and subscription state.

### aistock/factories/

- aistock/factories/__init__.py — Read: Re-exports session and trading component factories.
- aistock/factories/session_factory.py — Read: Builds full TradingCoordinator; TODO checkpoint restore noted.
- aistock/factories/trading_components_factory.py — Read: Creates portfolio/risk/broker/etc with FSD defaults.

### aistock/interfaces/

- aistock/interfaces/__init__.py — Read: Re-exports protocol interfaces.
- aistock/interfaces/broker.py — Read: Broker protocol defining submit/cancel/positions.
- aistock/interfaces/decision.py — Read: Decision engine protocol spanning evaluate/register/save.
- aistock/interfaces/market_data.py — Read: Market data provider protocol for bars/state.
- aistock/interfaces/persistence.py — Read: State manager protocol for checkpoint persistence.
- aistock/interfaces/portfolio.py — Read: Portfolio contract exposing cash/positions/fills.
- aistock/interfaces/risk/engine.py — Read: Risk engine protocol (pre-trade, register, halt).

## scripts/

- scripts/README.md — Read: Overview of automation scripts post-P&L fix.
- scripts/run_smoke_backtest.py — Read: CLI smoke test wiring SessionFactory with paper broker.
- scripts/run_sample_backtest.py — Read: Deterministic sample demonstrating corrected P&L.
- scripts/run_full_workflow.py — Read: Orchestrates end-to-end rerun workflow via subprocess.
- scripts/compare_backtest_results.py — Read: Compares legacy vs corrected backtest metrics.
- scripts/rerun_backtests.py — Read: Marks invalid results and builds rerun plan.
- scripts/monitor_duplicates.py — Read: Log analyzer for Option D duplicate violations.
- scripts/generate_synthetic_dataset.py — Read: Synthetic OHLCV generator for testing.

## tests/

- tests/__init__.py — Read: Empty module marker.
- tests/test_acquisition.py — Read: Acquisition pipeline integration + anomaly detection coverage.
- tests/test_analytics.py — Read: Analytics unit tests (symbol performance, drawdown, capital sizing).
- tests/test_audit.py — Read: Audit logger/state store/compliance reporter tests.
- tests/test_broker.py — Read: Paper broker fill + position snapshot tests.
- tests/test_broker_failure_modes.py — Read: Focused broker edge cases (open orders, overfill guard).
- tests/test_calendar.py — Read: Calendar holiday/trading hours coverage.
- tests/test_concurrency_stress.py — Read: Concurrency regression suite for timeframes, portfolio, RL agent.
- tests/test_coordinator_regression.py — Read: Coordinator regression coverage (checkpoint, idempotency, timezone).
- tests/test_corporate_actions.py — Read: Corporate action adjustment tests.
- tests/test_critical_fixes_regression.py — Read: Engine/coordinator/timeframe regression coverage.
- tests/test_data_feed.py — Read: DataFeed forward-fill behavior tests.
- tests/test_data_loader.py — Read: CSV directory loader validation.
- tests/test_edge_cases.py — Read: Edge case handler coverage.
- tests/test_engine_edge_cases.py — Read: Extensive TradingEngine edge-case suite.
- tests/test_engine_pnl.py — Read: Realized P&L regression tests.
- tests/test_idempotency.py — Read: Tracker generation and persistence behavior.
- tests/test_ingestion.py — Read: Ingestion manifest and append logic tests.
- tests/test_persistence.py — Read: Persistence checkpoint save/load tests.
- tests/test_portfolio.py — Read: Portfolio fill and reversal tests.
- tests/test_portfolio_threadsafe.py — Read: Thread-safe portfolio stress tests.
- tests/test_professional_integration.py — Read: Multi-timeframe/pattern/safeguard integration tests.
- tests/test_risk_engine.py — Read: RiskEngine limits, rate limiting, min balance coverage.
- tests/test_scanner.py — Read: Market scanner unit tests with mocks.
- tests/test_synthetic_dataset.py — Read: Synthetic dataset generator tests.
- tests/test_timezone_edge_cases.py — Read: Comprehensive timezone + TTL edge cases.

## Ancillary Roots

- data/README.md — Read: Data directory structure and FSD discovery notes (legacy FSD marketing).
- configs/fsd_mode_example.json — Read: FSD mode sample config with aggressive autonomy defaults.
- .gitignore — Read: Standard Python ignores plus data/state exclusions.
- .github/workflows/ci.yml — Read: CI pipeline running ruff, basedpyright, pytest across Python 3.9–3.11.
