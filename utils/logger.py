# utils/logger.py
import logging
import os
import sys  # <--- ADDED IMPORT
import threading  # <--- ADDED IMPORT
from datetime import datetime

import pytz  # Import pytz
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Attempt to import settings for format and timezone
try:
    from config.settings import Settings

    LOG_TS_FORMAT = Settings.LOG_TIMESTAMP_FORMAT
    DEFAULT_TZ_STR = Settings.TIMEZONE
except ImportError:
    # Fallback if settings cannot be imported (e.g., during early setup)
    LOG_TS_FORMAT = '%Y-%m-%d %H:%M:%S %Z%z'  # Example: 2023-10-27 10:30:00 EDT-0400
    DEFAULT_TZ_STR = 'UTC'  # Safe fallback

# Attempt to get the timezone object
try:
    DEFAULT_TZ = pytz.timezone(DEFAULT_TZ_STR)
except pytz.UnknownTimeZoneError:
    print(f"Warning: Unknown timezone '{DEFAULT_TZ_STR}' in logger setup. Using UTC.")
    DEFAULT_TZ = pytz.utc
except Exception as e:
    print(f'Error setting timezone in logger: {e}. Using UTC.')
    DEFAULT_TZ = pytz.utc


class TimezoneFormatter(logging.Formatter):
    """Custom formatter to include timezone-aware timestamps using the DEFAULT_TZ."""

    def formatTime(self, record, datefmt=None):
        # Convert record creation time (timestamp) to aware datetime in the default timezone
        dt = datetime.fromtimestamp(record.created, DEFAULT_TZ)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            # Default format if none specified
            s = dt.isoformat(timespec='milliseconds')
        return s


class ColoredFormatter(TimezoneFormatter):  # Inherit from TimezoneFormatter
    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.MAGENTA + Style.BRIGHT,  # Changed Critical color
    }
    KEYWORD_COLORS = {
        'Submitted': Fore.BLUE,
        'Filled': Fore.GREEN + Style.BRIGHT,
        'Cancelled': Fore.YELLOW + Style.BRIGHT,
        'Rejected': Fore.RED + Style.BRIGHT,
        'Connected': Fore.GREEN + Style.BRIGHT,
        'Disconnected': Fore.RED + Style.BRIGHT,
        'Error': Fore.RED + Style.BRIGHT,
        'Exception': Fore.RED + Style.BRIGHT,
        'Failed': Fore.RED + Style.BRIGHT,
        'CRITICAL': Fore.MAGENTA + Style.BRIGHT,
        'Warning': Fore.YELLOW + Style.BRIGHT,  # Ensure warnings stand out
        'Skipping': Fore.YELLOW,
        'HALTED': Fore.RED + Style.BRIGHT,
        'Resuming': Fore.GREEN + Style.BRIGHT,
        'limit reached': Fore.RED + Style.BRIGHT,
        'Retraining': Fore.CYAN + Style.BRIGHT,
    }

    def format(self, record):
        # Apply level color first
        level_color = self.LEVEL_COLORS.get(record.levelno, Fore.WHITE)  # Default to white
        # Base formatted message using parent class (handles timestamp)
        formatted_message = super().format(record)

        # Apply keyword coloring to the entire formatted message for emphasis
        final_message = formatted_message
        # Sort keywords by length descending to match longer keywords first
        sorted_keywords = sorted(self.KEYWORD_COLORS.keys(), key=len, reverse=True)
        for keyword in sorted_keywords:
            # Case-insensitive keyword check
            if keyword.lower() in formatted_message.lower():
                # Apply color more broadly to the line containing the keyword
                final_message = f'{self.KEYWORD_COLORS[keyword]}{formatted_message}{Style.RESET_ALL}'
                break  # Apply first matching keyword color

        # Ensure level color is still visible if no keyword matched, or enhance keyword match
        # Example: Prepend level color if no keyword matched
        if final_message == formatted_message:  # No keyword color applied
            # Manually format with level color (less precise than Formatter's templating)
            # This part is tricky to get right without re-parsing the format string.
            # Let's just ensure CRITICAL/ERROR always have strong color.
            if record.levelno >= logging.ERROR:
                final_message = f'{level_color}{formatted_message}{Style.RESET_ALL}'
            # else keep default color from formatter + keyword logic

        return final_message


# Cache for initialized loggers
_loggers = {}
_logger_lock = threading.Lock()


def setup_logger(name, log_file=None, level=logging.INFO, console=True, sanitize=True):
    """Sets up a logger with specified handlers and formatters (thread-safe).

    Args:
        name: Logger name
        log_file: Path to log file (optional)
        level: Logging level
        console: Whether to log to console
        sanitize: Whether to install sensitive data filter (default: True)
    """
    with _logger_lock:
        # Check cache first
        if name in _loggers:
            return _loggers[name]

        # Convert level string to numeric if necessary
        log_level = level
        if isinstance(level, str):
            log_level = getattr(logging, level.upper(), logging.INFO)

        # Define format string using the setting
        log_format = '%(asctime)s - %(levelname)-8s - [%(name)-15s] - %(message)s'  # Adjusted name width

        # Formatter without colors for file handler
        file_formatter = TimezoneFormatter(log_format, datefmt=LOG_TS_FORMAT)
        # Colored formatter for console handler
        console_formatter = ColoredFormatter(log_format, datefmt=LOG_TS_FORMAT)

        logger = logging.getLogger(name)
        logger.setLevel(log_level)

        # Prevent adding handlers multiple times if logger already exists (though cache check handles this)
        if logger.hasHandlers():
            logger.handlers.clear()

        # File Handler (Optional)
        if log_file:
            try:
                # Ensure the directory exists
                log_dir = os.path.dirname(log_file)
                if log_dir:  # Avoid error if log_file is in current dir
                    os.makedirs(log_dir, exist_ok=True)
                # Use rotating file handler for larger logs? For simplicity, basic for now.
                file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='a')  # Append mode
                file_handler.setFormatter(file_formatter)
                logger.addHandler(file_handler)
            except Exception as e:
                print(f'Error setting up file handler for {log_file}: {e}')
                # Fallback to console logging only?

        # Console Handler (Optional)
        if console:
            console_handler = logging.StreamHandler(sys.stdout)  # Explicitly use stdout
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)

        # Prevent propagation to root logger to avoid duplicate messages
        logger.propagate = False

        # Install sensitive data filter
        if sanitize:
            try:
                from utils.log_sanitizer import install_sanitizer_on_logger

                install_sanitizer_on_logger(logger)
            except ImportError:
                # Sanitizer not available, continue without it
                pass

        # Add to cache
        _loggers[name] = logger
        return logger
