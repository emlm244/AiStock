# utils/data_utils.py
import os

try:
    from config.settings import Settings

    # Import contract utils for accurate details
    from contract_utils import get_min_tick, get_min_trade_size, round_quantity
    from utils.logger import setup_logger
except ImportError as e:
    print(f'Error importing modules in data_utils.py: {e}')
    raise

logger = setup_logger('DataUtils', 'logs/app.log', level=Settings.LOG_LEVEL)  # Use settings level


def calculate_position_size(
    entry_price,
    stop_loss_price,
    risk_amount,
    available_funds,
    symbol,
    min_trade_size,  # Pass the already determined min size increment
    min_tick,  # Pass the already determined min tick
    api=None,  # Pass API instance if needed for more details (optional here now)
    commission_per_unit=0.0,  # Optional estimated commission
    slippage_per_unit=0.0,  # Optional estimated slippage
):
    """
    Calculates position size based on risk amount, stop loss, available funds, and contract details.

    Args:
        entry_price (float): The estimated entry price.
        stop_loss_price (float): The calculated stop loss price.
        risk_amount (float): The maximum amount of equity to risk on this trade.
        available_funds (float): The funds available for trading (e.g., 'AvailableFunds' from broker).
        symbol (str): The trading symbol (e.g., 'AAPL', 'ETH/USD').
        min_trade_size (float): The minimum quantity increment allowed for the asset.
        min_tick (float): The minimum price increment for the asset.
        api (IBKRApi, optional): API instance (if needed for further details).
        commission_per_unit (float): Estimated commission per unit/share.
        slippage_per_unit (float): Estimated slippage per unit/share (in price units).

    Returns:
        float: The calculated position size (quantity), rounded down to the nearest valid increment, or 0.0 if invalid/unaffordable.
    """
    if entry_price is None or stop_loss_price is None or risk_amount is None or entry_price <= 0:
        logger.error(
            f'Invalid input for position size calculation: Entry={entry_price}, SL={stop_loss_price}, RiskAmt={risk_amount}'
        )
        return 0.0
    if min_trade_size <= 0 or min_tick <= 0:
        logger.error(
            f'Invalid contract details for position size calculation: MinSize={min_trade_size}, MinTick={min_tick}'
        )
        return 0.0

    # --- Calculate Risk Per Unit (including estimated costs) ---
    base_risk_per_unit = abs(entry_price - stop_loss_price)

    # Factor in estimated costs per unit (commission is usually round trip, slippage applies on entry/exit)
    # Simplified: Add half commission (entry) + full slippage (entry) to the risk per unit
    # A more complex model could estimate exit slippage/commission too.
    cost_per_unit = (commission_per_unit / 2.0) + slippage_per_unit
    effective_risk_per_unit = base_risk_per_unit + cost_per_unit

    # Ensure effective risk is meaningful (at least min_tick + costs)
    min_effective_risk = min_tick + cost_per_unit
    if effective_risk_per_unit < min_effective_risk:
        # logger.warning(f"Effective risk/unit ({effective_risk_per_unit:.5f}) for {symbol} below min ({min_effective_risk:.5f}). Using min.")
        effective_risk_per_unit = min_effective_risk

    if effective_risk_per_unit <= 1e-9:  # Check after cost adjustment
        logger.error(f'Cannot calculate position size: Effective risk per unit is zero/negative for {symbol}.')
        return 0.0

    # --- Calculate Raw Position Size ---
    if risk_amount <= 0:
        logger.warning('Risk amount is zero or negative. Cannot calculate position size.')
        return 0.0
    raw_position_size = risk_amount / effective_risk_per_unit

    # --- Apply Minimum Trade Size ---
    if raw_position_size < min_trade_size:
        # If calculated size is less than minimum, we cannot place the trade based on risk parameters.
        logger.warning(
            f'Calculated size {raw_position_size:.8f} for {symbol} is below minimum increment {min_trade_size:.8f}. Cannot meet risk/size constraints.'
        )
        return 0.0  # Cannot place trade meeting risk constraints at min size

    # --- Round Quantity Down ---
    position_size = round_quantity(raw_position_size, min_trade_size)

    if position_size < min_trade_size:  # Double check after rounding
        logger.warning(
            f'Position size {position_size:.8f} for {symbol} fell below minimum {min_trade_size:.8f} after rounding. Cannot place trade.'
        )
        return 0.0

    # --- Final Affordability Check (Using Available Funds) ---
    # Estimate margin/cost required for the calculated position size
    # TODO: Refine margin calculation based on asset type and broker rules
    estimated_cost = position_size * entry_price  # Basic cost for long
    # Margin for shorts or leveraged assets is more complex, use a buffer?
    # Assume available_funds represents the actual buying power/margin available
    required_funds_buffer_factor = 1.01  # Add 1% buffer
    required_funds = estimated_cost * required_funds_buffer_factor

    if required_funds > available_funds:
        logger.error(
            f'Calculated position size {position_size:.8f} for {symbol} is unaffordable. '
            f'Estimated Cost/Margin: {required_funds:.2f}, Available Funds: {available_funds:.2f}.'
        )
        # Optional: Try reducing size iteratively until affordable? Complex.
        # For now, fail the sizing if initial calculation is unaffordable.
        return 0.0

    # --- Log Final Size ---
    logger.info(
        f'Calculated position size for {symbol}: {position_size:.8f} '
        f'(Raw: {raw_position_size:.8f}, MinInc: {min_trade_size:.8f}, '
        f'RiskAmt: {risk_amount:.2f}, EffRisk/Unit: {effective_risk_per_unit:.5f})'
    )
    return position_size


# --- Deprecated Functions ---
# get_min_trade_size -> Moved to contract_utils.py, uses API details
# process_historical_data -> Logic moved into TradingBot.finalize_historical_data for better context
# merge_data_sources -> Keep if specifically needed elsewhere, but often handled by pd.concat/combine_first


def save_dataframe_to_csv(df, filepath, append=False):
    """Saves a DataFrame to CSV, creating directory if needed. (Thread-safe for separate files)"""
    if df is None or df.empty:
        logger.warning(f'Attempted to save an empty DataFrame to {filepath}. Skipping.')
        return False  # Indicate failure

    try:
        # Ensure the directory exists (handle potential race condition creating dir)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        mode = 'a' if append else 'w'
        # Write header only if file is new or overwriting
        write_header = not append or not os.path.exists(filepath)

        # Save DataFrame (ensure index is saved if it's meaningful, like timestamp)
        df.to_csv(filepath, mode=mode, header=write_header, index=True)  # Assume index is important
        logger.debug(f'DataFrame saved to {filepath} (Append={append}, Header={write_header})')
        return True  # Indicate success

    except Exception as e:
        logger.error(f'Error saving DataFrame to {filepath}: {e}', exc_info=True)
        return False  # Indicate failure
