# ⚠️ DEPRECATED: fsd.py

**This file is deprecated and will be removed in a future version.**

## Use the New Modular FSD Components Instead

The old monolithic `FSDEngine` has been decomposed into focused components.

### Old Way (Deprecated)
```python
from aistock.fsd import FSDEngine

engine = FSDEngine(
    config,
    portfolio,
    timeframe_manager,
    pattern_detector
)
```

### New Way (Recommended)
```python
# Use via SessionFactory (recommended)
from aistock.factories import SessionFactory

factory = SessionFactory(config, fsd_config)
session = factory.create_trading_session()
# Access via session.decision_engine

# Or use components directly (advanced)
from aistock.fsd_components import (
    MarketStateExtractor,
    DecisionMaker,
    LearningCoordinator,
    FSDStatePersistence,
    WarmupSimulator
)
```

## New FSD Components

Located in `aistock/fsd_components/`:

1. **MarketStateExtractor** - Feature extraction from market data
2. **DecisionMaker** - Trading decisions with RL agent
3. **LearningCoordinator** - Q-learning updates
4. **FSDStatePersistence** - Save/load learned state
5. **WarmupSimulator** - Historical data pre-training

## Migration Guide

See `MODULARIZATION_COMPLETE.md` for the complete migration guide.

---

**Status**: Currently kept for backward compatibility (tests use it).
**Timeline**: Will be removed in v3.0.0
