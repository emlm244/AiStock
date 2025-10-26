# Dependency & Security Notes

## Runtime Dependencies

The safe baseline intentionally uses **only the Python 3.12 standard library**.
No external wheel installations are required. The precision-sensitive parts of
the system (pricing, P&L tracking) rely on `decimal.Decimal`.

## Optional / Future Integrations

If you reintroduce third-party packages, follow these guardrails:

- Pin versions in `requirements.txt` with exact hashes.
- Validate licences (no copyleft libraries without legal review).
- Run vulnerability scanners (`pip-audit`, `safety`) in CI.

## Secrets Handling

- No credentials are stored in the repository.
- When connecting to brokers or databases, load secrets from environment
  variables or an encrypted secrets manager.
- Never log raw secrets; redact tokens before writing to disk or telemetry.

## Supply Chain Hygiene

- Prefer vendoring deterministic assets (e.g., exchange holiday calendars) over
  fetching them at runtime.
- Record data snapshots (date/version/source) alongside backtest artefacts.

## Hardening Checklist (for future live mode)

1. Enforce read-only API keys for paper trading until audit complete.
2. Implement tamper-evident logging (signed logs or WORM storage).
3. Add watchdogs for clock skew, stale market data, and broker disconnects.
4. Instrument kill switch to bubble up via on-call alerts.
- Interactive Brokers support requires `ibapi` (pin: `ibapi==9.81.1`). Install
  only on machines where TWS/Gateway is available and vetted.
- Machine-learning tooling leverages pure Python implementations (no numpy).
  Training remains deterministic and dependency-free unless you opt into more
  advanced stacks.
