from ibapi.contract import Contract

def create_contract(symbol):
    """
    Creates an IBKR contract for:
      - A Cryptocurrency pair (secType="CRYPTO", exchange="PAXOS") if base is in crypto_bases
      - A Forex pair (secType="CASH", exchange="IDEALPRO") if '/' but not recognized as crypto
      - A Stock (secType="STK", exchange="SMART") if no '/'
    """
    crypto_bases = ['BTC', 'ETH', 'LTC', 'XRP', 'BCH', 'EOS', 'XLM', 'LINK', 'DOT', 'ADA']

    if '/' in symbol:
        base_currency, quote_currency = symbol.split('/')
        base_upper = base_currency.upper()
        quote_upper = quote_currency.upper()

        # Decide if it's Crypto vs Forex by checking base currency
        if base_upper in crypto_bases:
            # Cryptocurrency
            contract = Contract()
            contract.symbol = base_upper        # e.g. "ETH"
            contract.secType = "CRYPTO"
            contract.exchange = "PAXOS"         # IBKR-supported crypto exchange
            contract.currency = quote_upper     # e.g. "USD"
            return contract
        else:
            # Forex
            contract = Contract()
            contract.symbol = base_upper
            contract.secType = "CASH"
            contract.exchange = "IDEALPRO"
            contract.currency = quote_upper
            return contract
    else:
        # Stock
        contract = Contract()
        contract.symbol = symbol.upper()
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        return contract
