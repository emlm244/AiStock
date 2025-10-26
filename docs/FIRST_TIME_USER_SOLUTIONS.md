# First-Time User Solutions

## 🚨 Problems Identified

### Problem 1: No Historical Data for ML Training
**Scenario:** New user opens AIStock for first time
- No `data/` folder exists
- No historical bars
- ML model can't be trained (needs historical data)
- FSD can learn on-the-fly, but ML model can't

### Problem 2: FSD Needs Historical Context
**Scenario:** FSD should learn from past BEFORE trading
- Download 10 days of historical data
- Process historical bars to understand patterns
- THEN start live trading

### Problem 3: Urgency Mode - "I Need Money NOW"
**Scenario:** Aggressive user needs quick gains
- User: "I need money in 1 hour!"
- Current: FSD might not trade if confidence is low
- Needed: Hard deadline to FORCE a trade if time is running out

---

## ✅ Solutions

### Solution 1: Auto-Download Historical Data on First Run

#### Approach: Automatic Setup Wizard

**When user first launches Simple Mode:**
```
┌─────────────────────────────────────────────┐
│  🎯 Welcome to AIStock Robot!              │
│                                             │
│  This is your first time running FSD.      │
│  Let me prepare everything for you...      │
│                                             │
│  📊 Downloading 10 days of historical data │
│     for top stocks (AAPL, MSFT, GOOGL...)  │
│                                             │
│  ⏱️ This will take about 30 seconds...     │
│                                             │
│     [████████░░░░░░░░] 60%                 │
│                                             │
└─────────────────────────────────────────────┘
```

**What it downloads:**
- 10 days of 1-minute bars for top 5 liquid stocks
- Saves to `data/historical/`
- Trains a default ML model automatically
- Saves to `models/ml_model.json`

**Implementation Options:**

#### Option A: Use `yfinance` (Simple, Free)
```python
import yfinance as yf

def download_historical_data(symbols, days=10):
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        # Download last 10 days, 1-minute intervals
        df = ticker.history(period="10d", interval="1m")
        # Save to data/historical/SYMBOL.csv
```

#### Option B: Use IBKR API (Best for live trading)
```python
def download_from_ibkr(broker, symbol, days=10):
    end_time = datetime.now()
    duration = f"{days} D"
    bar_size = "1 min"

    bars = broker.request_historical_bars(
        symbol, end_time, duration, bar_size
    )
    # Save to data/historical/SYMBOL.csv
```

#### Option C: Ship Pre-Trained Model (Fastest)
- Include a pre-trained ML model in the repo
- Trained on SPY, QQQ, AAPL, MSFT, GOOGL
- Users can use it immediately
- Optional: Re-train with their own data later

**Recommended: Hybrid Approach**
1. Ship with pre-trained model (immediate use)
2. Auto-download 10 days of data in background
3. Auto-train a personalized model
4. Switch to personalized model when ready

---

### Solution 2: FSD Historical Warmup Period

#### Current FSD Behavior:
```python
# session.py
self.session = LiveTradingSession(config, mode="fsd", fsd_config=fsd_config)
self.session.start()  # Immediately starts trading!
```

#### Enhanced FSD Behavior:
```python
# 1. Download historical data
bars = download_historical_data(symbols, days=10)

# 2. FSD learns from historical data FIRST
fsd_engine.warmup_from_historical(bars)

# 3. THEN start live trading
self.session.start()
```

#### Warmup Process:
```
FSD Warmup Process (10 days of historical data):

Day 1-5: Observation Phase
  → FSD processes 5 days of bars
  → Builds confidence scores for each bar
  → NO trades executed (just observing)
  → Updates internal state features

Day 6-10: Simulated Trading Phase
  → FSD simulates trades based on learned patterns
  → Calculates hypothetical PnL
  → Updates Q-values based on simulated outcomes
  → Experience buffer fills up

After Warmup:
  → FSD has learned from 10 days of patterns
  → Q-values are initialized (not zero)
  → Confidence scoring is calibrated
  → NOW ready for live trading!
```

**Benefits:**
- FSD doesn't trade "blind" on first session
- Better initial decisions
- Faster convergence to profitable strategy
- Less "learning curve" losses

---

### Solution 3: Trade Deadline - Hard Limit Feature

