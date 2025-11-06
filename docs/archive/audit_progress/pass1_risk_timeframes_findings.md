# Pass-1 Findings — aistock Risk/Scanner/GUI/Timeframes

- `risk.RiskEngine` minimum-balance check deducts trade cost only for buys; needs explicit handling for leverage/shorting and unit tests around projected equity logic.
- Order-rate tracking stores ISO strings without pruning; consider bounded deque or cleanup to avoid unbounded state growth over long sessions.
- `scanner.MarketScanner` lacks offline tests; fallback BaseClient/BaseWrapper stubs leave IBKR path unverified—flag for integration or mock-based coverage.
- `simple_gui.SimpleGUI` hardcodes FSD workflow, auto-discovers symbols, and runs SessionFactory directly; document headless/session usage and expose risk settings outside GUI for automation.
- GUI still attempts IBKR market scanner on startup; needs guardrails when ibapi absent to prevent user-facing errors.
- `timeframes.TimeframeManager._validate_timeframe_sync` calculates drift but acceptance window fixed at 2× slowest timeframe; make configurable via Risk/Config and add regression tests.
- Multi-timeframe calculations mix Decimal and float conversions; ensure deterministic rounding for reproducibility (especially momentum/volatility conversions).
