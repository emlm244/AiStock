# contract_utils.py

import numpy as np  # <--- ADDED IMPORT
from ibapi.contract import Contract, ContractDetails

# List of known crypto base symbols traded on PAXOS via IBKR (may change)
# Check IBKR documentation for the most up-to-date list
KNOWN_CRYPTO_BASES = ['BTC', 'ETH', 'LTC', 'BCH', 'PAXG', 'LINK', 'UNI', 'AAVE', 'MATIC']


def create_contract(symbol_input, api_instance=None):
    """
    Creates an IBKR contract object based on the input symbol string.
    Handles Stocks (e.g., 'AAPL'), Forex (e.g., 'EUR/USD'), and Crypto (e.g., 'BTC/USD').
    Optionally uses cached ContractDetails from the API instance for precision.

    Args:
        symbol_input (str): The trading symbol string.
        api_instance (IBKRApi, optional): An instance of the IBKR API client
                                           to check for cached ContractDetails.

    Returns:
        Contract: An initialized ibapi.contract.Contract object, or None if invalid.
    """
    if not isinstance(symbol_input, str) or not symbol_input:
        print(f"Error creating contract: Invalid symbol input '{symbol_input}'")  # Use print or logger early
        return None

    symbol = symbol_input.upper().strip()

    # --- Check Cache First (if API provided) ---
    if api_instance and hasattr(api_instance, 'contract_details_cache'):
        cached_details = api_instance.contract_details_cache.get(symbol)
        if cached_details and isinstance(cached_details, ContractDetails):
            # Use the contract from the details for accuracy
            # Note: ContractDetails.contract is the Contract object
            contract = cached_details.contract
            print(f'Created contract for {symbol} from cached ContractDetails.')
            return contract
        # else: # Not found in cache, proceed with heuristic
        #     print(f"ContractDetails for {symbol} not found in cache. Using heuristics.")
        #     pass

    # --- Heuristic Method ---
    if '/' in symbol:
        parts = symbol.split('/')
        if len(parts) != 2:
            print(f"Error creating contract (Heuristic): Invalid Forex/Crypto format '{symbol_input}'")
            return None

        base_currency, quote_currency = parts[0], parts[1]

        # Check if it's a known Crypto pair on PAXOS
        if base_currency in KNOWN_CRYPTO_BASES and quote_currency in ['USD', 'PAX']:  # Common quote currencies
            contract = Contract()
            contract.symbol = base_currency
            contract.secType = 'CRYPTO'
            contract.currency = quote_currency
            contract.exchange = 'PAXOS'  # Primary exchange for these on IBKR
            print(
                f'Created CRYPTO contract (Heuristic): {contract.symbol} ({contract.secType}) {contract.currency} @{contract.exchange}'
            )
            return contract
        else:
            # Assume Forex if not known Crypto
            contract = Contract()
            contract.symbol = base_currency
            contract.secType = 'CASH'
            contract.currency = quote_currency
            contract.exchange = 'IDEALPRO'  # Primary Forex ECN
            print(
                f'Created FOREX contract (Heuristic): {contract.symbol} ({contract.secType}) {contract.currency} @{contract.exchange}'
            )
            return contract
    else:
        # Assume Stock
        contract = Contract()
        contract.symbol = symbol
        contract.secType = 'STK'
        contract.currency = 'USD'  # Default to USD, might need adjustment for non-US stocks
        contract.exchange = 'SMART'  # SMART routing default
        # Optional: Specify primary exchange if needed (e.g., NYSE, NASDAQ, ARCA)
        # contract.primaryExchange = "NASDAQ" # Cannot set primaryExchange AND SMART routing
        print(
            f'Created STOCK contract (Heuristic): {contract.symbol} ({contract.secType}) {contract.currency} @{contract.exchange}'
        )
        return contract


def get_contract_details(symbol, api_instance):
    """Safely retrieves cached ContractDetails for a symbol."""
    if api_instance and hasattr(api_instance, 'contract_details_cache'):
        return api_instance.contract_details_cache.get(symbol.upper().strip())
    return None


def get_min_tick(symbol, api_instance):
    """Gets the minimum tick size from cached ContractDetails, with fallback heuristics."""
    details = get_contract_details(symbol, api_instance)
    if details and isinstance(details, ContractDetails) and details.minTick > 0:
        return details.minTick

    # Fallback heuristics
    contract = create_contract(symbol)  # Create contract using heuristic
    if contract:
        if contract.secType == 'STK':
            return 0.01
        if contract.secType == 'CASH':
            return 0.00001 if 'JPY' not in contract.symbol else 0.001  # Forex 5 decimals, JPY 3
        if contract.secType == 'CRYPTO':
            # Crypto varies wildly, use a reasonable default or refine per symbol
            if 'BTC' in contract.symbol or 'ETH' in contract.symbol:
                return 0.01
            return 0.001  # Smaller altcoins? Check broker spec
    return 0.01  # Default fallback


def get_min_trade_size(symbol, api_instance):
    """Gets the minimum trade size from cached ContractDetails, with fallback heuristics."""
    get_contract_details(symbol, api_instance)
    min_size = 1.0  # Default for stocks

    # IBKR ContractDetails doesn't always have a direct minSize.
    # mdSizeMultiplier might be relevant for some contracts (e.g., futures).
    # Order size rules often involve increments (minTick applies to price).
    # Let's stick to heuristics for quantity increments for now, unless ContractDetails provides more.

    # Heuristics based on type
    contract = create_contract(symbol, api_instance)  # Use cached details if available
    if contract:
        if contract.secType == 'STK':
            # Could check details.stockType or market rules if available
            min_size = 1.0  # Assume shares for now
        elif contract.secType == 'CASH':  # Forex
            # Usually traded in lots, but API uses total quantity. Min increment might be 1, 100, 1000...
            min_size = 1.0  # Default to 1 unit increment, check broker rules
        elif contract.secType == 'CRYPTO':
            # Precision depends heavily on the coin value
            base = contract.symbol
            if base == 'BTC':
                min_size = 0.00001  # Example BTC min size
            elif base == 'ETH':
                min_size = 0.0001  # Example ETH min size
            elif base in ['LTC', 'BCH']:
                min_size = 0.001
            else:
                min_size = 0.01  # Generic small crypto

    # Can add more specific rules based on details.marketRuleIds if available and parsed
    # print(f"Min trade size for {symbol} determined as: {min_size} (using {'details' if details else 'heuristics'})")
    return min_size


def round_price(price, min_tick):
    """Rounds a price to the nearest valid tick size."""
    if min_tick is None or min_tick <= 0:
        return price  # Cannot round
    return round(round(price / min_tick) * min_tick, 8)  # Use high precision for rounding result


def round_quantity(quantity, min_size_increment):
    """Rounds a quantity down to the nearest valid size increment (floor)."""
    if min_size_increment is None or min_size_increment <= 0:
        return quantity  # Cannot round
    factor = 1 / min_size_increment
    return np.floor(quantity * factor) / factor
