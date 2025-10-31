# 🚀 START HERE - FSD Mode Quick Start

**Get trading in 2 minutes with AI-powered Full Self-Driving mode**

---

## ⚡ Launch (30 seconds)

```bash
python -m aistock
```

**That's it!** The GUI will open.

---

## 🎯 First Time Setup

### Step 1: Configure FSD
1. **Capital**: Enter `200` (dollars)
2. **Risk Level**: Choose `Conservative` (safe) or `Moderate` (balanced)
3. **Investment Goal**: `Steady Growth` (recommended)
4. **Time Limit**: `60` minutes (1 hour)

### Step 2: Choose Trading Mode
- **Paper Trading** ✅ (Recommended for first time)
  - Uses fake money
  - Zero risk
  - Perfect for testing
  
- **Live Trading** ⚠️ (Real money)
  - Requires Interactive Brokers account
  - Real money at risk
  - Only after testing in paper mode

### Step 3: Start Trading
1. Click **🚀 START ROBOT**
2. Watch the AI analyze markets
3. See trades in real-time
4. Monitor performance on dashboard

---

## 📊 Understanding the Dashboard

### Top Section:
- **Balance**: Current portfolio value
- **Daily P&L**: Profit/Loss today
- **Win Rate**: Percentage of profitable trades
- **Status**: What the AI is doing now

### Activity Log:
- Real-time updates
- Trade executions
- AI decisions
- Learning updates

### FSD Stats:
- **Q-Values Learned**: How much AI has learned
- **Exploration Rate**: How experimental AI is
- **Total Trades**: Number of trades made
- **Win Rate**: Success percentage

---

## 🎓 How FSD Works

1. **AI Analyzes Market**
   - Price trends
   - Volume patterns
   - Volatility levels
   - Position status

2. **Makes Decision**
   - BUY, SELL, or HOLD
   - Confidence level (0-100%)
   - Position size

3. **Executes Trade**
   - Submits order to broker
   - Updates portfolio
   - Manages risk

4. **Learns from Result**
   - Updates Q-values
   - Improves strategy
   - Gets smarter over time

---

## 🔒 Risk Management

### Built-in Safety:
- ✅ **Daily Loss Limit**: Auto-stops if loss too high
- ✅ **Position Size Caps**: Max 20% per symbol
- ✅ **Confidence Threshold**: Only trades when confident
- ✅ **Risk Penalties**: Discourage excessive risk

### Your Responsibilities:
- ⚠️ Start with small capital
- ⚠️ Use paper trading first
- ⚠️ Monitor regularly
- ⚠️ Set strict limits
- ⚠️ Never risk more than you can lose

---

## 💡 Quick Tips

### For Best Results:
1. **Run for at least 1 hour** - AI needs time to learn
2. **Don't interrupt** - Let it complete the session
3. **Review trades** - Check what AI learned
4. **Increase gradually** - Start small, scale up slowly
5. **Trust the process** - AI improves over time

### Common Mistakes:
- ❌ Starting with too much capital
- ❌ Interrupting the learning process
- ❌ Changing settings too frequently
- ❌ Not using paper trading first
- ❌ Expecting instant profits

---

## 🐛 Troubleshooting

### GUI Won't Launch?
```bash
pip install -r requirements.txt
python -m aistock
```

### No Trades Happening?
- Check confidence threshold (lower it in settings)
- Ensure market data is available
- Verify capital is sufficient

### AI Not Learning?
- Let it run longer (needs 20+ trades)
- Check that trades are executing
- Review FSD stats in dashboard

---

## 📚 Next Steps

### After First Session:
1. ✅ Review dashboard metrics
2. ✅ Check trade log
3. ✅ Adjust risk level if needed
4. ✅ Try longer session (2-4 hours)

### Going Live:
1. ✅ Test in paper mode for 1+ week
2. ✅ See consistent positive results
3. ✅ Read **IBKR_CONNECTION_TEST_GUIDE.md**
4. ✅ Start with minimal capital ($100-500)
5. ✅ Monitor closely

### Advanced:
- Read `docs/FSD_ENHANCED.md` for technical details
- Modify `FSDConfig` parameters
- Export Q-values for analysis
- Backtest on historical data

---

## 🎯 What to Expect

### First Hour:
- AI is exploring and learning
- Win rate may be ~50%
- Some losses are normal
- Building Q-value table

### After 10+ Hours:
- AI has learned patterns
- Win rate improves (60%+)
- More confident decisions
- Better risk management

### Long Term:
- Continuously adapts to markets
- Learns from all trades
- Improves over time
- Stable performance

---

## 🚀 Ready to Start?

```bash
python -m aistock
```

**Remember**: Start with paper trading, use small capital, and let the AI learn!

---

**Questions?** Check `README.md` or `IBKR_CONNECTION_TEST_GUIDE.md`

**Ready to trade!** 🎯
