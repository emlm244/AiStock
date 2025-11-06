# Repository Guidelines

## Project Structure & Module Organization
The `aistock/` package holds trading logic: `fsd.py` (RL engine), `engine.py` (execution loop), `brokers/` (paper + IBKR adapters), and GUI helpers in `simple_gui.py`. Tests align under `tests/`. Reference docs live in `docs/`; runtime presets in `configs/`. Generated artifacts (`state/`, `models/`, `logs/`, `backtest_results/`, `data/`) should stay local. Utility scripts are in `scripts/`.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` – install runtime dependencies.
- `pip install -r requirements-dev.txt` – add linting, typing, and test tooling.
- `ruff check aistock tests` – run lint rules from `ruff.toml`.
- `ruff format aistock tests` – apply formatter when updating style.
- `pytest tests` – execute automation; append `-k pattern` for targeted runs.
- `python -m aistock` – launch the FSD engine headless.
- `python launch_gui.py` – open the Tkinter dashboard for manual checks.

## Coding Style & Naming Conventions
Follow four-space indentation, snake_case modules, and PascalCase public classes. Prefer explicit imports and targeted functions to keep control flow readable. Type hints are expected; align with `pyrightconfig.json` and annotate broker interfaces, dataclasses, and async calls. Let `ruff` handle lint-autofix before review, and keep docstrings brief for any public entry point in `aistock/`.

## Testing Guidelines
Place new tests beside related modules (`tests/test_engine.py` covers `aistock/engine.py`). Name cases `test_<behavior>` and use parametrization for scenario coverage. Share fixtures instead of writing to `data/` or `state/`. Every trading rule or regression fix must include a corresponding pytest, and `pytest tests` should pass locally before requesting review.

## Commit & Pull Request Guidelines
Use the Conventional Commit format already in history (`type: summary`), with focused commits and descriptive bodies. PRs need a concise problem statement, solution summary, and any operational considerations (config changes, manual steps). Attach relevant metrics or screenshots for GUI updates, list lint/test commands executed, and note follow-ups when work is staged.

## Configuration & Data Hygiene
Keep credentials in environment variables or local `.env` files ignored by git. Treat `configs/` as versioned templates—copy and override locally for experiments. Clean generated outputs in `data/`, `logs/`, `models/`, and `backtest_results/` before shipping a PR unless the artifact is a committed fixture.
