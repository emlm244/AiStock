import logging
import os
from colorama import Fore, Style, init

init(autoreset=True)

class ColoredFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        level_color = self.LEVEL_COLORS.get(record.levelno, '')

        # Customize colors for specific messages
        if 'Trade executed' in record.msg:
            level_color = Fore.BLUE
        elif 'Starting new trade execution' in record.msg:
            level_color = Fore.MAGENTA
        elif 'Connected to IBKR TWS' in record.msg:
            level_color = Fore.GREEN + Style.BRIGHT
        elif 'Disconnected from IBKR TWS' in record.msg:
            level_color = Fore.RED + Style.BRIGHT
        elif 'Error' in record.msg or 'Exception' in record.msg:
            level_color = Fore.RED + Style.BRIGHT
        elif 'Not enough data' in record.msg:
            level_color = Fore.YELLOW + Style.BRIGHT
        elif 'Maximum daily loss limit reached' in record.msg:
            level_color = Fore.RED + Style.BRIGHT
        # Add any other specific message patterns and colors as needed

        record.msg = f"{level_color}{record.msg}{Style.RESET_ALL}"
        return super().format(record)

def setup_logger(name, log_file, level=logging.INFO, console=True):
    # Convert level to numeric if it's a string
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # Formatter without colors for file handler
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Colored formatter for console handler
    console_formatter = ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s')

    # Ensure the directory exists
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers = []

    if log_file:
        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    # Console handler
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger




