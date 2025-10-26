# Trading Mode Comparison Guide

## 🎯 Three Modes, Three User Types

```
FSD (Full Self-Driving)    ←  Beginners & "Set and Forget"
        ↓
Headless (Semi-Autonomous) ←  Advanced Users
        ↓
BOT (Manual Control)       ←  Power Users & Traders
```

---

## 📊 **Mode Comparison Table**

| Feature | FSD (AI) | Headless | BOT (Manual) |
|---------|----------|----------|--------------|
| **Target User** | Beginners | Advanced | Power Users |
| **Autonomy** | 100% AI | AI assists | Full manual |
| **Asset Classes** | Stocks only | Stocks only | Stocks + Forex + Crypto |
| **User Input** | Capital + Risk Level | Strategy params | Everything |
| **Stock Selection** | AI chooses | User + AI | User chooses |
| **Entry/Exit Timing** | AI decides | AI suggests, user approves | User decides |
| **Position Sizing** | AI calculates | AI recommends | User sets |
| **Risk Management** | AI adapts | User sets limits, AI enforces | User controls |
| **Learning** | Learns from every trade | No learning | No learning |
| **State Persistence** | Saves & loads | Config-based | Config-based |
| **Can Skip Trades** | Yes, if confidence low | Yes, if conditions not met | User decides |
| **Complexity** | ⭐ Simple | ⭐⭐⭐ Moderate | ⭐⭐⭐⭐⭐ Complex |

---

## 1️⃣ **FSD (Full Self-Driving) - AI Mode**

### **Philosophy**
> "You're the passenger, AI is the driver"

### **User Experience**
```
1. Enter capital: $200
2. Choose risk: Conservative/Moderate/Aggressive
3. Click START
4. Walk away - AI does everything
```

### **What AI Controls**
- ✅ Which stocks to scan (scans all 36)
- ✅ Which stocks to trade (chooses based on analysis)
- ✅ When to enter trades
- ✅ When to exit trades
- ✅ Position sizes
- ✅ Which algorithms to weight
- ✅ Risk parameters
- ✅ Can choose NOT to trade

### **Only 2 Hard Constraints**
1. **Max Capital**: Cannot exceed (e.g., $200)
2. **Time Deadline**: Must trade within timeframe (e.g., 60 minutes)

### **Learning Mechanism**
```
Good Trade (+$50)  →  Reinforces behavior  →  Do more of this
Bad Trade  (-$20)  →  Learns to avoid      →  Don't do this again
```

### **Session Persistence**
```
Session 1: AI explores, makes trades, learns
           ↓
         Saves state (Q-values, win rate, exploration rate)
           ↓
Session 2: Loads previous state, continues learning
           ↓
         Gets smarter over time!
```

### **Best For**
- Beginners who don't know technical analysis
- Busy people who can't watch markets
- People who want to "set and forget"
- Those who trust AI to learn and improve

### **Example Day**
```
9:30 AM  - User starts FSD with $200, Aggressive mode
9:31 AM  - AI scans 36 stocks, finds NVDA and TSLA look good
9:35 AM  - AI enters NVDA position ($60, 30% of capital)
10:15 AM - AI monitors, decides to hold
11:00 AM - AI sees profit opportunity, exits at +$8
11:05 AM - AI enters TSLA position ($65)
2:00 PM  - AI sees loss forming, cuts position at -$3
4:00 PM  - Session ends: +$5 total
           AI saves: "NVDA setup was good, TSLA timing was bad"
Next day - AI uses yesterday's lesson to trade smarter
```

---

## 2️⃣ **Headless (Semi-Autonomous) - Assisted Mode**

### **Philosophy**
> "You're the driver, AI is your co-pilot"

### **User Experience**
```
1. Set strategy parameters (MA periods, RSI thresholds, etc.)
2. Set risk limits (max loss, position size, etc.)
3. Start session
4. AI suggests trades, you approve/reject
```

### **What User Controls**
- Strategy selection (MA crossover, RSI, trend following)
- Technical indicator parameters
- Risk limits
- Which stocks to include
- Approval of each trade

### **What AI Does**
- Monitors markets 24/7
- Generates trade signals
- Calculates position sizes
- Enforces risk limits
- Suggests when to exit

### **Learning Mechanism**
- No learning - uses your configured strategy
- You manually adjust parameters based on results

### **Best For**
- Traders who know what they want but need execution help
- Those who want to test specific strategies
- Users who want oversight but automation
- Advanced users learning to optimize strategies

### **Example Day**
```
User: Sets MA(10,20) crossover strategy, max 2% loss per trade
AI:   Monitors markets, finds MA crossover on AAPL
AI:   → "Suggested trade: Buy AAPL, 50 shares, entry $150"
User: Approves
AI:   Executes trade, monitors position
AI:   → "Stop loss triggered at $147 (-2%)"
AI:   Auto-exits position
User: Reviews results, adjusts MA periods for tomorrow
```

---

