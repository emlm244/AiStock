# utils/validation.py

"""
Comprehensive Input Validation and Configuration Validator

Provides production-grade validation for all user inputs, configuration values,
and system state to ensure safe operation and beginner-friendly error messages.
"""

import os
import re
import socket
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
import pytz


class ValidationError(Exception):
    """Custom exception for validation errors with actionable guidance"""
    def __init__(self, message: str, fix_suggestion: str = "", details: str = ""):
        self.message = message
        self.fix_suggestion = fix_suggestion
        self.details = details
        super().__init__(self.format_message())

    def format_message(self) -> str:
        """Format error message with guidance"""
        msg = f"\n❌ VALIDATION ERROR: {self.message}"
        if self.fix_suggestion:
            msg += f"\n\n💡 HOW TO FIX: {self.fix_suggestion}"
        if self.details:
            msg += f"\n\n📋 DETAILS: {self.details}"
        return msg


class ConfigValidator:
    """Validates configuration settings for safety and correctness"""

    # Valid ranges for risk parameters (safety limits)
    RISK_PER_TRADE_MIN = 0.001  # 0.1%
    RISK_PER_TRADE_MAX = 0.05   # 5%
    MAX_DAILY_LOSS_MIN = 0.01   # 1%
    MAX_DAILY_LOSS_MAX = 0.20   # 20%
    MAX_DRAWDOWN_MIN = 0.05     # 5%
    MAX_DRAWDOWN_MAX = 0.50     # 50%

    # Valid instrument patterns
    STOCK_PATTERN = re.compile(r'^[A-Z]{1,5}$')  # e.g., AAPL, MSFT
    CRYPTO_PATTERN = re.compile(r'^[A-Z]{3,}/[A-Z]{3}$')  # e.g., BTC/USD
    FOREX_PATTERN = re.compile(r'^[A-Z]{3}/[A-Z]{3}$')   # e.g., EUR/USD

    @staticmethod
    def validate_settings(settings) -> List[ValidationError]:
        """
        Validate all critical settings and return list of validation errors

        Returns:
            List of ValidationError objects (empty if all valid)
        """
        errors = []

        # Validate risk parameters
        errors.extend(ConfigValidator._validate_risk_parameters(settings))

        # Validate trading instruments
        errors.extend(ConfigValidator._validate_instruments(settings))

        # Validate API configuration
        errors.extend(ConfigValidator._validate_api_config())

        # Validate directories
        errors.extend(ConfigValidator._validate_directories())

        # Validate timezone
        errors.extend(ConfigValidator._validate_timezone(settings))

        # Validate timeframe
        errors.extend(ConfigValidator._validate_timeframe(settings))

        # Validate indicator parameters
        errors.extend(ConfigValidator._validate_indicators(settings))

        return errors

    @staticmethod
    def _validate_risk_parameters(settings) -> List[ValidationError]:
        """Validate risk management parameters"""
        errors = []

        # RISK_PER_TRADE
        risk_per_trade = getattr(settings, 'RISK_PER_TRADE', None)
        if risk_per_trade is None:
            errors.append(ValidationError(
                "RISK_PER_TRADE is not set",
                "Add RISK_PER_TRADE to config/settings.py (recommended: 0.01 for 1%)",
                "This controls how much capital you risk per trade"
            ))
        elif not isinstance(risk_per_trade, (int, float)):
            errors.append(ValidationError(
                f"RISK_PER_TRADE must be a number, got {type(risk_per_trade).__name__}",
                "Set RISK_PER_TRADE to a decimal value (e.g., 0.01 for 1%)"
            ))
        elif risk_per_trade < ConfigValidator.RISK_PER_TRADE_MIN:
            errors.append(ValidationError(
                f"RISK_PER_TRADE ({risk_per_trade:.1%}) is too low (min: {ConfigValidator.RISK_PER_TRADE_MIN:.1%})",
                f"Increase RISK_PER_TRADE to at least {ConfigValidator.RISK_PER_TRADE_MIN}",
                "Very low risk per trade may result in negligible position sizes"
            ))
        elif risk_per_trade > ConfigValidator.RISK_PER_TRADE_MAX:
            errors.append(ValidationError(
                f"RISK_PER_TRADE ({risk_per_trade:.1%}) is too high (max: {ConfigValidator.RISK_PER_TRADE_MAX:.1%})",
                f"Reduce RISK_PER_TRADE to at most {ConfigValidator.RISK_PER_TRADE_MAX} for safety",
                "High risk per trade can lead to catastrophic losses"
            ))

        # MAX_DAILY_LOSS
        max_daily_loss = getattr(settings, 'MAX_DAILY_LOSS', None)
        if max_daily_loss is None:
            errors.append(ValidationError(
                "MAX_DAILY_LOSS is not set",
                "Add MAX_DAILY_LOSS to config/settings.py (recommended: 0.03 for 3%)"
            ))
        elif not isinstance(max_daily_loss, (int, float)):
            errors.append(ValidationError(
                f"MAX_DAILY_LOSS must be a number, got {type(max_daily_loss).__name__}",
                "Set MAX_DAILY_LOSS to a decimal value (e.g., 0.03 for 3%)"
            ))
        elif max_daily_loss < ConfigValidator.MAX_DAILY_LOSS_MIN:
            errors.append(ValidationError(
                f"MAX_DAILY_LOSS ({max_daily_loss:.1%}) is too low (min: {ConfigValidator.MAX_DAILY_LOSS_MIN:.1%})",
                f"Increase MAX_DAILY_LOSS to at least {ConfigValidator.MAX_DAILY_LOSS_MIN}"
            ))
        elif max_daily_loss > ConfigValidator.MAX_DAILY_LOSS_MAX:
            errors.append(ValidationError(
                f"MAX_DAILY_LOSS ({max_daily_loss:.1%}) is too high (max: {ConfigValidator.MAX_DAILY_LOSS_MAX:.1%})",
                f"Reduce MAX_DAILY_LOSS to at most {ConfigValidator.MAX_DAILY_LOSS_MAX} for safety",
                "High daily loss limits can deplete capital quickly"
            ))

        # MAX_DRAWDOWN_LIMIT
        max_drawdown = getattr(settings, 'MAX_DRAWDOWN_LIMIT', None)
        if max_drawdown is None:
            errors.append(ValidationError(
                "MAX_DRAWDOWN_LIMIT is not set",
                "Add MAX_DRAWDOWN_LIMIT to config/settings.py (recommended: 0.15 for 15%)"
            ))
        elif not isinstance(max_drawdown, (int, float)):
            errors.append(ValidationError(
                f"MAX_DRAWDOWN_LIMIT must be a number, got {type(max_drawdown).__name__}",
                "Set MAX_DRAWDOWN_LIMIT to a decimal value (e.g., 0.15 for 15%)"
            ))
        elif max_drawdown < ConfigValidator.MAX_DRAWDOWN_MIN:
            errors.append(ValidationError(
                f"MAX_DRAWDOWN_LIMIT ({max_drawdown:.1%}) is too low (min: {ConfigValidator.MAX_DRAWDOWN_MIN:.1%})",
                f"Increase MAX_DRAWDOWN_LIMIT to at least {ConfigValidator.MAX_DRAWDOWN_MIN}"
            ))
        elif max_drawdown > ConfigValidator.MAX_DRAWDOWN_MAX:
            errors.append(ValidationError(
                f"MAX_DRAWDOWN_LIMIT ({max_drawdown:.1%}) is too high (max: {ConfigValidator.MAX_DRAWDOWN_MAX:.1%})",
                f"Reduce MAX_DRAWDOWN_LIMIT to at most {ConfigValidator.MAX_DRAWDOWN_MAX} for safety",
                "High drawdown limits increase risk of significant capital loss"
            ))

        # Validate relationship: MAX_DAILY_LOSS should be less than MAX_DRAWDOWN_LIMIT
        if max_daily_loss and max_drawdown and max_daily_loss >= max_drawdown:
            errors.append(ValidationError(
                f"MAX_DAILY_LOSS ({max_daily_loss:.1%}) should be less than MAX_DRAWDOWN_LIMIT ({max_drawdown:.1%})",
                "Set MAX_DAILY_LOSS < MAX_DRAWDOWN_LIMIT for proper risk layering"
            ))

        return errors

    @staticmethod
    def _validate_instruments(settings) -> List[ValidationError]:
        """Validate trading instruments"""
        errors = []

        trading_mode = getattr(settings, 'TRADING_MODE', 'crypto')
        instruments = getattr(settings, 'TRADE_INSTRUMENTS', [])

        if not instruments:
            errors.append(ValidationError(
                "No trading instruments specified",
                "Add instruments to TRADE_INSTRUMENTS list in settings (e.g., ['BTC/USD', 'ETH/USD'])"
            ))
            return errors

        if not isinstance(instruments, list):
            errors.append(ValidationError(
                f"TRADE_INSTRUMENTS must be a list, got {type(instruments).__name__}",
                "Format: TRADE_INSTRUMENTS = ['SYMBOL1', 'SYMBOL2']"
            ))
            return errors

        # Validate each instrument
        for instrument in instruments:
            if not isinstance(instrument, str):
                errors.append(ValidationError(
                    f"Invalid instrument type: {instrument} ({type(instrument).__name__})",
                    "All instruments must be strings"
                ))
                continue

            instrument = instrument.upper().strip()

            # Validate format based on trading mode
            if trading_mode == 'stock':
                if not ConfigValidator.STOCK_PATTERN.match(instrument):
                    errors.append(ValidationError(
                        f"Invalid stock symbol format: '{instrument}'",
                        "Stock symbols should be 1-5 uppercase letters (e.g., 'AAPL', 'MSFT')",
                        f"For stocks, use simple ticker symbols. Found: '{instrument}'"
                    ))
            elif trading_mode == 'crypto':
                if not ConfigValidator.CRYPTO_PATTERN.match(instrument):
                    errors.append(ValidationError(
                        f"Invalid crypto pair format: '{instrument}'",
                        "Crypto pairs should be 'CRYPTO/CURRENCY' format (e.g., 'BTC/USD', 'ETH/USD')",
                        f"Use format like 'BTC/USD' instead of '{instrument}'"
                    ))
            elif trading_mode == 'forex':
                if not ConfigValidator.FOREX_PATTERN.match(instrument):
                    errors.append(ValidationError(
                        f"Invalid forex pair format: '{instrument}'",
                        "Forex pairs should be 'CUR1/CUR2' format (e.g., 'EUR/USD', 'GBP/USD')",
                        f"Use format like 'EUR/USD' instead of '{instrument}'"
                    ))

        return errors

    @staticmethod
    def _validate_api_config() -> List[ValidationError]:
        """Validate Interactive Brokers API configuration"""
        errors = []

        try:
            from config.credentials import IBKR
        except ImportError:
            errors.append(ValidationError(
                "Cannot import IBKR credentials from config/credentials.py",
                "Create config/credentials.py with IBKR dictionary containing TWS_HOST, TWS_PORT, ACCOUNT_ID, CLIENT_ID",
                "Copy config/credentials_template.py if it exists, or create a new file"
            ))
            return errors

        # Validate ACCOUNT_ID
        account_id = IBKR.get('ACCOUNT_ID')
        if not account_id or account_id == 'YOUR_ACCOUNT_ID':
            errors.append(ValidationError(
                "IBKR_ACCOUNT_ID is not configured",
                "Set your Interactive Brokers account ID in config/credentials.py",
                "Find your account ID in TWS: Account > Account Info, or in Client Portal"
            ))

        # Validate TWS_PORT
        port = IBKR.get('TWS_PORT', 7497)
        if not isinstance(port, int):
            errors.append(ValidationError(
                f"Invalid TWS_PORT type: {type(port).__name__}",
                "TWS_PORT must be an integer (7497 for paper trading, 7496 for live)"
            ))
        elif port not in [4001, 4002, 7496, 7497]:
            errors.append(ValidationError(
                f"Unusual TWS_PORT: {port}",
                "Common ports: 7497 (TWS Paper), 7496 (TWS Live), 4002 (Gateway Paper), 4001 (Gateway Live)",
                "Verify this port matches your TWS/Gateway configuration"
            ))

        # Validate host connectivity
        host = IBKR.get('TWS_HOST', '127.0.0.1')
        try:
            # Quick connectivity check (non-blocking)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()

            if result != 0:
                errors.append(ValidationError(
                    f"Cannot connect to TWS/Gateway at {host}:{port}",
                    "1. Ensure TWS or IB Gateway is running\n"
                    "   2. Enable API connections in TWS: File > Global Configuration > API > Settings\n"
                    "   3. Check 'Enable ActiveX and Socket Clients'\n"
                    "   4. Verify the port number matches your TWS/Gateway configuration",
                    f"Connection attempt to {host}:{port} failed. Is TWS/Gateway running?"
                ))
        except socket.error as e:
            errors.append(ValidationError(
                f"Network error checking TWS connection: {e}",
                "Check your network settings and firewall configuration"
            ))

        return errors

    @staticmethod
    def _validate_directories() -> List[ValidationError]:
        """Validate required directories exist and are writable"""
        errors = []

        required_dirs = [
            ('logs', 'Store log files'),
            ('logs/error_logs', 'Store error logs'),
            ('logs/trade_logs', 'Store trade execution logs'),
            ('data', 'Store market data'),
            ('data/historical_data', 'Store historical price data'),
            ('data/live_data', 'Store live price data'),
            ('models', 'Store trained ML models'),
            ('config', 'Store configuration files'),
        ]

        for dir_path, description in required_dirs:
            path = Path(dir_path)

            # Check if directory exists
            if not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    errors.append(ValidationError(
                        f"Cannot create required directory: {dir_path}",
                        f"Manually create directory '{dir_path}' or fix permissions",
                        f"Purpose: {description}. Error: {e}"
                    ))
                    continue

            # Check if writable
            test_file = path / '.write_test'
            try:
                test_file.touch()
                test_file.unlink()
            except Exception as e:
                errors.append(ValidationError(
                    f"Directory '{dir_path}' is not writable",
                    f"Fix permissions for directory '{dir_path}'",
                    f"Purpose: {description}. Error: {e}"
                ))

        return errors

    @staticmethod
    def _validate_timezone(settings) -> List[ValidationError]:
        """Validate timezone settings"""
        errors = []

        timezone_str = getattr(settings, 'TIMEZONE', 'America/New_York')

        if not timezone_str:
            errors.append(ValidationError(
                "TIMEZONE is not set",
                "Add TIMEZONE to config/settings.py (e.g., 'America/New_York')",
                "This controls daily resets and market hours detection"
            ))
            return errors

        try:
            pytz.timezone(timezone_str)
        except pytz.UnknownTimeZoneError:
            errors.append(ValidationError(
                f"Invalid timezone: '{timezone_str}'",
                "Use a valid IANA timezone name (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo')",
                "See: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
            ))

        # Validate TWS_TIMEZONE
        tws_tz_str = getattr(settings, 'TWS_TIMEZONE', timezone_str)
        try:
            pytz.timezone(tws_tz_str)
        except pytz.UnknownTimeZoneError:
            errors.append(ValidationError(
                f"Invalid TWS_TIMEZONE: '{tws_tz_str}'",
                "Set TWS_TIMEZONE to match where your TWS/Gateway is running",
                "This is critical for correct timestamp parsing from IBKR API"
            ))

        return errors

    @staticmethod
    def _validate_timeframe(settings) -> List[ValidationError]:
        """Validate timeframe setting"""
        errors = []

        timeframe = getattr(settings, 'TIMEFRAME', '30 secs')

        # Valid IB timeframe formats
        valid_units = ['sec', 'secs', 'min', 'mins', 'hour', 'hours', 'day', 'days']

        timeframe_str = str(timeframe).lower().strip()
        parts = timeframe_str.split()

        if len(parts) not in [1, 2]:
            errors.append(ValidationError(
                f"Invalid TIMEFRAME format: '{timeframe}'",
                "Use format: '<number> <unit>' (e.g., '30 secs', '5 mins', '1 hour')",
                "Valid units: sec, min, hour, day (with optional 's')"
            ))
            return errors

        # Check if number is valid
        value_str = parts[0]
        try:
            value = int(value_str)
            if value <= 0:
                errors.append(ValidationError(
                    f"TIMEFRAME value must be positive, got: {value}",
                    "Set TIMEFRAME to a positive number (e.g., '30 secs', '5 mins')"
                ))
        except ValueError:
            errors.append(ValidationError(
                f"Invalid TIMEFRAME number: '{value_str}'",
                "TIMEFRAME must start with a valid number (e.g., '30 secs', '5 mins')"
            ))
            return errors

        # Check unit if specified
        if len(parts) == 2:
            unit = parts[1]
            if not any(unit.startswith(valid_unit) for valid_unit in valid_units):
                errors.append(ValidationError(
                    f"Invalid TIMEFRAME unit: '{unit}'",
                    f"Use one of: {', '.join(valid_units)}",
                    f"Example: '30 secs', '5 mins', '1 hour'"
                ))

        return errors

    @staticmethod
    def _validate_indicators(settings) -> List[ValidationError]:
        """Validate technical indicator parameters"""
        errors = []

        # Validate ATR period
        atr_period = getattr(settings, 'ATR_PERIOD', 14)
        if not isinstance(atr_period, int) or atr_period < 2:
            errors.append(ValidationError(
                f"ATR_PERIOD must be an integer >= 2, got: {atr_period}",
                "Set ATR_PERIOD to a reasonable value (typical: 14)"
            ))
        elif atr_period > 100:
            errors.append(ValidationError(
                f"ATR_PERIOD ({atr_period}) is unusually high",
                "Consider using a smaller period (typical: 14-21) for more responsive indicators"
            ))

        # Validate RSI period
        rsi_period = getattr(settings, 'RSI_PERIOD', 14)
        if not isinstance(rsi_period, int) or rsi_period < 2:
            errors.append(ValidationError(
                f"RSI_PERIOD must be an integer >= 2, got: {rsi_period}",
                "Set RSI_PERIOD to a reasonable value (typical: 14)"
            ))

        # Validate RSI thresholds
        rsi_overbought = getattr(settings, 'RSI_OVERBOUGHT', 70)
        rsi_oversold = getattr(settings, 'RSI_OVERSOLD', 30)

        if not (0 < rsi_oversold < rsi_overbought < 100):
            errors.append(ValidationError(
                f"Invalid RSI thresholds: oversold={rsi_oversold}, overbought={rsi_overbought}",
                "Set 0 < RSI_OVERSOLD < RSI_OVERBOUGHT < 100 (typical: 30 and 70)"
            ))

        return errors


