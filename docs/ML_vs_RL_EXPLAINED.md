# ML vs RL in AIStock Robot - EXPLAINED

## 🤔 The Confusion

**Question:** "Does FSD have access to the ML? Is the RL (ML Module) the FSD? Or does the FSD integrate the ML?"

**Answer:** There are TWO DIFFERENT "AI" systems in AIStock, and they are NOT the same thing!

---

## 🧠 The Two AI Systems

### 1. **Traditional ML Model** (Supervised Learning)

**What it is:**
- Logistic Regression classifier
- Trained in the ML Lab tab
- Learns from historical data patterns
- Predicts: "Will price go up or down?"

**How it's trained:**
```python
# You provide historical data
# It learns patterns: "When X happens, price usually goes up"
# Outputs: Probability of price increase (0.0 to 1.0)
```

**Where it's stored:**
- `models/ml_model.json`

**How to train it:**
1. Go to ML Lab tab in Advanced Mode
2. Select data folder and symbols
3. Configure lookback/horizon/epochs
4. Click "Train Model"

**Current usage:**
- ✅ BOT mode uses it
- ❌ FSD mode does NOT use it (yet!)
- ❌ Headless mode does not use it

---

### 2. **Reinforcement Learning (Q-Learning)** - FSD's Brain

**What it is:**
- Q-Learning agent
- Built into FSD mode
- Learns from trade outcomes
- Decides: "Should I trade this stock? How much?"

**How it learns:**
```python
# FSD makes a trade
# Trade completes with PnL (profit or loss)
# FSD updates its brain:
#   - Positive PnL = "That was good, do it again!"
#   - Negative PnL = "That was bad, avoid next time!"
```

**Where it's stored:**
- `state/fsd/simple_gui_*.json` (Q-values)
- `state/fsd/experience_buffer.json` (past experiences)
- `state/fsd/performance_history.json` (trade history)

**How it trains:**
- Automatically! Every trade teaches it something
- Persistent learning across sessions
- No manual training required

**Current usage:**
- ✅ FSD mode ONLY
- ❌ BOT mode does not use it
- ❌ Headless mode does not use it

---

## 🔍 Key Differences

| Feature | Traditional ML | Reinforcement Learning (FSD) |
|---------|---------------|------------------------------|
| **Type** | Supervised Learning | Reinforcement Learning |
| **Training** | Manual (ML Lab) | Automatic (every trade) |
| **Input** | Historical bars | Market state + past outcomes |
| **Output** | Buy/Sell probability | Trade decision + size |
| **Learning From** | Historical patterns | Real trade results (PnL) |
| **Storage** | `models/*.json` | `state/fsd/*.json` |
| **Used By** | BOT mode | FSD mode |
| **Human Analogy** | "Study history books" | "Learn by doing" |

---

## 🎯 The Current Problem

### FSD's ConfidenceScorer Claims to Use ML... But Doesn't!

```python
# fsd.py:244
def _score_ml_prediction(bars: list[Bar]) -> float:
    """Score based on simple ML prediction (momentum)."""
    # 🚨 THIS DOES NOT USE THE TRAINED ML MODEL!
    # It just calculates momentum!

    closes = [float(b.close) for b in bars[-10:]]
    returns = [(closes[i] - closes[i-1]) / closes[i-1] ...]
    avg_return = sum(returns) / len(returns)

    if avg_return > 0.01:
        return 0.8  # Just momentum, no ML model!
```

**The issue:** FSD has a method called `_score_ml_prediction()` but it doesn't actually load or use the trained ML model!

---

## 🚀 The Solution: Integrate Both!

### How FSD SHOULD Work (with both systems):

```
┌─────────────────────────────────────────────────────────┐
│                    FSD Decision Flow                    │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  New Bar      │
                    │  Arrives      │
                    └───────┬───────┘
                            │
                            ▼
                ┌───────────────────────┐
                │  ConfidenceScorer     │
                │  Calculates Score     │
                └───────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
            ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │  Technical   │ │ Price Action │ │   Volume     │
    │  Indicators  │ │   Patterns   │ │   Profile    │
    │    (30%)     │ │    (25%)     │ │    (20%)     │
    └──────────────┘ └──────────────┘ └──────────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │   ML Model Score      │ ← 🆕 SHOULD USE TRAINED MODEL!
                │      (25%)            │
                └───────┬───────────────┘
                        │
                        ▼
            ┌───────────────────────────┐
            │   Total Confidence        │
            │   (0.0 to 1.0)           │
            └───────┬───────────────────┘
                    │
                    ▼
        ┌───────────────────────────────┐
        │  Reinforcement Learner         │ ← THIS IS FSD's BRAIN!
        │  (Q-Learning Agent)            │
        └───────┬───────────────────────┘
                │
                ▼
        ┌───────────────────────┐
        │  Trade Decision       │
        │  - Should trade?      │
        │  - Which stock?       │
        │  - How much?          │
        └───────┬───────────────┘
                │
                ▼
        ┌───────────────────┐
        │   Execute Trade   │
        └───────┬───────────┘
                │
                ▼
        ┌───────────────────┐
        │   Get PnL Result  │
        └───────┬───────────┘
                │
                ▼
        ┌───────────────────────────┐
        │   Update Q-Values         │ ← LEARNING HAPPENS HERE!
        │   (Reward from PnL)       │
        └───────────────────────────┘
```

