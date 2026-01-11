# Repository Guidelines

## Project Structure & Module Organization
- `aistock/` is the core runtime package, with key subpackages like `brokers/`, `session/`, `factories/`, `backtest/`, `engines/`, `ml/`, `providers/`, and `risk/` (legacy code in `aistock/_legacy/`).
- `tests/` holds pytest suites with domain folders (`tests/backtest/`, `tests/engines/`, `tests/ml/`, `tests/providers/`, `tests/risk/`) plus top-level regression tests.
- `scripts/` contains operational and backtest automation; follow the conventions in `scripts/README.md`.
- `configs/`, `data/`, `state/`, `logs/`, and `backtest_results/` store configuration examples, datasets, checkpoints, logs, and result artifacts.
- `docs/` captures architecture and audits; start with `docs/audit/2025-11-08/ARCHITECTURE_MAP.md`.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` installs runtime dependencies (Python 3.10+).
- `pip install -r requirements-dev.txt` adds pytest, ruff, basedpyright, and related tooling.
- `python -m aistock` or `python launch_gui.py` starts the FSD GUI/runtime.
- `python test_ibkr_connection.py` validates local IBKR connectivity.
- `pytest tests/` runs the test suite; target individual files during development.
- `ruff check .` and `ruff format .` enforce linting/formatting.
- `basedpyright` runs strict type checks (see `pyrightconfig.json`).

## Coding Style & Naming Conventions
- 4-space indentation, 120-char lines, single quotes (Ruff formatter).
- `snake_case` for modules/functions/variables, `CapWords` for classes, `UPPER_SNAKE` for constants.
- Preserve broker API callback naming (IBKR uses mixed-case callbacks).

## Testing Guidelines
- Pytest with `test_*.py` naming; keep new tests alongside the feature’s domain folder.
- Some tests require environment variables (e.g., `IBKR_ACCOUNT_ID`, `IBKR_CLIENT_ID`) and provider dependencies; configure via `.env` or `.env.example`.
- CI runs ruff, basedpyright (non-blocking), and pytest across Python 3.10–3.12 with coverage on 3.10.

## Commit & Pull Request Guidelines
- Commit messages use `type: summary` (common types: `feat`, `fix`, `docs`, `style`, `chore`; scope is optional).
- Keep summaries short, imperative, and specific.
- PRs should include a clear description, tests run, and screenshots for GUI changes; update `scripts/README.md` when adding scripts.

## Configuration & Data
- Copy `.env.example` to `.env` and set IBKR credentials, ports, and GUI defaults; never commit secrets.
- `configs/fsd_mode_example.json` shows a baseline FSD configuration.
- Use `data/README.md` and `scripts/generate_synthetic_dataset.py` to build historical CSV data for backtests.
