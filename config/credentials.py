# config/credentials.py
# SECURITY: All credentials now loaded from environment variables.
# Never commit .env files or hardcode secrets here.

import os

def _get_env_int(key, default):
    """Get integer from environment variable with fallback."""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"Environment variable {key} must be an integer, got: {val}")

# IBKR Configuration - loaded from environment variables
IBKR = {
    'TWS_HOST': os.getenv('IBKR_TWS_HOST', '127.0.0.1'),
    'TWS_PORT': _get_env_int('IBKR_TWS_PORT', 7497),
    'CLIENT_ID': _get_env_int('IBKR_CLIENT_ID', 1001),
    'ACCOUNT_ID': os.getenv('IBKR_ACCOUNT_ID'),  # REQUIRED - no default
}

# --- Validation ---
if not IBKR['ACCOUNT_ID']:
    raise ValueError(
        "CRITICAL: IBKR_ACCOUNT_ID environment variable is required. "
        "Set it in your .env file or export it. See .env.example for reference."
    )

if IBKR['TWS_PORT'] not in [7496, 7497, 4001, 4002]:
    print(f"WARNING: IBKR_TWS_PORT ({IBKR['TWS_PORT']}) is not a standard port (7496, 7497, 4001, 4002). Verify it is correct.")