---

## 💡 How They Work Together

### Step 1: Traditional ML Provides "Expert Opinion"
```python
# Trained ML model says: "Based on patterns, 75% chance price goes up"
ml_prediction = 0.75
```

### Step 2: FSD ConfidenceScorer Combines ALL Signals
```python
confidence = (
    technical_score * 0.30 +    # e.g., 0.70
    price_action_score * 0.25 +  # e.g., 0.65
    volume_score * 0.20 +         # e.g., 0.80
    ml_prediction * 0.25          # e.g., 0.75 ← FROM TRAINED MODEL!
)
# Total confidence = 0.72 (72%)
```

### Step 3: FSD's RL Agent Makes Final Decision
```python
if confidence >= threshold:
    # Ask Q-Learning agent
    action = rl_agent.get_action(state, available_symbols)

    if action['trade']:
        execute_trade(symbol, size=action['size_fraction'])
```

### Step 4: FSD Learns from Outcome
```python
# Trade completes
pnl = +5.50  # Made profit!

# Update Q-value (THIS is reinforcement learning!)
q_value += learning_rate * (pnl - q_value)

# Store experience for replay
experience_buffer.append(experience)
```

---

## 🎯 The Complete Picture

### Traditional ML (Supervised Learning)
- **What it learns:** Historical patterns
- **How it learns:** You train it manually
- **What it outputs:** "I think price will go up/down"
- **Role in FSD:** Provides ONE input (25% weight) to ConfidenceScorer

### FSD's RL (Q-Learning)
- **What it learns:** Which actions lead to profit
- **How it learns:** Automatically from every trade
- **What it outputs:** "Trade this stock with this size" or "Don't trade"
- **Role in FSD:** Makes the FINAL decision on whether/how to trade

### Together:
```
Traditional ML: "I studied history, I think this looks good (75% confidence)"
                         │
                         ▼
          ConfidenceScorer combines with other signals
                         │
                         ▼
                   Total confidence = 72%
                         │
                         ▼
FSD's RL Agent: "I've learned from 100 trades that when confidence is 72%
                 and portfolio is 40% deployed, trading with 15% size
                 usually makes money. Let's do it!"
```

---

## 🔧 Current Status

### ❌ What's Missing:
- FSD's `_score_ml_prediction()` does NOT use the trained ML model
- It just calculates momentum instead
- So FSD is NOT benefiting from your ML training!

### ✅ What Works:
- BOT mode uses the traditional ML model
- FSD's Q-Learning works independently
- Both systems exist, they just don't talk to each other

---

## 🚀 The Fix (Coming Next)

I'll integrate them so:
1. You train ML model in ML Lab (or Simple Mode does it automatically)
2. FSD loads the trained model
3. FSD's ConfidenceScorer uses REAL ML predictions (not just momentum)
4. FSD's RL agent makes better decisions (because confidence scores are better)
5. FSD learns faster (because it has better information)

---

## 📝 Summary

**Question:** Does FSD use ML?

**Current Answer:**
- ❌ NO - FSD does not use the trained ML model
- ✅ YES - FSD uses its own RL (Q-Learning), which is a type of ML, but different

**Future Answer (after integration):**
- ✅ YES - FSD uses the trained ML model for confidence scoring
- ✅ YES - FSD uses its own RL for final trade decisions
- ✅ BOTH systems work together!

---

## 🎓 ELI5 (Explain Like I'm 5)

**Traditional ML Model:**
- Like studying for a test by reading a textbook
- Learns from history: "This pattern usually means price goes up"
- Outputs: "I'm 75% sure this is a good trade"

**FSD's Reinforcement Learning:**
- Like learning to ride a bike by actually riding
- Learns from doing: "Last time I did this, I made money!"
- Outputs: "Yes, let's trade! Use this much money!"

**Together:**
- Traditional ML is the "expert advisor" whispering suggestions
- FSD's RL is the "decision maker" who takes the final action
- FSD learns WHICH expert advice to trust based on what actually works!

---

**Next:** I'll integrate the trained ML model into FSD so both systems work together! 🚀
