# Option F: Broker Reconciliation (Follow-Up Task)

**Priority**: HIGH
**Estimated Effort**: ~6 hours
**Status**: TODO
**Created**: 2025-11-03

## Background

**Current State (Option D - Time-Boxed Idempotency)**:
- ✅ Prevents same-session duplicates
- ✅ Allows safe restarts after 5-minute window
- ⚠️ Still has small duplicate window (crash after broker.submit, before mark_submitted)
- ⚠️ No broker-side reconciliation on startup

**Desired State (Option F - Broker Reconciliation)**:
- ✅ Zero duplicate window (broker is source of truth)
- ✅ Self-healing on restart (sync from broker state)
- ✅ Production-grade idempotency

---

## Implementation Plan

### Phase 1: IBKR Adapter Changes (~2 hours)

**File**: `aistock/brokers/ibkr.py`

1. **Forward `client_order_id` to IBKR**:
   ```python
   def submit(self, order: Order) -> str:
       ib_order = IBOrder()
       ib_order.orderRef = order.client_order_id  # NEW: Forward our ID
       # ... existing code
   ```

2. **Capture broker mappings in callbacks**:
   ```python
   def _handle_order_status(self, trade):
       orderRef = trade.order.orderRef
       permId = trade.order.permId
       if orderRef:
           self._orderref_to_permid[orderRef] = permId
           # Persist mapping to disk (atomic write)
   ```

3. **Implement reconciliation query**:
   ```python
   def get_recent_orders(self, last_24h: bool = True) -> List[BrokerOrder]:
       """Query recent orders from IBKR for reconciliation."""
       orders = []
       # Use reqCompletedOrders + reqOpenOrders
       # Return list of {orderRef, permId, status}
       return orders
   ```

**Files to modify**:
- `aistock/brokers/ibkr.py`
- `aistock/brokers/base.py` (add `get_recent_orders()` to interface)

---

### Phase 2: PaperBroker Changes (~30 min)

**File**: `aistock/brokers/paper.py`

1. **Track client_order_id mappings**:
   ```python
   self._client_to_broker_id: Dict[str, str] = {}

   def submit(self, order: Order) -> str:
       broker_id = self._generate_order_id()
       self._client_to_broker_id[order.client_order_id] = broker_id
       return broker_id
   ```

2. **Implement get_recent_orders()**:
   ```python
   def get_recent_orders(self, last_24h: bool = True) -> List[BrokerOrder]:
       # Return in-memory order history
       # Filter by timestamp if last_24h=True
   ```

**Files to modify**:
- `aistock/brokers/paper.py`

---

### Phase 3: Startup Reconciliation (~1 hour)

**File**: `aistock/session/coordinator.py` or new `aistock/session/reconciliation.py`

1. **Add reconciliation on startup**:
   ```python
   def _reconcile_idempotency_on_startup(self):
       \"\"\"Sync idempotency tracker from broker state.\"\"\"
       broker_orders = self.broker.get_recent_orders(last_24h=True)

       for order in broker_orders:
           if order.orderRef:  # Has our client_order_id
               self.idempotency.mark_submitted(order.orderRef)

       self.logger.info(f'Reconciled {len(broker_orders)} orders from broker')
   ```

2. **Call from coordinator __init__()**:
   ```python
   def __init__(self, ...):
       # ... existing init
       self._reconcile_idempotency_on_startup()
   ```

**Files to modify**:
- `aistock/session/coordinator.py`

---

### Phase 4: Testing (~2 hours)

**New test file**: `tests/test_broker_reconciliation.py`

Test scenarios:
1. ✅ IBKR adapter forwards `orderRef` correctly
2. ✅ PaperBroker tracks client-to-broker ID mapping
3. ✅ Startup reconciliation hydrates idempotency tracker
4. ✅ Crash after `broker.submit()` + restart → no duplicate (reconciled from broker)
5. ✅ Reconciliation handles missing `orderRef` gracefully
6. ✅ Reconciliation filters to last 24h correctly

**Integration test**:
```python
def test_crash_recovery_no_duplicate():
    # Submit order
    broker.submit(order)
    # Simulate crash (don't call mark_submitted)
    # Restart coordinator (new instance)
    # Reconciliation should detect order in broker
    # Retry same order → blocked as duplicate
```

---

## Migration Path

**Backward Compatibility**:
- New `orderRef` field is optional (IBKR ignores if empty)
- Old orders (pre-Option F) won't have `orderRef` → reconciliation skips them
- Gradual rollout: works alongside Option D

**Deployment**:
1. Deploy broker adapter changes (no behavior change yet)
2. Deploy reconciliation logic
3. Monitor logs for reconciliation metrics
4. Validate zero duplicates over 1 week
5. Document as production-ready

---

## Acceptance Criteria

- [ ] IBKR adapter forwards `client_order_id` via `orderRef`
- [ ] IBKR adapter captures `orderRef → permId` mapping
- [ ] Paper broker tracks client-to-broker ID mapping
- [ ] Both brokers implement `get_recent_orders()` interface
- [ ] Startup reconciliation hydrates idempotency tracker
- [ ] Regression test: crash after submit → restart → no duplicate
- [ ] All existing tests continue to pass
- [ ] Documentation updated (CLAUDE.md + AGENTS.md)

---

## Risk Assessment

**Risks**:
- ⚠️ IBKR `orderRef` length limits (need to verify max length)
- ⚠️ Reconciliation query performance (TWS/Gateway load)
- ⚠️ Clock skew between system and broker (24h window edge cases)

**Mitigations**:
- Validate `orderRef` max length in docs/testing
- Cache reconciliation results (only query on startup)
- Add configurable reconciliation window (default 24h)

---

## References

- **IBKR API Docs**: https://interactivebrokers.github.io/tws-api/classIBApi_1_1Order.html
- **Current Implementation**: Option D (time-boxed idempotency)
- **Discussion**: Code review feedback (2025-11-03)

---

## Next Steps

1. Schedule 6-hour engineering block
2. Create feature branch: `feature/option-f-broker-reconciliation`
3. Implement Phase 1-4 sequentially
4. PR review + deployment plan
5. Monitor production metrics for 1 week