## 3️⃣ **BOT (Manual Control) - Power User Mode**

### **Philosophy**
> "You are the AI - full control"

### **User Experience**
```
1. Configure EVERYTHING:
   - Indicators (MA, RSI, Bollinger, MACD, etc.)
   - Entry conditions
   - Exit conditions
   - Position sizing formulas
   - Risk parameters
   - Symbols to trade
   - Timeframes
   - Backtesting windows
2. Run backtests
3. Optimize parameters
4. Train ML models
5. Run live with your exact specifications
```

### **What User Controls**
- EVERYTHING
- Every parameter
- Every decision
- Every algorithm
- Multi-asset (stocks, forex, crypto)

### **What AI Does**
- Nothing (unless you code it)
- Executes your rules
- Provides tools (indicators, backtesting, ML)
- You build your own "AI"

### **Learning Mechanism**
- You are the learning mechanism
- Backtest → Analyze → Optimize → Repeat
- Optional: Train your own ML models

### **Best For**
- Quantitative traders
- Algorithm developers
- Traders with proven strategies
- Those who want maximum control
- Professionals building trading systems

### **Example Day**
```
User: Spends 2 hours coding custom strategy
User: Backtests on 2 years of data
User: Optimizes parameters manually
User: Trains custom ML model
User: Deploys to live trading
User: Monitors every tick
User: Manually adjusts as needed
User: Analyzes logs, tweaks for tomorrow
```

---

## 🎬 **Which Mode Should You Use?**

### **Choose FSD if**:
- ✅ You're new to trading
- ✅ You don't have time to watch markets
- ✅ You want AI to handle everything
- ✅ You're okay with AI learning from mistakes
- ✅ You trade STOCKS only
- ✅ You want "Tesla FSD for trading"

### **Choose Headless if**:
- ✅ You know technical analysis
- ✅ You have a strategy in mind
- ✅ You want to test specific approaches
- ✅ You want oversight on AI decisions
- ✅ You trade STOCKS only
- ✅ You want "Autopilot with supervision"

### **Choose BOT if**:
- ✅ You're an experienced trader
- ✅ You want to build custom strategies
- ✅ You trade multiple asset classes
- ✅ You want maximum control
- ✅ You have time to optimize
- ✅ You want "Manual mode with tools"

---

## 🚀 **Getting Started**

### **FSD Mode**
```bash
python -m aistock
# or
python launch_gui.py
# Select option 1 (Simple Mode)
```

### **Headless Mode**
```bash
python -m aistock --advanced
# Select "Headless" mode in GUI
```

### **BOT Mode**
```bash
python -m aistock --advanced
# Use full Advanced GUI with all tabs
```

---

## 📈 **Progression Path**

Many users follow this learning path:

```
1. Start with FSD
   - Learn by watching AI
   - Understand what works
   - Build confidence

2. Move to Headless
   - Apply what you learned
   - Test your own ideas
   - Refine strategies

3. Graduate to BOT
   - Full customization
   - Professional trading
   - Algorithm development
```

**Or**: Stay in FSD forever if it's working! 🎯

---

## 🔄 **Can You Switch Modes?**

**Yes!** You can switch anytime:

```
FSD Session → Save results → Load in Headless → Analyze
Headless → Test strategy → If good → Automate in FSD
BOT → Develop algo → Simplify → Run in Headless
```

---

## 💡 **Pro Tips**

### **FSD Users**:
- Start Conservative, increase risk as AI learns
- Let it run for at least 10 sessions before judging
- Check performance history regularly
- Trust the learning process

### **Headless Users**:
- Backtest your strategy first
- Start with paper trading
- Monitor AI suggestions to learn
- Adjust parameters based on market conditions

### **BOT Users**:
- Document everything you try
- Keep a trading journal
- Use version control for strategies
- Backtest rigorously before going live

---

## ❓ **FAQ**

**Q: Can FSD trade forex or crypto?**
A: No, FSD is stocks-only for safety. Use BOT mode for other assets.

**Q: Will FSD lose all my money?**
A: FSD respects max capital and has built-in risk controls. But any trading carries risk.

**Q: How long until FSD is "good"?**
A: It learns from every trade. Typically shows improvement after 20-50 trades.

**Q: Can I see what FSD is thinking?**
A: Yes! FSD logs confidence scores, decision reasoning, and learning progress.

**Q: What if I don't like FSD's trades?**
A: You can stop it anytime, or switch to Headless for more control.

**Q: Can I use FSD and BOT together?**
A: Not simultaneously. But you can run FSD for stocks, BOT for crypto separately.

---

## 📝 **Summary**

| Mode | User Type | Control | Assets | Learning |
|------|-----------|---------|--------|----------|
| **FSD** | Beginner | AI | Stocks | Yes ✅ |
| **Headless** | Advanced | Shared | Stocks | No |
| **BOT** | Expert | User | All | Optional |

**Choose your mode, start trading, and evolve your approach over time!** 🚀
