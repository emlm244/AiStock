# Pass-1 Findings — aistock/interfaces

- `RiskEngineProtocol.check_pre_trade` signature omits `timestamp`, `quantity_delta` naming, and `last_prices` optionality used by implementation; update protocol to match latest engine API.
- Decision engine protocol locks FSD semantics (register_trade_intent, handle_fill); consider abstracting for non-FSD engines in roadmap.
