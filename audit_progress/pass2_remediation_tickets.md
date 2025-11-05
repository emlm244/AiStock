# Pass-2 Remediation Tickets

1. **README + Data Docs Alignment**  
   - Rewrite `README.md` and `data/README.md` to reflect coordinator-first architecture, clarify headless/paper workflows, and tone down legacy FSD marketing.  
   - Mirror updates in `CLAUDE.md` / `AGENTS.md` to keep guidance consistent.

2. **Ruff Config & CI Python Version Sync**  
   - Prune stale per-file ignores in `ruff.toml` (references to removed modules).  
   - Align CI lint job with supported Python version (pyright uses 3.11 but lint job pins 3.9); document official runtime matrix.

3. **Logging Standardization & Print Cleanup**  
   - Replace `print` statements in `aistock/data.py`, scripts, and tests where structured logging should be used.  
   - Ensure `configure_logger` is leveraged across acquisition/ingestion components for consistency.

4. **Idempotency & Persistence Hardening**  
   - Update `OrderIdempotencyTracker` and contract registry writes to use atomic persistence (reuse `_atomic_write_json`).  
   - Add regression tests covering crash-safe writes.

5. **Option F Broker Reconciliation Implementation**  
   - Implement broker `get_recent_orders()` + `orderRef` mapping (IBKR + Paper).  
   - Add startup reconciliation in TradingCoordinator and cover with regression tests.  
   - Update docs (`OPTION_F_BROKER_RECONCILIATION.md`, `AGENTS.md`).

6. **Risk/Timeframe Config Surfacing**  
   - Expose configurable parameters for minimum balance protection and timeframe drift tolerance (currently hard-coded).  
   - Extend regression coverage to include new knobs.

7. **Script UX Improvements**  
   - Provide non-interactive flags for `run_full_workflow.py` (remove blocking `input()` in CI contexts).  
   - Document `PYTHONPATH` expectations or package install steps for scripts.  
   - Add argument-based logging configuration (stdout vs JSON).

8. **Protocol/API Alignment**  
   - Update `RiskEngineProtocol` signature to match implementation (timestamp parameter, quantity naming).  
   - Audit other protocols (decision engine) for FSD-specific methods and plan abstraction for future engines.

9. **Tests: Reduce Sleep-Based Timing**  
   - Refactor idempotency TTL and concurrency tests to use time mocking/events instead of `time.sleep`, reducing flakiness.  
   - Add integration coverage for broker failure rate-limit behavior referenced in regression docs.
