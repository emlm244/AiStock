# FSD (Full Self-Driving) Trading Bot - Complete Technical Guide

## 🎯 Overview

The FSD Trading Bot is an autonomous AI-powered trading system that uses **Reinforcement Learning (Q-Learning)** to make ALL trading decisions. It learns from every trade, adapts its strategy dynamically, and continuously improves its performance.

## ✅ Requirements

Install runtime dependencies before running the bot (NumPy + pandas are required):

```bash
pip install -r requirements.txt
```

---

## 🧠 Core Technology: Q-Learning Reinforcement Learning

### What is Q-Learning?

Q-Learning is a **model-free** reinforcement learning algorithm that learns the **quality (Q)** of actions in different states. The agent (our trading bot) learns an optimal **policy** (strategy) by maximizing cumulative rewards.

### The Q-Learning Formula

```
Q(s, a) ← Q(s, a) + α [r + γ · max Q(s', a') - Q(s, a)]
```

Where:
- **Q(s, a)**: Quality of action `a` in state `s`
- **α (alpha)**: Learning rate (0.001) - how fast we learn from new experiences
- **r**: Immediate reward from taking action `a`
- **γ (gamma)**: Discount factor (0.95) - how much we value future rewards
- **s'**: Next state after taking action `a`
- **max Q(s', a')**: Best possible future Q-value

### How FSD Uses Q-Learning

1. **State Extraction**: Convert market data into discretized features
2. **Action Selection**: Choose action using ε-greedy policy (explore vs exploit)
3. **Execute Trade**: Place order and observe outcome
4. **Reward Calculation**: Calculate reward based on P&L, risk, and costs
5. **Q-Value Update**: Update Q-table to learn from experience
6. **Repeat**: Continuously improve through iteration

---

## 📊 State Space (Market Features)

The FSD bot observes the market through a **state vector** containing:

### 1. Price Change Percentage
- **What**: Change in price from previous bar
- **Range**: -5% to +5% (discretized into 10 bins)
- **Purpose**: Capture momentum and direction

### 2. Volume Ratio
- **What**: Current volume / 20-bar average volume
- **Range**: 0.5x to 2.0x (discretized into 5 bins)
- **Purpose**: Detect unusual activity (breakouts, selloffs)

### 3. Trend
- **What**: SMA crossover signal
- **Values**: 'up', 'down', 'neutral'
- **Calculation**: 5-period SMA vs 10-period SMA
- **Purpose**: Identify overall market direction

### 4. Volatility
- **What**: Standard deviation of returns
- **Values**: 'low' (<1%), 'normal' (1-3%), 'high' (>3%)
- **Purpose**: Measure risk and uncertainty

### 5. Position Percentage
- **What**: Current position value / total equity
- **Range**: -50% to +50% (discretized into 5 bins)
- **Purpose**: Track exposure and manage risk

### State Hashing
States are **discretized** and **hashed** into a unique string to enable Q-table lookup:
```python
state_hash = md5(json.dumps(discretized_state))
```

**Total State Space**: ~10 × 5 × 3 × 3 × 5 = **~2,250 possible states**

---

## 🎮 Action Space

The FSD bot can take **5 actions**:

| Action | Description | Position Change |
|--------|-------------|-----------------|
| **BUY** | Open long position | +10% equity |
| **SELL** | Open short/exit long | -10% equity |
| **INCREASE_SIZE** | Add to position | +5% equity |
| **DECREASE_SIZE** | Reduce position | -5% equity |
| **HOLD** | Do nothing | 0 |

### Action Selection: ε-Greedy Policy

```python
if random() < exploration_rate:
    action = random_action()  # EXPLORE
else:
    action = max(Q_values[state])  # EXPLOIT
```

- **Exploration Rate**: Starts at 10%, decays to 1%
- **Purpose**: Balance learning new strategies vs using known good ones

---

## 💰 Reward Function

The reward function shapes how the AI learns:

```python
reward = PnL - risk_penalty - transaction_cost

risk_penalty = 0.1 × position_value
transaction_cost = 0.001 × position_value
```

