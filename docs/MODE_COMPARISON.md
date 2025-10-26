# Trading Mode Comparison

## 🎯 Three Trading Modes Explained

AIStock Robot offers three distinct trading modes, each designed for different user profiles and asset classes.

---

## 🤖 FSD Mode - Full Self-Driving AI

**Who it's for:** Beginners and "set it and forget it" users
**Asset Classes:** **STOCKS ONLY**
**Control Level:** FULL AI CONTROL (user = passenger)

### What FSD Does

The FSD (Full Self-Driving) mode is like **Tesla's Autopilot for stock trading**. The AI makes ALL decisions autonomously:

#### 1. **Connects to IBKR** (Interactive Brokers)
- Establishes live connection to your broker
- Authenticates and prepares for trading

#### 2. **Pulls ALL Available Data**
- Downloads complete candle/bar history for stocks
- Continuously streams real-time market data
- Monitors price, volume, volatility, momentum

#### 3. **Analyzes Market with ALL Algorithms**
- **Technical Indicators:** SMA, RSI approximation, trend analysis
- **Price Action:** Candlestick patterns, body ratios, momentum
- **Volume Analysis:** Volume spikes, liquidity checks
- **ML Predictions:** Momentum-based forecasting

#### 4. **Dynamically Chooses Stocks**
- Scans available symbols based on:
  - Liquidity (minimum volume requirements)
  - Price range (avoids penny stocks and extremely expensive stocks)
  - Volatility (based on risk level)
- Can trade ANY stock that meets criteria
- NOT limited to pre-selected symbols

#### 5. **Adjusts Parameters in Real-Time**
- Confidence thresholds adapt based on market conditions
- Position sizing changes based on portfolio utilization
- Exploration rate decays as AI learns
- Q-values (action values) update after every trade

#### 6. **Learns from EVERY Trade**
- Uses **Reinforcement Learning** (Q-Learning)
- Positive PnL = reward signal (AI repeats this behavior)
- Negative PnL = punishment signal (AI avoids this behavior)
- Experience Replay: Learns from past trades multiple times
- Persistent Learning: Saves state between sessions

#### 7. **Makes Autonomous Decisions**
- **Can choose NOT to trade** (if confidence is low)
- Decides WHEN to enter positions
- Decides WHEN to exit positions
- Decides HOW MUCH capital to deploy
- NO human intervention required

### FSD Risk Levels

The risk level you choose dictates HOW the AI trades:

#### 🛡️ **Conservative** (Safe & Slow Gains)
- **Max Capital:** Uses up to 30% of your money
- **Target Volatility:** LOW (seeks stable, boring stocks)
- **Confidence Threshold:** HIGH (only trades when very confident)
- **Exploration Rate:** LOW (10%) - less random experimentation
- **Position Sizing:** SMALL (5-10% of available capital per trade)
- **Stop-Loss:** TIGHT (exits quickly on losses)
- **Time Limit:** 60 minutes max per session
- **Best for:** "$200 I can't afford to lose"

#### ⚖️ **Moderate** (Balanced)
- **Max Capital:** Uses up to 50% of your money
- **Target Volatility:** MEDIUM (balanced stocks)
- **Confidence Threshold:** MEDIUM (trades with reasonable confidence)
- **Exploration Rate:** MEDIUM (20%) - balanced experimentation
- **Position Sizing:** MEDIUM (10-20% of available capital per trade)
- **Stop-Loss:** BALANCED (reasonable exit points)
- **Time Limit:** 120 minutes (2 hours)
- **Best for:** "I want balanced growth"

#### 🚀 **Aggressive** (Risky & Fast Gains)
- **Max Capital:** Uses up to 70% of your money
- **Target Volatility:** HIGH (seeks volatile, fast-moving stocks)
- **Confidence Threshold:** LOW (trades more frequently)
- **Exploration Rate:** HIGH (35%) - more random experimentation
- **Position Sizing:** LARGE (20-30% of available capital per trade)
- **Stop-Loss:** LOOSE (gives trades room to run)
- **Time Limit:** 180 minutes (3 hours)
- **Best for:** "YOLO! Maximum gains!"

### FSD Technical Details

#### Only 2 HARD Constraints:
1. **max_capital** - Cannot exceed this amount (e.g., $60 for Conservative with $200)
2. **time_limit_minutes** - Must stop trading after this time

#### Everything Else is Learned:
- Which stocks to trade
- When to enter/exit
- Position sizes
- Confidence thresholds
- Risk parameters

#### Reinforcement Learning:
- **State:** Market features (price, volume, indicators, portfolio utilization)
- **Action:** {trade/no-trade, symbol, size_fraction}
- **Reward:** PnL from the trade
- **Policy:** Epsilon-greedy Q-learning with experience replay

#### AI Components:
1. **ConfidenceScorer** - Multi-factor scoring (technical, price action, volume, ML)
2. **ReinforcementLearner** - Q-learning agent with experience buffer
3. **FSDEngine** - Orchestrates everything

---

## 🚗 Headless Mode - Supervised Autopilot

**Who it's for:** Advanced users who want some control
**Asset Classes:** **STOCKS ONLY**
**Control Level:** SEMI-AUTONOMOUS (user = co-pilot)

### What Headless Does

Headless mode is like **Cruise Control with Lane Assist**. The AI drives, but you're still in the front seat:

#### Features:
- Automated model promotion
- Multi-stage validation before trading
- Approval gates for critical decisions
- Automatic risk adjustments
- Human-in-the-loop for important changes

#### CLI Scripts:
```bash
# Run once
python scripts/supervised_autopilot.py --run-once

# Schedule recurring runs
python scripts/supervised_autopilot.py --schedule

# Health check
python scripts/supervised_autopilot.py --health-check

# List pending approvals
python scripts/supervised_autopilot.py --list-approvals
```