#### The Scenario:
```
Aggressive User: "I have $200 and need to make money in 1 hour!"

Current FSD Behavior:
  - Evaluates every bar
  - Only trades if confidence >= threshold (e.g., 45%)
  - If no good opportunities → NO TRADES
  - User gets $0 profit after 1 hour 😞

Desired FSD Behavior:
  - Evaluates every bar
  - Trades normally if confidence is good
  - BUT if approaching deadline with NO trades yet:
    → Gets "stressed" (lowers threshold)
    → MUST make SOME trade before deadline
  - User gets SOME profit/loss (not $0) ✅
```

#### Implementation:

**New Config Parameter:**
```python
@dataclass(frozen=True)
class FSDConfig:
    # ... existing fields ...

    # Trade Deadline (optional)
    trade_deadline_minutes: int | None = None  # e.g., 60 = must trade within 1 hour
    trade_deadline_stress_enabled: bool = True  # Enable urgency mode
```

**How It Works:**
```python
class FSDEngine:
    def evaluate_opportunity(self, symbol, bars, last_prices):
        # Calculate normal confidence
        confidence = self.confidence_scorer.score(symbol, bars, portfolio)
        threshold = self.config.initial_confidence_threshold  # e.g., 0.45

        # Check if we're approaching trade deadline
        if self.config.trade_deadline_minutes is not None:
            time_since_session_start = (datetime.now() - self.session_start).total_seconds() / 60
            time_remaining = self.config.trade_deadline_minutes - time_since_session_start

            # If approaching deadline AND no trades made yet
            if time_remaining > 0 and len(self.session_trades) == 0:
                # Calculate "stress factor" (increases as deadline approaches)
                stress_factor = 1.0 - (time_remaining / self.config.trade_deadline_minutes)

                # Lower threshold based on stress
                # e.g., threshold = 0.45 * (1 - 0.8) = 0.09 (very low!)
                adjusted_threshold = threshold * (1 - stress_factor * 0.8)

                self.logger.info(
                    "trade_deadline_stress",
                    extra={
                        "time_remaining": time_remaining,
                        "stress_factor": stress_factor,
                        "original_threshold": threshold,
                        "adjusted_threshold": adjusted_threshold,
                        "trades_made": len(self.session_trades)
                    }
                )

                threshold = adjusted_threshold

        # Use adjusted threshold
        if confidence >= threshold:
            # Trade!
```

**Stress Levels:**
```
Time Remaining | Stress Factor | Threshold Adjustment | Effective Threshold
---------------|---------------|---------------------|--------------------
60 min (100%)  | 0.0           | 0%                  | 0.45 (normal)
30 min (50%)   | 0.5           | 40%                 | 0.27 (lower)
10 min (17%)   | 0.83          | 66%                 | 0.15 (very low)
1 min (1.6%)   | 0.98          | 78%                 | 0.10 (desperate!)
0 min (0%)     | 1.0           | 80%                 | 0.09 (MUST TRADE!)
```

**User Experience:**
```
User sets: Trade Deadline = 60 minutes

Minute 0-40: FSD trades normally (threshold = 45%)
  → If good opportunity → TRADE
  → If bad opportunity → SKIP

Minute 40-50: FSD gets "concerned" (threshold drops to 27%)
  → More likely to trade
  → Still somewhat selective

Minute 50-59: FSD gets "stressed" (threshold drops to 15%)
  → Very likely to trade
  → Takes marginal opportunities

Minute 59-60: FSD gets "desperate" (threshold drops to 9%)
  → Will trade almost anything
  → MUST make SOME trade before deadline!

After deadline: Back to normal (threshold = 45%)
  → Deadline resets for next trade cycle
```

---

## 🎯 Updated Simple GUI Flow

### New Question 5: Trade Deadline (Optional)

```
┌─────────────────────────────────────────────────────────┐
│  ⏰ Do you need money within a specific time?           │
│                                                          │
│  ⚪ No rush - Trade when opportunities are good         │
│     (FSD trades normally, no deadline pressure)         │
│                                                          │
│  ⚪ Yes - I need to make a trade within:                │
│                                                          │
│     [____60____] minutes                                │
│                                                          │
│     💡 FSD will try to trade normally, but if no       │
│        good opportunities appear, it will become        │
│        more aggressive as the deadline approaches.      │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Examples:**

### Conservative + 60 min deadline:
```
Normal threshold: 70%
Deadline stress: Enabled