### Reward Components

1. **P&L (Profit/Loss)**:
   - Positive for profitable trades
   - Negative for losing trades
   
2. **Risk Penalty** (0.1 × position_value):
   - Discourages holding large risky positions
   - Promotes capital preservation
   
3. **Transaction Cost** (0.001 × position_value):
   - Simulates slippage and commissions
   - Prevents overtrading

### Example Rewards
- **Profitable trade**: +$10 PnL - $0.50 risk - $0.05 cost = **+$9.45**
- **Losing trade**: -$5 PnL - $0.50 risk - $0.05 cost = **-$5.55**
- **No trade (HOLD)**: $0 PnL - $0 risk - $0 cost = **$0**

---

## 🚀 NEW ADVANCED FEATURES (Just Implemented)

### 1. **Session-Based Confidence Adaptation** ⏰

**Problem**: Sometimes the bot is too conservative and makes no trades early in a session.

**Solution**: If the session has no trades yet, the bot gradually lowers the confidence threshold after a grace period.

```python
elapsed_minutes = (now - session_start).total_seconds() / 60
if elapsed_minutes > confidence_decay_start_minutes:
    decay_minutes = elapsed_minutes - confidence_decay_start_minutes
    decay_factor = min(1.0, decay_minutes / 60.0)
    confidence_decay = decay_factor * max_confidence_decay
    effective_threshold = max(0.35, base_threshold - confidence_decay)
```

**Example**:
- Base threshold: 66%
- After 30 minutes (start of decay): Threshold stays at 66%
- After 60 minutes (30 minutes into decay): Threshold drops by up to 7.5% (if max decay is 15%)
- After 90 minutes (max decay reached): Threshold drops by up to 15%

### 2. **Parallel Multi-Stock Trading** 🔄

**Feature**: Trade multiple stocks simultaneously with concurrency limits.

**Configuration**:
```python
max_concurrent_positions = 5  # Hold up to 5 stocks at once
max_capital_per_position = 0.20  # Max 20% capital per position
```

