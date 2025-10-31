"""Deprecated monolithic components - kept for backward compatibility.

DEPRECATED: These imports are kept for backward compatibility only.
Please use the new modular architecture instead:

OLD (deprecated):
    from aistock.session import LiveTradingSession
    session = LiveTradingSession(config, fsd_config)

NEW (recommended):
    from aistock.factories import SessionFactory
    factory = SessionFactory(config, fsd_config)
    session = factory.create_trading_session()

The old monolithic files (session.py, fsd.py) are still present but
will be removed in a future version. Please migrate to the new architecture.
"""

import warnings


def warn_deprecated_import(old_module: str, new_module: str) -> None:
    """Warn about deprecated imports."""
    warnings.warn(
        f"Importing from '{old_module}' is deprecated. "
        f"Please use '{new_module}' instead. "
        "See MODULARIZATION_COMPLETE.md for migration guide.",
        DeprecationWarning,
        stacklevel=3,
    )