Result:
  - Minute 0-40: Trades only if 70%+ confident
  - Minute 40-50: Trades if 42%+ confident
  - Minute 50-60: Trades if 20%+ confident
  - Minute 60: MUST trade (accepts 14%+ confidence)
```

### Aggressive + 30 min deadline:
```
Normal threshold: 45%
Deadline stress: Enabled

Result:
  - Minute 0-15: Trades only if 45%+ confident
  - Minute 15-25: Trades if 20%+ confident
  - Minute 25-30: Trades if 10%+ confident
  - Minute 30: MUST trade (accepts 9%+ confidence)
```

### Moderate + No deadline:
```
Normal threshold: 60%
Deadline stress: Disabled

Result:
  - Trades only if 60%+ confident
  - Never lowers threshold
  - May not trade if no opportunities
  - User: "That's OK, I'm patient"
```

---

## 📊 Complete First-Time User Flow

```
User launches AIStock for first time
        │
        ▼
┌─────────────────────────────────┐
│  Setup Wizard Appears           │
│                                 │
│  "This is your first time!      │
│   Let me set everything up..."  │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Auto-Download Historical Data  │
│  - AAPL, MSFT, GOOGL, etc.      │
│  - Last 10 days, 1-min bars     │
│  - Saves to data/historical/    │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Auto-Train ML Model            │
│  - Extract features from data   │
│  - Train logistic regression    │
│  - Save to models/ml_model.json │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Setup Complete!                │
│  "Ready to trade!"              │
└────────────┬────────────────────┘
             │
             ▼
   Simple GUI appears with 5 questions:
   1. How much money?
   2. Risk level?
   3. Investment goal?
   4. Max loss per trade?
   5. Trade deadline? (NEW!)
        │
        ▼
   User clicks START
        │
        ▼
┌─────────────────────────────────┐
│  FSD Warmup Phase               │
│  - Process 10 days historical   │
│  - Simulate trades              │
│  - Update Q-values              │
│  - Build experience buffer      │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  FSD Live Trading Begins        │
│  - Uses trained ML model        │
│  - Q-values pre-initialized     │
│  - Trade deadline tracking      │
│  - Smart, informed decisions!   │
└─────────────────────────────────┘
```

---

## 🛠️ Implementation Plan

### Phase 1: Historical Data Auto-Download
1. Create `aistock/setup/first_time_wizard.py`
2. Detect first-time user (check if `data/historical/` exists)
3. Download 10 days of data using `yfinance`
4. Save to CSV format

### Phase 2: Auto-Train ML Model
1. Use downloaded data
2. Call ML pipeline automatically
3. Save model to `models/ml_model.json`
4. Show progress to user

### Phase 3: FSD Warmup Period
1. Add `warmup_from_historical()` method to FSDEngine
2. Process historical bars without executing trades
3. Update Q-values based on simulated outcomes
4. Initialize experience buffer

### Phase 4: Trade Deadline Feature
1. Add `trade_deadline_minutes` to FSDConfig
2. Add stress factor calculation to `evaluate_opportunity()`
3. Lower threshold as deadline approaches
4. Force trade if deadline reached with no trades

### Phase 5: Update Simple GUI
1. Add Question 5: Trade Deadline
2. Pass deadline to FSDConfig
3. Show deadline countdown in dashboard
4. Log stress level in activity feed

---

## 📚 Benefits Summary

### For First-Time Users:
- ✅ No manual setup required
- ✅ Automatic data download
- ✅ Pre-trained ML model ready to go
- ✅ FSD learns from history before trading
- ✅ Better first trades
- ✅ Less "learning curve" losses

### For Aggressive Users:
- ✅ "I need money NOW" mode available
- ✅ Trade deadline ensures SOME action
- ✅ FSD adapts to urgency
- ✅ No more "sat there for an hour and made $0"

### For All Users:
- ✅ ML model always available (even first run)
- ✅ FSD has historical context
- ✅ Smarter, more informed decisions
- ✅ Better user experience

---

**Next:** Implement these features! 🚀
