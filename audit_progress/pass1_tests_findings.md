# Pass-1 Findings — tests/ (initial batch)

- Regression coverage leans heavily on FSD/coordinator; ensure forthcoming Pass-2 audits check for non-FSD decision engines or add protocol-based fixtures.
- Concurrency stress suite relies on wall-clock sleeps; consider tightening with threading Events to reduce flakiness in CI.
- Duplicate monitoring of PaperBroker internals via `_open_orders` should migrate to public APIs (tests reference private attributes).
- Need to confirm Option F scenarios (broker reconciliation) have targeted regression tests once feature implemented—currently absent.
- Remaining queued tests must be reviewed to complete Pass-1; expect further findings around timezone, idempotency, and risk coverage.
