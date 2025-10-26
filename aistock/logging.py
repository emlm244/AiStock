"""
Structured logging helpers built solely on the Python standard library.

P0 Fix: Includes sensitive field redaction to prevent credential leakage.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# P0 Fix: Sensitive keys that should be redacted in logs
_SENSITIVE_KEYS: set[str] = {
    "ib_account",
    "ibkr_account",
    "account",
    "password",
    "api_key",
    "secret",
    "token",
    "credential",
    "auth",
    "authorization",
}


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    key_lower = key.lower()
    return any(sensitive in key_lower for sensitive in _SENSITIVE_KEYS)


def _to_serialisable(value: Any, key: str | None = None) -> Any:
    """
    Convert objects to JSON-serializable types with sensitive field redaction.

    Args:
        value: The value to serialize
        key: The field name (used for sensitivity checking)
    """
    # P0 Fix: Redact sensitive fields
    if key and _is_sensitive_key(key):
        return "[REDACTED]"

    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter with P0 Fix for sensitive field redaction.

    Automatically redacts fields containing sensitive keywords like
    'account', 'password', 'token', etc.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.args:
            payload["args"] = [_to_serialisable(arg, None) for arg in record.args]
        reserved = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
        }
        # P0 Fix: Redact sensitive fields in extra context
        for key, value in record.__dict__.items():
            if key not in reserved:
                payload[key] = _to_serialisable(value, key)
        return json.dumps(payload, sort_keys=True)


def configure_logger(name: str, level: str = "INFO", structured: bool = False) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