#### When to Use:
- You want automation but with safety gates
- You want to approve major strategy changes
- You want daily summaries and alerts
- You trust AI but want oversight

---

## 🎮 BOT Mode - Strategy Autopilot

**Who it's for:** EXTREME power users who want FULL manual control
**Asset Classes:** **FOREX, CRYPTO, AND STOCKS**
**Control Level:** MANUAL CONTROL (user = driver)

### What BOT Does

BOT mode is like **Manual Transmission**. YOU become the AI:

#### Features:
- Full control over EVERY parameter
- Custom strategy definitions
- Manual indicator tuning
- Classical technical analysis (MA crossover, RSI, momentum, trend-following)
- Optional ML augmentation (YOU choose when/how to use it)
- Multi-asset support (stocks, forex, crypto)

#### Configuration:
- Short window, long window for MA crossover
- RSI period and thresholds
- Momentum lookback period
- Trend-following parameters
- ML model paths and feature lookback
- Custom risk limits per symbol
- Custom execution parameters

#### When to Use:
- You're an experienced trader
- You want to implement YOUR strategy
- You want to trade forex or crypto (FSD/Headless don't support these)
- You want complete control over algorithm parameters
- You don't want AI making decisions for you

---

## 🔍 Mode Comparison Table

| Feature | FSD | Headless | BOT |
|---------|-----|----------|-----|
| **User Profile** | Beginner | Advanced | Expert |
| **Control Level** | None (AI drives) | Some (Co-pilot) | Full (You drive) |
| **Asset Classes** | Stocks only | Stocks only | Forex, Crypto, Stocks |
| **AI Decision Making** | FULL autonomy | Supervised autonomy | Manual with optional ML |
| **Stock Selection** | AI chooses | Pre-configured | Pre-configured |
| **Parameter Tuning** | AI learns optimal | AI suggests, user approves | Manual configuration |
| **Reinforcement Learning** | Yes (continuous) | No | No |
| **Persistent Learning** | Yes (saves state) | No | No |
| **Risk Management** | AI-driven | Hybrid (AI + human) | Manual |
| **Approval Gates** | None | Yes (major decisions) | All (you approve everything) |
| **Complexity** | 3 questions | Medium | High |
| **Setup Time** | 30 seconds | 10 minutes | Hours/Days |
| **Maintenance** | None | Weekly check-ins | Daily tuning |

---

## 🎯 Which Mode Should I Choose?

### Choose FSD if:
- ✅ You're new to trading
- ✅ You have limited capital ($200-$5000)
- ✅ You want to "set it and forget it"
- ✅ You trust AI to make decisions
- ✅ You only trade stocks (not forex/crypto)
- ✅ You want the AI to learn and improve over time

### Choose Headless if:
- ✅ You understand trading basics
- ✅ You want automation with oversight
- ✅ You want to approve major changes
- ✅ You're comfortable with scheduled checks
- ✅ You only trade stocks
- ✅ You want safety gates and validation

### Choose BOT if:
- ✅ You're an experienced trader
- ✅ You have a specific strategy you want to implement
- ✅ You want to trade forex or crypto
- ✅ You want full control over every parameter
- ✅ You enjoy fine-tuning and optimization
- ✅ You don't want AI making autonomous decisions

---

## 🚀 Recommendation: Start with FSD!

If you're reading this and unsure, **START WITH FSD**:

1. **Launch Simple Mode:**
   ```bash
   python -m aistock
   ```

2. **Answer 3 questions:**
   - How much money? (e.g., $200)
   - Risk level? (Start with Conservative)
   - Click START!

3. **Watch it trade:**
   - The AI will learn from every trade
   - You can switch to Advanced Mode anytime
   - You can upgrade to Headless/BOT later

4. **Graduate when ready:**
   - After FSD learns your risk profile → Try Headless
   - After Headless gets consistent → Try BOT with custom strategies
   - Or just stay in FSD and let it keep learning!

---

## 🧠 The Philosophy

### FSD = Human with Tools
Think of FSD like a human trader who:
- Has access to ALL algorithms (tools)
- Can use tools of different sizes (parameters)
- Chooses the best tool for each job (dynamic parameter selection)
- Learns from mistakes (reinforcement learning)
- Gets better over time (persistent learning)

### Headless = Human with Assistant
Think of Headless like a trader with an AI assistant:
- Assistant suggests trades
- Human approves major decisions
- Automated monitoring and alerts
- Safety checks before execution

### BOT = Human IS the AI
Think of BOT like:
- You manually configure EVERYTHING
- You ARE the decision maker
- AI provides optional signal augmentation
- You control when/how to use ML

---

## 📊 Performance Expectations

### FSD Mode:
- **First 100 trades:** Learning phase (expect mixed results)
- **100-500 trades:** Pattern recognition improves
- **500+ trades:** Mature decision-making
- **Continuous:** Never stops learning

### Headless Mode:
- **Backtested strategies** with approval gates
- **Consistent but** requires periodic tuning
- **Human oversight** prevents runaway behavior

### BOT Mode:
- **Performance depends** entirely on YOUR strategy
- **No learning curve** - executes YOUR rules
- **Requires constant tuning** based on market conditions

---

## ⚠️ Important Notes

1. **FSD and Headless are STOCKS ONLY** - They don't support forex or crypto
2. **BOT supports ALL asset classes** - Use BOT if you want forex/crypto
3. **FSD learns continuously** - Give it time to learn your risk profile
4. **All modes use the SAME algorithms** - They just use them differently
5. **Risk management is ALWAYS active** - Even FSD respects hard limits

---

**Ready to start?**

```bash
python -m aistock  # Simple Mode (FSD) - Perfect for beginners!
```
