# ⚠️ DEPRECATED: session.py

**This file is deprecated and will be removed in a future version.**

## Use the New Modular Architecture Instead

### Old Way (Deprecated)
```python
from aistock.session import LiveTradingSession

session = LiveTradingSession(
    config,
    fsd_config=fsd_config,
    checkpoint_dir='state'
)
session.start()
```

### New Way (Recommended)
```python
from aistock.factories import SessionFactory

factory = SessionFactory(config, fsd_config)
session = factory.create_trading_session(
    symbols=['AAPL', 'MSFT'],
    checkpoint_dir='state'
)
session.start()
```

## Benefits of New Architecture
- ✅ Modular components
- ✅ Easy to test
- ✅ Dependency injection
- ✅ Clean interfaces
- ✅ Service layer

## Migration Guide

See `MODULARIZATION_COMPLETE.md` for the complete migration guide.

---

**Status**: Currently kept for backward compatibility.
**Timeline**: Will be removed in v3.0.0
