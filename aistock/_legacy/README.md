# _legacy/ Directory

**Purpose**: Contains old monolithic code that has been replaced by modular architecture.

## Files Here

### session.py (DEPRECATED - DO NOT USE)
- **Status**: Fully replaced by `session/coordinator.py` + `session/bar_processor.py` + other session components
- **Reason for keeping**: Reference only, in case needed for comparison
- **Use instead**: `from aistock.factories import SessionFactory`

**Example** (OLD - Don't use):
```python
from aistock.session import LiveTradingSession  # ❌ DON'T USE
session = LiveTradingSession(config, fsd_config)
```

**Example** (NEW - Use this):
```python
from aistock.factories import SessionFactory  # ✅ USE THIS
factory = SessionFactory(config, fsd_config)
coordinator = factory.create_trading_session(symbols=['AAPL'])
```

---

## Why Keep These Files?

1. **Reference**: Compare old vs new implementation
2. **Safety**: Can restore if something breaks
3. **History**: Understand evolution of the codebase

## Can These Be Deleted?

Yes, after:
1. All tests pass with new architecture
2. Production trading runs successfully for 1+ week
3. Team confirms no need for old code

Then you can safely delete this entire `_legacy/` directory.

---

**Recommendation**: Delete _legacy/ directory in v3.0.0 (after 2-4 weeks of successful production use)
