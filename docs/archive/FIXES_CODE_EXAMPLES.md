# Code Quality Fixes - Detailed Examples

## Fix #1: Edge Case Handler Parameter Mismatch (CRITICAL)

### Location
`aistock/fsd.py`, line 669, inside `evaluate_opportunity()` method

### Current Code (WRONG)
```python
# Line 667-675
if self.edge_case_handler:
    # Re-run edge case check to get adjustments
    edge_result = self.edge_case_handler.check_edge_cases(symbol, bars)  # MISSING PARAMS!
    if edge_result.is_edge_case and edge_result.action != 'block':
        adjusted_confidence += edge_result.confidence_adjustment
        edge_case_position_multiplier = edge_result.position_size_multiplier
        # Log edge case warning
        if edge_result.action == 'warn' or edge_result.action == 'reduce_size':
            safeguard_warnings.append(f'Edge case: {edge_result.reason}')
```

### Fixed Code
```python
# Line 667-675
if self.edge_case_handler:
    # Re-run edge case check to get adjustments
    # Note: Reuse timeframe_data from earlier in the method (lines 562-568)
    edge_result = self.edge_case_handler.check_edge_cases(
        symbol=symbol,
        bars=bars,
        timeframe_data=timeframe_data if self.timeframe_manager else None,
        current_time=datetime.now(timezone.utc),
    )
    if edge_result.is_edge_case and edge_result.action != 'block':
        adjusted_confidence += edge_result.confidence_adjustment
        edge_case_position_multiplier = edge_result.position_size_multiplier
        # Log edge case warning
        if edge_result.action == 'warn' or edge_result.action == 'reduce_size':
            safeguard_warnings.append(f'Edge case: {edge_result.reason}')
```

### Why This Matters
- The first call (line 570) passes all parameters including `timeframe_data` and `current_time`
- The second call (line 669) was missing these, potentially causing:
  - Loss of multi-timeframe edge case detection
  - Loss of time-based constraints (near-close trading restrictions)
  - Inconsistent edge case handling within the same opportunity evaluation

---

## Fix #2: Error Handling in Portfolio.update_position() (HIGH)

### Location
`aistock/portfolio.py`, lines 138-166, `update_position()` method

### Current Code (PROBLEMATIC)
```python
def update_position(self, symbol: str, quantity_delta: Decimal, price: Decimal, commission: Decimal = Decimal('0')):
    with self._lock:
        # CRITICAL FIX: Calculate cash delta but don't apply yet
        cash_delta = -(quantity_delta * price) - commission

        # Get or create position
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        pos = self.positions[symbol]

        # CRITICAL FIX: Try position update first (may raise exception)
        try:
            pos.realise(quantity_delta, price, datetime.now(timezone.utc))

            # Only update cash if position update succeeded
            self.cash += cash_delta

            # Remove position if closed
            if pos.quantity == 0:
                del self.positions[symbol]

        except Exception:
            # Position update failed - rollback by recreating clean position
            if symbol in self.positions:
                # Restore original position (before realise() was called)
                # Note: realise() modifies position in-place, so we can't fully rollback
                # Best we can do is not commit cash change and re-raise
                pass
            raise  # Re-raise exception to caller
```

### Fixed Code
```python
import logging

logger = logging.getLogger(__name__)

def update_position(self, symbol: str, quantity_delta: Decimal, price: Decimal, commission: Decimal = Decimal('0')):
    with self._lock:
        # CRITICAL FIX: Calculate cash delta but don't apply yet
        cash_delta = -(quantity_delta * price) - commission

        # Get or create position
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        pos = self.positions[symbol]

        # Backup original state before modification
        original_qty = pos.quantity
        original_price = pos.average_price
        original_timestamp = pos.last_update_utc

        # CRITICAL FIX: Try position update first (may raise exception)
        try:
            pos.realise(quantity_delta, price, datetime.now(timezone.utc))

            # Only update cash if position update succeeded
            self.cash += cash_delta

            # Remove position if closed
            if pos.quantity == 0:
                del self.positions[symbol]

        except Exception as e:
            # Restore original state if modification failed
            pos.quantity = original_qty
            pos.average_price = original_price
            pos.last_update_utc = original_timestamp
            
            # Log error with context
            logger.error(
                f'Failed to update position for {symbol}: {e}',
                exc_info=True,
                extra={
                    'symbol': symbol,
                    'quantity_delta': quantity_delta,
                    'price': price,
                    'commission': commission,
                }
            )
            # Re-raise exception to caller
            raise
```

