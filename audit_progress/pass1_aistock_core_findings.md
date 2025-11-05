# Pass-1 Findings — aistock Core Modules (Edge Cases → Professional)

- `aistock/fsd.py` remains the dominant orchestration layer despite Option D coordinator focus; documentation and exports still pitch autonomous FSD workflows. Evaluate deprecation or re-scoping for current production architecture.
- `edge_cases.EdgeCaseHandler` re-runs checks twice per decision path; consider refactor to avoid duplicate work and unify logging with safeguards.
- `portfolio.Position.realise` still mixes Decimal math with implicit float conversions when computing weighted average; audit for precision and ensure entry timestamps reset on reversals (known TODO in guidelines).
- `professional._check_end_of_day` relies on `nyse_trading_hours` but still measures minutes via naive ET conversion flagged in backlog; schedule fix/test per Known Risks section.
- `idempotency.OrderIdempotencyTracker` persists plain JSON without atomic writes; reuse persistence helper for crash safety in Pass-3.
- Acquisition/ingestion modules log warnings via `print` in `data.load_csv_file`; standardize through `configure_logger` to support structured logging.
