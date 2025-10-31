# Repository Guidelines

## Project Structure & Module Organization
- `aistock/` holds the trading engine, RL agents, and broker integrations; start with `fsd.py`, `engine.py`, and `session.py` when extending control flow.
- `tests/` mirrors the package layout with `pytest` suites; fixtures and CSV samples live under `tests/fixtures/`.
- `scripts/` provides operational helpers such as `run_smoke_backtest.py` and data generation utilities.
- `configs/` contains JSON templates (e.g., `fsd_mode_example.json`) for prebuilt FSD sessions; copy and adjust rather than editing in place.
- Documentation and onboarding guides sit in `docs/`, `START_HERE.md`, and audit checklists in the repository root.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` installs runtime dependencies; add dev-only tools to `requirements-dev.txt`.
- `python -m aistock` launches FSD mode headlessly, while `python launch_gui.py` opens the Tkinter control panel for manual inspection.
- `pytest tests` runs the full suite; prefer `pytest --maxfail=1 --lf` when iterating on a failing case to shorten feedback loops.
- `ruff check .` enforces lint rules and import order; `ruff format .` applies the repository formatter before committing.

## Coding Style & Naming Conventions
Rely on Ruff’s defaults: 4-space indentation, 120-character lines, single quotes, and Python 3.9+ syntax. Follow the module naming already in place (`risk.py`, `portfolio.py`) and keep class names in CapWords (`FSDEngine`, `RiskManager`). When interacting with broker callbacks, retain upstream casing (e.g., IBKR event handlers) to match configured ignores.

## Testing Guidelines
Author tests alongside features under `tests/`, mirroring the module path (`tests/test_engine_multi_asset.py` covers `engine.py`). Use descriptive function names like `test_fsd_updates_q_values` and prefer fixtures for market data samples. Run `pytest --cov=aistock --cov-report=html` locally to refresh `htmlcov/`; keep coverage steady by extending integration tests when modifying long-running flows.

## Commit & Pull Request Guidelines
Commits follow a Conventional Commit style (`feat:`, `docs:`, `fix:`) as seen in recent history; scope changes narrowly and squash noisy checkpoints. Pull requests should summarize intent, link tracking issues, and list verification steps (e.g., `pytest tests`, `ruff check .`). Include screenshots or logs for GUI or broker-facing changes, and note any configuration updates required by operators.

## Security & Configuration Tips
Store broker credentials and API tokens outside the repo (environment variables or secrets managers) and reference them via `aistock.config`. Never commit files from `state/` or personal `configs/` copies—treat them as runtime artifacts and gitignore any new variants. Review `PRODUCTION_EDGE_CASE_AUDIT.md` before enabling live trading paths.