### Why This Matters
- **Current code:** Has no actual recovery mechanism - just re-raises the error
- **Problem:** If `pos.realise()` fails partway through, the position is left in a corrupted state
- **Fix:** Backs up position state before modification, restores if exception occurs, and logs error with context
- **Benefit:** Prevents position corruption and provides visibility into failures

---

## Fix #3: Duplicate P&L Calculation (HIGH)

### Location
`aistock/engine.py` lines 101-110 (authoritative source) vs `aistock/portfolio.py` lines 207-227 (duplicate)

### Problem
Two independent implementations of P&L calculation that could diverge:

```python
# Engine.py - execute_trade() lines 101-110 (AUTHORITATIVE)
if (current_position > 0 and quantity < 0) or (current_position < 0 and quantity > 0):
    closed_qty = min(abs(quantity), abs(current_position))
    if current_position > 0:
        realised_pnl = closed_qty * (price - current_basis)
    else:
        realised_pnl = closed_qty * (current_basis - price)

# Portfolio.py - apply_fill() lines 207-227 (DUPLICATE!)
if existing_position and existing_position.quantity != 0:
    current_qty = existing_position.quantity
    avg_price = existing_position.average_price
    
    is_closing = (current_qty > 0 and quantity < 0) or (current_qty < 0 and quantity > 0)
    if is_closing:
        closing_qty = min(abs(quantity), abs(current_qty))
        if current_qty > 0:
            realized_pnl = (price - avg_price) * closing_qty
        else:
            realized_pnl = (avg_price - price) * closing_qty
```

### Solution: Remove from Portfolio

**Option 1: Delete duplicate calculation from Portfolio.apply_fill()**

```python
def apply_fill(
    self, symbol: str, quantity: Decimal, price: Decimal, commission: Decimal, timestamp: datetime
) -> Decimal:
    """Apply a fill to the portfolio and return realized P&L (thread-safe)."""
    
    with self._lock:
        # UPDATE: P&L is now calculated and passed by caller (TradingEngine)
        # This method no longer needs to calculate P&L
        
        # Update cash and position atomically
        cash_delta = -(quantity * price) - commission
        self.cash += cash_delta

        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        position = self.positions[symbol]
        position.realise(quantity, price, timestamp)
        if position.quantity == 0:
            del self.positions[symbol]

        return Decimal('0')  # P&L calculated by caller
```

**Option 2: Modified signature to accept P&L**

```python
def apply_fill(
    self, symbol: str, quantity: Decimal, price: Decimal, commission: Decimal, 
    timestamp: datetime, realized_pnl: Decimal | None = None
) -> Decimal:
    """
    Apply a fill to the portfolio and return realized P&L (thread-safe).
    
    If realized_pnl is provided (calculated by TradingEngine), use that.
    Otherwise, calculate it here for backward compatibility.
    """
    
    with self._lock:
        # Use provided P&L or calculate if not provided
        if realized_pnl is None:
            # Fallback calculation for backward compatibility
            existing_position = self.positions.get(symbol)
            realized_pnl = Decimal('0')
            
            if existing_position and existing_position.quantity != 0:
                current_qty = existing_position.quantity
                avg_price = existing_position.average_price
                
                is_closing = (current_qty > 0 and quantity < 0) or (current_qty < 0 and quantity > 0)
                if is_closing:
                    closing_qty = min(abs(quantity), abs(current_qty))
                    if current_qty > 0:
                        realized_pnl = (price - avg_price) * closing_qty
                    else:
                        realized_pnl = (avg_price - price) * closing_qty
        
        # Update cash and position atomically
        cash_delta = -(quantity * price) - commission
        self.cash += cash_delta

        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        position = self.positions[symbol]
        position.realise(quantity, price, timestamp)
        if position.quantity == 0:
            del self.positions[symbol]

        if realized_pnl:
            self.realised_pnl += realized_pnl

        return realized_pnl
```

### Why This Matters
- Per AGENTS.md: "TradingEngine is the authoritative source for P&L"
- Having two independent implementations violates DRY principle and creates divergence risk
- If one is fixed, the other isn't automatically updated
- Proper solution: TradingEngine calculates once, other modules use that value

---

## Fix #4: Float/Decimal Consistency in Warmup (MEDIUM)

### Location
`aistock/fsd.py`, lines 1128-1131, `warmup_from_historical()` method

