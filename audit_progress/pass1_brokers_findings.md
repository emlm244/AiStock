# Pass-1 Findings — aistock/brokers

- `IBKRBroker` still lacks Option F reconciliation API (`get_recent_orders`) outlined in docs; add mapping persistence and startup hydration per backlog.
- Auto-reconnect replays subscriptions but does not refresh idempotency state; ensure TradingCoordinator integrates with reconciling broker order IDs.
- `PaperBroker` uses `random.uniform` for partial fills with default seed 42; document deterministic behavior and consider exposing seed override via config.
- Contract registry writes plain JSON without atomic persistence; align with `_atomic_write_json` to prevent corruption.
- Broker reconciliation service assumes broker `get_positions()` returns averages; for IBKR we only populate on callbacks—add coverage to ensure sync.