class InputValidator:
    """Validates user inputs during runtime"""

    @staticmethod
    def validate_symbol_input(symbol: str, trading_mode: str) -> Tuple[bool, str, str]:
        """
        Validate symbol/instrument input from user

        Returns:
            (is_valid, cleaned_symbol, error_message)
        """
        if not symbol or not isinstance(symbol, str):
            return False, "", "Symbol cannot be empty"

        symbol = symbol.upper().strip()

        if trading_mode == 'stock':
            if ConfigValidator.STOCK_PATTERN.match(symbol):
                return True, symbol, ""
            return False, symbol, f"Invalid stock symbol: '{symbol}'. Use 1-5 letters (e.g., 'AAPL')"

        elif trading_mode == 'crypto':
            if ConfigValidator.CRYPTO_PATTERN.match(symbol):
                return True, symbol, ""
            return False, symbol, f"Invalid crypto pair: '{symbol}'. Use format 'BTC/USD'"

        elif trading_mode == 'forex':
            if ConfigValidator.FOREX_PATTERN.match(symbol):
                return True, symbol, ""
            return False, symbol, f"Invalid forex pair: '{symbol}'. Use format 'EUR/USD'"

        return False, symbol, f"Unknown trading mode: {trading_mode}"

    @staticmethod
    def validate_number_input(
        value: str,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        allow_negative: bool = False
    ) -> Tuple[bool, Optional[float], str]:
        """
        Validate numeric input

        Returns:
            (is_valid, parsed_number, error_message)
        """
        try:
            number = float(value)
        except (ValueError, TypeError):
            return False, None, f"'{value}' is not a valid number"

        if not allow_negative and number < 0:
            return False, number, "Number must be non-negative"

        if min_val is not None and number < min_val:
            return False, number, f"Number must be at least {min_val}"

        if max_val is not None and number > max_val:
            return False, number, f"Number must be at most {max_val}"

        return True, number, ""

    @staticmethod
    def validate_yes_no_input(value: str) -> Tuple[bool, bool, str]:
        """
        Validate yes/no input

        Returns:
            (is_valid, boolean_value, error_message)
        """
        if not value or not isinstance(value, str):
            return False, False, "Input cannot be empty"

        value_lower = value.lower().strip()

        if value_lower in ['y', 'yes', '1', 'true', 't']:
            return True, True, ""
        elif value_lower in ['n', 'no', '0', 'false', 'f']:
            return True, False, ""
        else:
            return False, False, f"Invalid input: '{value}'. Please enter 'y' or 'n'"
