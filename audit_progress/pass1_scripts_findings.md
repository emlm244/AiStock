# Pass-1 Findings — scripts/

- Scripts assume repo installed as editable package; add `if __name__ == "__main__"` import guard adjustments or document `PYTHONPATH` expectations.
- `run_smoke_backtest.py` uses `print` for reporting; align with logging guidelines and avoid direct stdout for automation.
- `rerun_backtests.py` writes invalidation JSON without atomic writes and leaves original file untouched; consider backup/rename semantics.
- Duplicate monitor uses `json.loads` on arbitrary log lines without error handling when log not JSON; wrap in try/except to avoid crash.
- Workflow script blocks on `input()`; provide `--non-interactive` flag for CI runners.