### Current Code (PROBLEMATIC)
```python
# Lines 1116-1124 - Observation phase
for i in range(20, observe_upto, 5):
    window = bars[i - 20 : i + 1]
    state_dict: dict[str, Any] = self.extract_state(symbol, window, {symbol: window[-1].close})
    # ✓ Correct: Uses Decimal directly from Bar.close

# Lines 1126-1140 - Simulation phase
for i in range(max(20, observe_upto), n - 1, 2):
    window = bars[i - 20 : i + 1]
    current_price = float(window[-1].close)  # ✗ Unnecessary conversion
    next_bar_price = float(bars[i + 1].close)  # ✗ Unnecessary conversion

    # Line 1131 - Creates float→Decimal round-trip (precision loss!)
    state2: dict[str, Any] = self.extract_state(
        symbol, 
        window, 
        {symbol: Decimal(str(current_price))}  # ✗ Decimal(str(float)) loses precision
    )
```

### Fixed Code
```python
# Lines 1116-1124 - Observation phase (unchanged - already correct)
for i in range(20, observe_upto, 5):
    window = bars[i - 20 : i + 1]
    state_dict: dict[str, Any] = self.extract_state(symbol, window, {symbol: window[-1].close})
    if state_dict:
        state_hash = self.rl_agent.hash_state(state_dict)
        if state_hash not in self.rl_agent.q_values:
            self.rl_agent.q_values[state_hash] = dict.fromkeys(self.rl_agent.get_actions(), 0.0)
            states_discovered += 1

# Lines 1126-1140 - Simulation phase (FIXED)
for i in range(max(20, observe_upto), n - 1, 2):
    window = bars[i - 20 : i + 1]
    
    # ✓ FIXED: Keep as Decimal, don't convert to float and back
    current_price = window[-1].close  # Now Decimal, stays Decimal
    next_bar_price = bars[i + 1].close  # Now Decimal, stays Decimal
    
    # ✓ FIXED: Pass Decimal directly to extract_state
    state2: dict[str, Any] = self.extract_state(
        symbol, 
        window, 
        {symbol: current_price}  # Pass Decimal directly
    )
    
    if not state2:
        continue

    action_type = self.rl_agent.select_action(state2, training=True)
    confidence = self.rl_agent.get_confidence(state2, action_type)
    # ... rest of loop
```

### Why This Matters
- Float conversion loses precision: `Decimal('123.456789') → float(123.456789) → Decimal(str(...))` may differ
- Inconsistency between observation and simulation phases
- Warmup should match live trading precision

---

## Fix #5: Hardcoded Position Normalization (MEDIUM)

### Location
`aistock/fsd.py`, line 854, inside `handle_fill()` method

### Current Code (PROBLEMATIC)
```python
def handle_fill(self, symbol: str, timestamp: datetime, fill_price: float, 
                realised_pnl: float, signed_quantity: float, 
                previous_position: float, new_position: float):
    # ... lines 845-853
    
    # Get next state (would need current market data)
    # For now, use last state as approximation
    next_state = self.last_state.copy()
    next_state['position_pct'] = new_position / 1000.0  # ✗ Why 1000? Hardcoded!
```

### Fixed Code
```python
def handle_fill(self, symbol: str, timestamp: datetime, fill_price: float, 
                realised_pnl: float, signed_quantity: float, 
                previous_position: float, new_position: float):
    # ... lines 845-853
    
    # Get next state (would need current market data)
    # For now, use last state as approximation
    next_state = self.last_state.copy()
    
    # ✓ FIXED: Calculate position_pct correctly using equity (consistent with extract_state)
    # This matches line 499 in extract_state() which normalizes by equity
    try:
        # Get current equity from portfolio
        current_equity = float(self.portfolio.get_equity({
            symbol: Decimal(str(fill_price)) 
            # Add other symbols if available in last_prices
        }))
        
        if current_equity > 0:
            # Normalize by equity (not arbitrary 1000)
            position_pct = float(new_position) / current_equity
        else:
            position_pct = 0.0
    except (ValueError, KeyError):
        # Fallback: use normalized position without equity
        # Could also use new_position directly, or calculate from initial_cash
        position_pct = float(new_position) / float(self.portfolio.initial_cash)
    
    next_state['position_pct'] = position_pct
    
    # ... rest of method (lines 857+)
```

### Why This Matters
- Line 499 in `extract_state()` correctly normalizes by equity: `position_pct = position_value / equity`
- Line 854 uses arbitrary `1000.0`, which assumes max position is 1000 shares
- Inconsistency between training and live trading state representation
- RL agent expects consistent state features

---

## Fix #6: Unnecessary Defensive Check (LOW)

### Location
`aistock/engine.py`, lines 134-137, inside `execute_trade()` method

### Current Code
```python
# Line 124-140
elif abs(new_position) > abs(current_position):
    # Opening or adding to position - update weighted average basis
    if current_position == 0:
        # Opening new position
        self.cost_basis[symbol] = price
    else:
        # Adding to existing position - weighted average
        added_qty = abs(quantity)
        total_qty = abs(current_position) + added_qty

        # CRITICAL FIX: Guard against division by zero
        if total_qty == 0:  # ✗ This condition can never be True here
            # Edge case: both quantities are zero (shouldn't happen but defensive)
            self.cost_basis[symbol] = price
        else:
            weighted_basis = (abs(current_position) * current_basis + added_qty * price) / total_qty
            self.cost_basis[symbol] = weighted_basis
```

