# managers/risk_manager.py
from datetime import datetime, date, time as dt_time
import pytz # Import pytz
import numpy as np

from utils.logger import setup_logger
from config.settings import Settings
# No direct state modification, primarily reads from PM, so locking might be less critical here,
# but needs careful review if RiskManager develops its own complex state.


class RiskManager:
    """
    Manages trading risk based on predefined rules. Halts trading if limits are breached.
    Includes checks for daily loss, maximum drawdown (with recovery), and pre-trade assessments.
    """
    def __init__(self, portfolio_manager, settings, logger=None):
        self.portfolio_manager = portfolio_manager # Needs PortfolioManager instance
        self.settings = settings
        self.logger = logger or setup_logger('RiskManager', 'logs/app.log', level=settings.LOG_LEVEL)
        self.error_logger = setup_logger('RiskError', 'logs/error_logs/errors.log', level='ERROR')

        # Timezone setup
        try:
            self.default_tz = pytz.timezone(self.settings.TIMEZONE)
        except pytz.UnknownTimeZoneError:
            self.logger.warning(f"Unknown timezone '{self.settings.TIMEZONE}' in settings. Using UTC for daily reset.")
            self.default_tz = pytz.utc
        except Exception as e:
            self.logger.error(f"Error setting risk manager timezone: {e}. Using UTC.")
            self.default_tz = pytz.utc

        # Risk State
        self._trading_halted = False
        self._halt_reason = ""
        self._last_daily_reset_date = date.min # Date of last daily limit reset
        self._halted_by_drawdown = False # Flag if current halt is due to max drawdown breach

    def _check_reset_daily_limits(self):
        """Resets daily loss limit halt status if a new trading day has started."""
        # This method only resets the halt IF it was triggered by the daily loss limit.
        # Drawdown halts persist until recovery.
        now_local = datetime.now(self.default_tz)
        today_local = now_local.date()

        if today_local > self._last_daily_reset_date:
            self.logger.info(f"RiskManager: New day ({today_local} in {self.default_tz.zone}). Resetting daily loss tracking.")
            # PM handles resetting its daily PnL value via its own check or load
            self._last_daily_reset_date = today_local
            # Reset halt *only if* it was due to daily loss and not drawdown
            if self._trading_halted and not self._halted_by_drawdown:
                 self.logger.info("Daily loss limit halt lifted for the new day.")
                 self._trading_halted = False
                 self._halt_reason = ""
            # else: Keep drawdown halt active

    def check_portfolio_risk(self, latest_prices):
        """
        Checks overall portfolio risk, including daily loss and max drawdown limits.
        Updates the trading halt status. Handles drawdown recovery.

        Args:
            latest_prices (dict): {symbol: {'price': float, 'time_utc': datetime}}.
                                   (Currently unused here, but could be for position value checks).
        """
        self._check_reset_daily_limits() # Reset daily limits/halt if needed

        # Check for Drawdown Recovery FIRST
        if self._trading_halted and self._halted_by_drawdown:
            current_drawdown = self.portfolio_manager.get_current_drawdown()
            recovery_threshold = self.settings.MAX_DRAWDOWN_LIMIT * self.settings.DRAWDOWN_RECOVERY_THRESHOLD_FACTOR
            if current_drawdown < recovery_threshold:
                 self.logger.warning(f"Drawdown recovered below threshold ({current_drawdown:.2%} < {recovery_threshold:.2%}). Resuming trading.")
                 self._trading_halted = False
                 self._halted_by_drawdown = False
                 self._halt_reason = ""
            else:
                 # Still halted by drawdown, log occasionally and return
                 self.logger.warning(f"Trading remains halted due to Max Drawdown ({current_drawdown:.2%} >= limit {self.settings.MAX_DRAWDOWN_LIMIT:.2%}). Recovery needed below {recovery_threshold:.2%}.")
                 return

        # If already halted for other reasons (e.g., daily loss), return
        if self._trading_halted:
            self.logger.warning(f"Trading remains halted. Reason: {self._halt_reason}")
            return


        # --- Daily Loss Limit Check ---
        daily_pnl = self.portfolio_manager.get_daily_pnl()
        # Use initial capital as base, ensure max_loss is non-negative
        max_loss_amount = max(0.0, self.portfolio_manager.initial_capital * self.settings.MAX_DAILY_LOSS)

        # Use isclose for float comparison robustness
        if daily_pnl < 0 and not np.isclose(daily_pnl, -max_loss_amount) and daily_pnl < -max_loss_amount :
            self._trading_halted = True
            self._halted_by_drawdown = False # Explicitly not a drawdown halt
            self._halt_reason = f"Maximum daily loss limit reached ({daily_pnl:.2f} vs limit -{max_loss_amount:.2f})"
            self.logger.critical(f"RISK ALERT: {self._halt_reason}. Halting new trade entries for the day.")
            return # Halt triggered, no need for further checks


        # --- Maximum Drawdown Check ---
        current_drawdown = self.portfolio_manager.get_current_drawdown()
        max_drawdown_limit = self.settings.MAX_DRAWDOWN_LIMIT

        # Use isclose for float comparison
        if current_drawdown > 0 and not np.isclose(current_drawdown, max_drawdown_limit) and current_drawdown > max_drawdown_limit:
            self._trading_halted = True
            self._halted_by_drawdown = True # Mark as drawdown halt
            self._halt_reason = f"Maximum portfolio drawdown limit ({max_drawdown_limit:.1%}) breached. Current DD: {current_drawdown:.1%}"
            self.logger.critical(f"RISK ALERT: {self._halt_reason}. Halting ALL trading activity until recovery.")
            return # Halt triggered


        # --- Optional: Overall Position Concentration Check ---
        # equity = self.portfolio_manager.get_total_equity()
        # max_single_pos_pct = getattr(self.settings, 'MAX_SINGLE_POSITION_PERCENT', None)
        # if equity > 0 and max_single_pos_pct is not None and max_single_pos_pct > 0:
        #     positions_copy = self.portfolio_manager.get_positions_copy() # Get thread-safe copy
        #     for symbol, pos_data in positions_copy.items():
        #         qty = pos_data['quantity']
        #         price_data = latest_prices.get(symbol)
        #         if not np.isclose(qty, 0.0) and price_data and price_data['price'] > 0:
        #             position_value = abs(qty * price_data['price'])
        #             max_allowed_value = equity * max_single_pos_pct
        #             if position_value > max_allowed_value:
        #                  # Handle breach - Log warning, maybe halt specific symbol, reduce size?
        #                  self.logger.warning(f"Risk Warning: Position value for {symbol} ({position_value:.2f}) exceeds threshold ({max_allowed_value:.2f} = {max_single_pos_pct:.1%} of equity)")
        #                  # Example: Halt trading for this specific symbol?
        #                  # self.trading_bot.symbol_trading_paused[symbol] = True


    def check_pre_trade_risk(self, symbol, action, quantity, price, available_funds):
        """
        Checks if a potential trade violates risk rules before placing the order.

        Args:
            symbol (str): The symbol to trade.
            action (str): 'BUY' or 'SELL'.
            quantity (float): The quantity to trade (positive).
            price (float): The estimated execution price.
            available_funds (float): Funds available for trading (from PM, ideally broker value).

        Returns:
            bool: True if the trade passes risk checks, False otherwise.
        """
        # Check reset first as halt status might change based on daily reset
        self._check_reset_daily_limits()

        if self._trading_halted:
            self.logger.warning(f"Pre-trade check failed for {symbol}: Trading is halted ({self._halt_reason}).")
            return False

        # --- Max Position Size Check (Units) --- - Optional, % value often better
        # max_pos_units = getattr(self.settings, 'MAX_POSITION_SIZE_UNITS', None)
        # if max_pos_units is not None:
        #     current_position = self.portfolio_manager.get_position_size(symbol)
        #     potential_new_position_qty = current_position + quantity if action == 'BUY' else current_position - quantity
        #     if abs(potential_new_position_qty) > max_pos_units:
        #          self.logger.warning(f"Pre-trade check failed for {symbol}: Potential position size ({abs(potential_new_position_qty):.4f} units) exceeds MAX_POSITION_SIZE_UNITS ({max_pos_units}).")
        #          return False

        # --- Max Position Value Check (% Equity) ---
        max_single_pos_pct = getattr(self.settings, 'MAX_SINGLE_POSITION_PERCENT', None)
        if max_single_pos_pct is not None and max_single_pos_pct > 0:
            equity = self.portfolio_manager.get_total_equity()
            if equity <= 0:
                 self.logger.error("Pre-trade check failed: Portfolio equity is non-positive. Cannot assess value risk.")
                 return False

            current_position = self.portfolio_manager.get_position_size(symbol)
            potential_new_position_qty = current_position + quantity if action == 'BUY' else current_position - quantity
            potential_value = abs(potential_new_position_qty * price)
            max_allowed_value = equity * max_single_pos_pct

            if potential_value > max_allowed_value:
                 self.logger.warning(f"Pre-trade check failed for {symbol}: Potential position value ({potential_value:.2f}) would exceed limit ({max_allowed_value:.2f} = {max_single_pos_pct:.1%} of equity).")
                 return False

        # --- Affordability Check (Using Available Funds) ---
        # This is crucial, especially for margin accounts.
        required_margin = 0.0
        # TODO: Implement a more sophisticated margin calculation based on asset type, leverage rules.
        # Simple approximation for now: Cost of shares for BUYs. Shorting margin is complex.
        if action == 'BUY':
             required_margin = quantity * price # Approximate cost
             # Add buffer for potential slippage/commissions?
             required_margin *= 1.01

        if required_margin > available_funds:
            self.logger.error(
                f"Pre-trade check FAILED for {action} {symbol}: Estimated required margin/cost ({required_margin:.2f}) "
                f"exceeds available funds ({available_funds:.2f})."
            )
            return False


        # --- Add other pre-trade checks as needed ---
        # E.g., concurrent open orders limit? Pattern Day Trader rules (complex)?

        # If all checks passed:
        self.logger.debug(f"Pre-trade risk check passed for {action} {quantity:.8f} {symbol} @ {price:.5f}")
        return True


    def is_trading_halted(self):
        """Returns True if the risk manager has halted trading."""
        # Check reset first to potentially un-halt if it's a new day (for daily loss limit)
        # And check for drawdown recovery
        self.check_portfolio_risk({}) # Pass empty prices, only need drawdown/daily check here
        return self._trading_halted

    def get_halt_reason(self):
        """Returns the reason for the trading halt."""
        return self._halt_reason

    def force_halt(self, reason="Manual halt requested."):
        """ Manually halts trading. """
        if not self._trading_halted:
             self.logger.warning(f"Forcing trading halt. Reason: {reason}")
             self._trading_halted = True
             self._halt_reason = reason
             self._halted_by_drawdown = "drawdown" in reason.lower() # Heuristic guess if manual halt is DD related
        else:
             self.logger.info("Trading already halted.")

    def resume_trading(self):
        """ Manually resumes trading if halted (use with caution). """
        if self._trading_halted:
            self.logger.warning(f"Manually resuming trading. Previous halt reason: {self._halt_reason}")
            self._trading_halted = False
            self._halted_by_drawdown = False
            self._halt_reason = ""
            # Reset last daily reset date to allow daily loss check again if resuming mid-day? Risky.
            # self._last_daily_reset_date = date.min
        else:
            self.logger.info("Trading is not currently halted.")