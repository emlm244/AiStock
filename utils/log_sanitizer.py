"""
Log Sanitization Utilities

Prevents sensitive information from appearing in logs.
Automatically redacts credentials, API keys, account IDs, and other secrets.
"""

import logging
import re
from typing import Any


class SensitiveDataFilter(logging.Filter):
    """
    Logging filter that sanitizes sensitive data from log records.

    Redacts:
    - Account IDs
    - API keys
    - Passwords
    - Tokens
    - Credit card numbers
    - SSNs
    - Email addresses (optional)
    """

    # Patterns to detect and redact
    PATTERNS = {
        'account_id': (
            r'(?i)(account[_\s-]?id|acct[_\s-]?id|account[_\s-]?number)[\s:=]+([A-Z0-9]{6,})',
            r'\1: ***REDACTED***',
        ),
        'api_key': (
            r'(?i)(api[_\s-]?key|apikey|access[_\s-]?key)[\s:=]+([A-Za-z0-9\-_]{20,})',
            r'\1: ***REDACTED***',
        ),
        'password': (r'(?i)(password|passwd|pwd)[\s:=]+(\S+)', r'\1: ***REDACTED***'),
        'token': (r'(?i)(token|bearer)[\s:=]+([A-Za-z0-9\-_.]{20,})', r'\1: ***REDACTED***'),
        'credit_card': (
            r'\b(?:\d{4}[\s-]?){3}\d{4}\b',  # 16-digit credit card
            '****-****-****-****',
        ),
        'ssn': (
            r'\b\d{3}-\d{2}-\d{4}\b',  # SSN format
            '***-**-****',
        ),
        # Specific to IB
        'ib_account': (
            r'\b(DU|U)\d{6,}\b',  # IB account format (DU123456 or U123456)
            '***ACCOUNT***',
        ),
    }

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log record to redact sensitive data.

        Returns:
            True (always allow record, but sanitize it first)
        """
        # Sanitize the message
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = self.sanitize(record.msg)

        # Sanitize args if present
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = {k: self.sanitize(str(v)) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(self.sanitize(str(arg)) if isinstance(arg, str) else arg for arg in record.args)

        return True

    @classmethod
    def sanitize(cls, text: str) -> str:
        """
        Sanitize a string by redacting sensitive patterns.

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text with sensitive data redacted
        """
        if not isinstance(text, str):
            return text

        sanitized = text
        for name, (pattern, replacement) in cls.PATTERNS.items():
            sanitized = re.sub(pattern, replacement, sanitized)

        return sanitized

    @classmethod
    def sanitize_dict(cls, data: dict) -> dict:
        """
        Recursively sanitize a dictionary.

        Args:
            data: Dictionary to sanitize

        Returns:
            Sanitized dictionary
        """
        if not isinstance(data, dict):
            return data

        sanitized = {}
        for key, value in data.items():
            # Redact entire value if key looks sensitive
            if cls._is_sensitive_key(key):
                sanitized[key] = '***REDACTED***'
            elif isinstance(value, str):
                sanitized[key] = cls.sanitize(value)
            elif isinstance(value, dict):
                sanitized[key] = cls.sanitize_dict(value)
            elif isinstance(value, (list, tuple)):
                sanitized[key] = [cls.sanitize(str(v)) if isinstance(v, str) else v for v in value]
            else:
                sanitized[key] = value

        return sanitized

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        """Check if a dictionary key indicates sensitive data."""
        sensitive_keywords = [
            'password',
            'passwd',
            'pwd',
            'secret',
            'token',
            'api_key',
            'apikey',
            'access_key',
            'account_id',
            'account_number',
            'credit_card',
            'ssn',
            'social_security',
        ]
        key_lower = str(key).lower()
        return any(keyword in key_lower for keyword in sensitive_keywords)


def install_sanitizer_on_logger(logger: logging.Logger) -> None:
    """
    Install sensitive data filter on a logger.

    Args:
        logger: Logger instance to protect
    """
    # Check if already installed
    for filter_obj in logger.filters:
        if isinstance(filter_obj, SensitiveDataFilter):
            return

    logger.addFilter(SensitiveDataFilter())


def install_sanitizer_globally() -> None:
    """
    Install sensitive data filter on all existing loggers and the root logger.
    """
    # Install on root logger
    root_logger = logging.getLogger()
    install_sanitizer_on_logger(root_logger)

    # Install on all existing loggers
    for logger_name in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        if isinstance(logger, logging.Logger):  # Skip PlaceHolder objects
            install_sanitizer_on_logger(logger)


# Convenience function for one-off sanitization
def sanitize_for_display(data: Any) -> Any:
    """
    Sanitize data for safe display (logs, console, etc.).

    Args:
        data: Data to sanitize (str, dict, list, etc.)

    Returns:
        Sanitized version of data
    """
    if isinstance(data, str):
        return SensitiveDataFilter.sanitize(data)
    elif isinstance(data, dict):
        return SensitiveDataFilter.sanitize_dict(data)
    elif isinstance(data, (list, tuple)):
        return [sanitize_for_display(item) for item in data]
    else:
        return data


__all__ = ['SensitiveDataFilter', 'install_sanitizer_on_logger', 'install_sanitizer_globally', 'sanitize_for_display']
