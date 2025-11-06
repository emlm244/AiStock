# Pass-1 Findings — tests/ (remaining suites)

- `test_coordinator_regression.py` documents missing integration for broker failure rate-limit preservation; add real coordinator test once infrastructure available.
- Many tests still rely on `time.sleep` (idempotency TTL, concurrency); consider using monkeypatch/time injection to avoid flakiness.
- `test_professional_integration.py` builds trending bars manually; potential duplication with timeframe helper—factor into fixtures.
- `test_persistence.py` manipulates `sys.modules` to import aistock; ensure package install path is resolved during CI to avoid module shadowing.