**Benefits**:
- Diversification (don't put all eggs in one basket)
- More trading opportunities
- Reduced single-stock risk

**Implementation**: Before each trade, check:
```python
if num_open_positions >= max_concurrent_positions:
    # Only allow closing trades, no new positions
    return no_trade
```

### 3. **Per-Symbol Adaptive Confidence** 📈

**Feature**: Learn which symbols are profitable and trade them more confidently.

**How It Works**:
```python
for each symbol:
    track: {trades, wins, total_pnl, confidence_adj}
    
    if trades >= 3:  # Need at least 3 trades
        win_rate = wins / trades
        avg_pnl = total_pnl / trades
        
        if win_rate > 0.6 and avg_pnl > 0:
            confidence_adj += 0.02  # Boost confidence
        elif win_rate < 0.4 or avg_pnl < 0:
            confidence_adj -= 0.02  # Reduce confidence
```

**Example**:
- AAPL: 5 trades, 4 wins, +$50 total → Confidence boost: +6%
- TSLA: 5 trades, 1 win, -$30 total → Confidence penalty: -6%

**Result**: Bot trades AAPL more, TSLA less automatically!

### 4. **Persistent Per-Symbol Performance** 💾

**Feature**: Save and reload which symbols performed well.

**State Saved**:
```json
{
  "q_values": {...},
  "symbol_performance": {
    "AAPL": {"trades": 10, "wins": 7, "total_pnl": 45.30, "confidence_adj": 0.08},
    "MSFT": {"trades": 8, "wins": 6, "total_pnl": 32.10, "confidence_adj": 0.04},
    "TSLA": {"trades": 5, "wins": 1, "total_pnl": -12.50, "confidence_adj": -0.06}
  }
}
```

**Next Session**: Bot remembers AAPL is good, TSLA is risky!

---

## 🔧 Configuration Parameters

### Learning Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `learning_rate` | 0.001 | How fast Q-values update |
| `discount_factor` | 0.95 | How much we value future rewards |
| `exploration_rate` | 0.1 | % of random exploratory actions |
| `exploration_decay` | 0.995 | How fast exploration decreases |
| `min_exploration_rate` | 0.05 | Minimum exploration (always learn) |

### Trading Constraints
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_capital` | $10,000 | Maximum capital to deploy |
| `max_timeframe_seconds` | 300 | Max session timeframe (seconds) |
| `min_confidence_threshold` | 0.6 | Minimum confidence to trade (60%) |
| `max_loss_per_trade_pct` | 5.0 | Max loss per trade (% of position) |
| `max_concurrent_positions` | 5 | Max stocks held simultaneously |
| `max_capital_per_position` | 0.20 | Max 20% per stock |

### Advanced Features
| Parameter | Default | Description |
|-----------|---------|-------------|
| `enable_per_symbol_params` | True | Learn per-symbol confidence |
| `adaptive_confidence` | True | Adjust confidence dynamically |
| `enable_session_adaptation` | True | Enable session-based threshold decay |
| `max_confidence_decay` | 0.15 | Max threshold reduction over session |
| `confidence_decay_start_minutes` | 30 | Minutes before decay starts |
| `volatility_bias` | balanced | Prefer high/low/neutral volatility |

---

## 📈 Learning Process

### Phase 1: Startup (State Restore)
1. **Load saved learning state** (if present):
   - Q-values
   - Per-symbol performance stats
2. **Otherwise start fresh**: empty state and learning begins from real trades

There is **no automatic historical warmup** step. Recommended workflow: train in IBKR paper mode first.

### Phase 2: Paper/Live Trading (Online Learning)
1. **For each new bar**:
   - Extract state from market data
   - Select action using ε-greedy policy
   - Check confidence threshold (adaptive per symbol)
   - Check parallel trading limits
2. **If trade approved**:
   - Submit order to broker
   - Wait for fill
3. **On fill**:
   - Calculate reward
   - Update Q-values
   - Update per-symbol performance
   - Save state to disk
4. **Repeat**: Bot continuously learns and adapts

### Phase 3: Session End
1. **Save state**:
   - Q-values (learned patterns)
   - Per-symbol performance
   - Statistics (total trades, wins, P&L)
2. **Next session**: Reload and continue learning

---

## ❓ Why No Trades in Your Test?

Your bot made **0 trades** because:

### Root Causes
1. **High confidence threshold**: Conservative presets can be very selective
2. **Not enough bars yet**: The engine needs a minimum bar history before it can extract features and evaluate trades
3. **Fresh state**: If no saved learning state is available, the agent starts neutral and learns only from real fills
4. **No historical warmup**: The system does not pre-train on startup; learning happens during paper/live sessions

### Solution: Train in IBKR Paper Mode First
- Run paper mode for multiple sessions to accumulate trade outcomes and update learning state
- If you consistently see 0 trades, reduce the confidence threshold or choose a less conservative preset
- Learning state persists between sessions, so performance can improve over time

---

## 🌐 IBKR Integration & Multi-Timeframe Trading

### Current IBKR Implementation
- **Supported**: Real-time bars via `reqRealTimeBars()` API
- **Interval**: 5-second bars (IBKR limitation)
- **Symbols**: Unlimited (one subscription per symbol)

### Multi-Timeframe Trading (Feasibility)

#### ✅ What IBKR Supports:
1. **Historical Data**: Multiple timeframes (1min, 5min, 15min, 1hour, 1day)
2. **Real-time Bars**: 5-second bars only
3. **Market Data**: Tick-by-tick (can aggregate into any timeframe)

#### 🔧 How to Implement Multi-Timeframe:
```python
# Subscribe to 5-second bars from IBKR
broker.reqRealTimeBars(symbol, callback)

# Aggregate into multiple timeframes
aggregator = TimeframeAggregator()
aggregator.add_timeframes(['30s', '1min', '5min'])

def on_5s_bar(bar):
    # Aggregate into higher timeframes
    bars_30s = aggregator.aggregate(bar, '30s')
    bars_1min = aggregator.aggregate(bar, '1min')
    bars_5min = aggregator.aggregate(bar, '5min')
    
    # FSD evaluates ALL timeframes
    decision_30s = fsd.evaluate_opportunity(symbol, bars_30s, ...)
    decision_1min = fsd.evaluate_opportunity(symbol, bars_1min, ...)
    decision_5min = fsd.evaluate_opportunity(symbol, bars_5min, ...)
    
    # Combine signals (e.g., vote or weight by confidence)
    final_decision = combine_signals([decision_30s, decision_1min, decision_5min])
```

#### 📊 Cross-Timeframe Analysis Example:
- **30s bars**: Show immediate momentum (scalping signals)
- **1min bars**: Filter out noise
- **5min bars**: Confirm trend direction

**Strategy**: Only trade if ALL timeframes agree (higher confidence)

---

## 🔮 Roadmap: Future Enhancements

### 1. **Multi-Timeframe State Encoding**
Add timeframe to state space:
```python
state = {
    'symbol': 'AAPL',
    'timeframe': '1min',  # NEW
    'price_change_pct': 0.02,
    ...
}
```

### 2. **Deep Q-Network (DQN)**
Replace Q-table with neural network:
- **Benefit**: Handle continuous states (no discretization)
- **Benefit**: Generalize to unseen states
- **Trade-off**: More complex, slower training

### 3. **Portfolio-Level RL**
Current: Trade each symbol independently
Future: Optimize entire portfolio (correlations, diversification)

### 4. **Multi-Agent RL**
Multiple AI agents with different strategies:
- Agent 1: Scalper (30s-1min)
- Agent 2: Day trader (5min-15min)
- Agent 3: Swing trader (1hour-1day)
- Meta-agent: Decides which agent to trust

---

## 🎓 Answers to Your Questions

### Q1: "Did the bot do good?"
**A**: If it made 0 trades, it was likely too selective or didn’t have enough bar history yet. Train in paper mode first and let it run long enough to generate fills.

### Q2: "Should it use historical warmup to pre-train?"
**A**: No. ✅ AIStock does not perform an automatic historical warmup step. Train in IBKR paper mode first.

### Q3: "Can FSD choose any stock dynamically?"
**A**: YES! ✅ FSD scans ALL provided symbols:
- Evaluates each bar for each symbol
- Chooses best opportunities based on confidence
- Now with per-symbol adaptive confidence

### Q4: "Can it do parallel trades?"
**A**: YES! ✅ Just implemented:
- `max_concurrent_positions = 5` (configurable)
- `max_capital_per_position = 0.20` (20% max)
- Checks limits before each trade

### Q5: "Can it trade multiple timeframes?"
**A**: Not yet, but FEASIBLE:
- IBKR provides 5-second bars
- Can aggregate into any timeframe (30s, 1min, 5min, etc.)
- Implementation: 1-2 days of work

### Q6: "Can it adapt parameters per stock?"
**A**: YES! ✅ Just implemented:
- Tracks performance per symbol
- Adjusts confidence boost/penalty per symbol
- Saves to disk for next session

### Q7: "Does it save learning for next session?"
**A**: YES! ✅
- Saves Q-values
- Saves per-symbol performance
- Loads on next startup

---

## 🏁 Next Steps

1. **Run IBKR paper mode** for multiple sessions to build learning state from real fills
2. **Monitor results**:
   - Trades placed and filled
   - Per-symbol performance adapting over time
3. **Review state file** after a session:
   ```bash
   cat state/fsd_state.json
   ```
   - Check `symbol_performance` for per-symbol stats

---

## 📚 Further Reading

- [Sutton & Barto - Reinforcement Learning](http://incompleteideas.net/book/the-book.html)
- [Q-Learning Tutorial](https://www.youtube.com/watch?v=__t2XRxXGxI)
- [Interactive Brokers API Docs](https://interactivebrokers.github.io/tws-api/)

---

**Built with ❤️ by AIStock Team**
