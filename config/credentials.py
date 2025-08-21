# config/credentials.py
# It's crucial to keep this file secure and excluded from version control systems like Git.
# Add this file to your .gitignore!

IBKR = {
    'TWS_HOST': '127.0.0.1',        # Host running TWS or Gateway
    'TWS_PORT': 7497,               # Default Paper Trading Port. Use 7496 for Live.
    'CLIENT_ID': 1001,              # Unique client ID for this connection
    'ACCOUNT_ID': 'DUE072840', # IMPORTANT: Replace with your actual IBKR Account ID (e.g., DU1234567)
}

# Add other credentials here if needed (e.g., for crypto exchanges, news APIs)
# EXAMPLE_CRYPTO_EXCHANGE = {
#     'API_KEY': 'YOUR_CRYPTO_API_KEY',
#     'API_SECRET': 'YOUR_CRYPTO_API_SECRET',
# }

# --- Input Validation ---
if IBKR['ACCOUNT_ID'] == 'YOUR_ACCOUNT_ID':
    raise ValueError("CRITICAL: Please replace 'YOUR_ACCOUNT_ID' in config/credentials.py with your actual IBKR account ID.")

if IBKR['TWS_PORT'] not in [7496, 7497, 4001, 4002]: # Common ports: Live, Paper, Gateway Live, Gateway Paper
    print(f"WARNING: TWS_PORT ({IBKR['TWS_PORT']}) in config/credentials.py is not a standard IBKR port (7496, 7497, 4001, 4002). Ensure it's correct.")