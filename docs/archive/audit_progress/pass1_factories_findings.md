# Pass-1 Findings — aistock/factories

- `SessionFactory` still mandates FSDConfig; document headless non-FSD workflows or provide alternative decision-engine injection.
- Checkpoint restore TODO untouched; schedule implementation or remove placeholder to avoid false sense of recovery.
- `TradingComponentsFactory.create_broker` instantiates IBKR without handling missing ibapi; rely on earlier guard but add try/except for clearer error.
- Idempotency tracker creation reuses JSON file without atomic writes; align with persistence helpers.
