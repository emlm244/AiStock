# Pass-1 Findings — Repository Root (Initial Chunk)

- README.md marketing/legacy content diverges from current architecture and safety posture described in AGENTS.md; needs rewrite or relocation to avoid misleading operators.
- ruff.toml references directories/modules that no longer exist (e.g., api/ibkr_api.py, utils/*); lint config should be pruned to match active tree.
- launch_gui.py provides minimal error handling; consider surfacing structured logging hooks consistent with `configure_logger` usage elsewhere.
- requirements*.txt lock Python 3.9+ while pyrightconfig.json targets Python 3.11; document supported versions and reconcile tooling defaults.
- IBKR onboarding docs (.env.example, IBKR_REQUIREMENTS_CHECKLIST.md) hard-code GUI-based configuration paths; need cross-check with headless/session factory workflows during later passes.
