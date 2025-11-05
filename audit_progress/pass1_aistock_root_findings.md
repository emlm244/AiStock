# Pass-1 Findings — aistock/ Root Modules

- Package metadata (`aistock/__init__.py`) still markets legacy FSD-centric enhancements; should be updated to reflect coordinator/risk-led architecture.
- `aistock/__main__.py` always launches GUI; headless/session CLI support missing despite docs referencing paper/headless modes.
- Acquisition pipeline (`aistock/acquisition.py`) assumes local filesystem CSV sources; need to verify integration points with current production ingestion.
- Calendar utilities (`aistock/calendar.py`) ship with static holiday list through 2030; plan recurring maintenance task or external data hook.
- Data loader (`aistock/data.py`) logs warnings via `print`; migrate to structured logger for consistency.
- Corporate actions module flagged as unintegrated; decision needed on removal vs roadmap alignment.