### Fixed Code
```python
# Line 124-140 (SIMPLIFIED)
elif abs(new_position) > abs(current_position):
    # Opening or adding to position - update weighted average basis
    if current_position == 0:
        # Opening new position
        self.cost_basis[symbol] = price
    else:
        # Adding to existing position - weighted average
        added_qty = abs(quantity)
        total_qty = abs(current_position) + added_qty
        
        # Note: total_qty cannot be zero here because:
        # - If we're in this branch, abs(new_position) > abs(current_position)
        # - new_position = current_position + quantity
        # - So quantity must be non-zero
        # - Therefore total_qty = abs(current_position) + abs(quantity) > 0
        weighted_basis = (abs(current_position) * current_basis + added_qty * price) / total_qty
        self.cost_basis[symbol] = weighted_basis
```

### Alternative: Add Comment Explaining the Check
```python
elif abs(new_position) > abs(current_position):
    # Opening or adding to position - update weighted average basis
    if current_position == 0:
        self.cost_basis[symbol] = price
    else:
        added_qty = abs(quantity)
        total_qty = abs(current_position) + added_qty

        # Defensive check: total_qty should always be > 0 since we're adding to position
        # This would only fail if both current_position and quantity are zero,
        # which contradicts the condition abs(new_position) > abs(current_position)
        # Kept for defensive programming in case logic changes
        if total_qty == 0:
            self.cost_basis[symbol] = price
        else:
            weighted_basis = (abs(current_position) * current_basis + added_qty * price) / total_qty
            self.cost_basis[symbol] = weighted_basis
```

### Why This Matters
- The condition is logically impossible, adding unnecessary code complexity
- Either remove it or document why it's defensive
- Code clarity matters for maintenance

---

## Fix #7: Missing Timestamp Validation (LOW)

### Location
`aistock/engine.py`, lines 16-30, `Trade` dataclass

### Current Code
```python
@dataclass
class Trade:
    """
    Record of an executed trade.
    """

    timestamp: datetime  # ✗ Could be naive or aware
    symbol: str
    quantity: Decimal
    price: Decimal
    realised_pnl: Decimal
    equity: Decimal
    order_id: str = ''
    strategy: str = 'FSD'
```

### Fixed Code
```python
from datetime import datetime, timezone

@dataclass
class Trade:
    """
    Record of an executed trade.
    
    CRITICAL: timestamp MUST be timezone-aware (UTC per AGENTS.md)
    """

    timestamp: datetime  # Must be timezone-aware
    symbol: str
    quantity: Decimal
    price: Decimal
    realised_pnl: Decimal
    equity: Decimal
    order_id: str = ''
    strategy: str = 'FSD'

    def __post_init__(self):
        """Validate that timestamp is timezone-aware."""
        if self.timestamp.tzinfo is None:
            raise ValueError(
                f'Trade timestamp must be timezone-aware (UTC), '
                f'got naive datetime: {self.timestamp}'
            )
        if self.timestamp.tzinfo != timezone.utc and str(self.timestamp.tzinfo) != 'UTC':
            # Could be timezone-aware but not UTC - warn or convert
            # For now, allow it but log a warning
            import logging
            logging.warning(
                f'Trade timestamp should be UTC, got {self.timestamp.tzinfo}'
            )
```

### Why This Matters
- Per AGENTS.md: "All datetime objects MUST be timezone-aware (UTC)"
- Naive timestamps cause `TypeError` in edge case handlers and safeguards
- Early validation prevents silent bugs later

---

## Summary of All Fixes

| Issue | File | Line | Type | Effort |
|-------|------|------|------|--------|
| 1. Edge case handler params | fsd.py | 669 | CRITICAL | 2 min |
| 2. Error handling | portfolio.py | 138-166 | HIGH | 15 min |
| 3. Duplicate P&L | engine.py + portfolio.py | 101-110, 207-227 | HIGH | 30 min |
| 4. Float/Decimal conversion | fsd.py | 1128-1131 | MEDIUM | 5 min |
| 5. Position normalization | fsd.py | 854 | MEDIUM | 5 min |
| 6. Defensive check | engine.py | 134-137 | LOW | 2 min |
| 7. Timestamp validation | engine.py | 22-30 | LOW | 5 min |

**Total Estimated Time: ~1 hour for all fixes**

