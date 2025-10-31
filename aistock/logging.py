"""
Structured logging configuration.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON, capturing custom "extra" fields.

        Python's logging module attaches keys in the "extra" dict directly as
        attributes on the LogRecord. We detect non-standard attributes and
        include them in the structured payload.
        """
        log_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # Merge any custom attributes that were provided via `extra=`
        try:
            base_keys = set(logging.LogRecord('', 0, '', 0, '', (), None).__dict__.keys())
            for key, value in record.__dict__.items():
                if key not in base_keys and key not in {'args', 'message'}:
                    log_data[key] = value
        except Exception:
            # Be resilient – logging should never raise
            pass

        # Add exception info if present
        if record.exc_info:
            try:
                log_data['exception'] = self.formatException(record.exc_info)
            except Exception:
                log_data['exception'] = 'Exception formatting failed'

        return json.dumps(log_data, default=str)


def configure_logger(name: str, level: str = 'INFO', structured: bool = False) -> logging.Logger:
    """
    Configure a logger instance.

    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        structured: Use JSON structured logging

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    logger.handlers = []

    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(getattr(logging, level.upper()))

    # Set formatter
    if structured:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
