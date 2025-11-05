# Pass-1 Findings — aistock/session/

- `TradingCoordinator` still tightly couples to FSDEngine API (e.g., `evaluate_opportunity`, `register_trade_intent`, `handle_fill`); introduce protocol abstraction or align docs to reflect coordinator-first architecture.
- No startup reconciliation step to hydrate idempotency tracker from broker state (Option F backlog); current `_order_submission_times` only tracks local submissions.
- `CheckpointManager` worker lacks idempotent shutdown flag; legacy audit flagged double-shutdown risk persists.
- Analytics reporter writes CSVs but does not guard against I/O failures beyond logging; consider atomic writes and directory creation verification.
- `BarProcessor` uses non-structured logging; unify with `configure_logger` to maintain JSON logs.
- Reconciliation actions rely on broker `get_positions()` but do not include tolerance configuration; add config surface + tests.
