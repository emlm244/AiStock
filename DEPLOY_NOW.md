# 🚀 Quick Deployment Guide - AI Stock Bot

## ✅ Status: PRODUCTION READY
**1 Critical Bug Fixed** | Code Review Complete | Ready to Deploy

---

## 🔧 Pre-Deployment (5 minutes)

### 1. Install Dependencies
```bash
cd /workspace
pip install -r requirements.txt
```

### 2. Create .env File
```bash
cp .env.example .env
nano .env  # Edit with your credentials
```

Required variables:
```
IBKR_ACCOUNT_ID=YOUR_ACCOUNT_ID
IBKR_TWS_HOST=127.0.0.1
IBKR_TWS_PORT=7497  # Paper trading
TIMEZONE=America/New_York
LOG_LEVEL=INFO
```

### 3. Prepare Directories
```bash
mkdir -p data/{historical_data,live_data,backtest_results}
mkdir -p logs/{error_logs,trade_logs}
mkdir -p models
```

---

## 🧪 Validation (10 minutes)

### Run Tests
```bash
python3 -m pytest tests/ -v
```

### Run Linting
```bash
pip install ruff
ruff check .
```

### Validate Backtest (if you have data)
```bash
python3 backtest.py --symbols "BTC/USD" --data-dir data/historical_data
```

---

## 🎯 First Run (Paper Trading)

### 1. Start TWS/Gateway
- Launch IB Gateway or TWS
- Login with **paper trading account**
- Enable API: Configure → Settings → API → Enable ActiveX and Socket Clients
- Note the port (7497 for paper TWS, 4002 for paper Gateway)

### 2. Launch Bot (Interactive Mode)
```bash
python3 main.py
```

Follow prompts:
- Select trading mode (Crypto/Stock/Forex)
- Enter instruments (e.g., `BTC/USD,ETH/USD`)
- Enable autonomous mode: Y
- Enable adaptive risk: Y
- Enable auto-retraining: Y

### 3. Launch Bot (Headless Mode)
```bash
python3 main.py --headless --mode crypto --instruments "BTC/USD,ETH/USD" --autonomous
```

---

## 📊 Monitoring

### Check Logs
```bash
# Main application log
tail -f logs/app.log

# Error logs
tail -f logs/error_logs/errors.log

# Trade logs
tail -f logs/trade_logs/trades.log
```

### Key Metrics to Watch
- ✅ Connection status (should show "Connected")
- ✅ Market data flowing (tick updates)
- ✅ Strategy signals generating
- ✅ Risk limits enforced
- ✅ No critical errors

---

## 🛡️ Safety Features Active

### Risk Management
- ✅ Daily loss limit: 3% of capital (configurable)
- ✅ Max drawdown: 15% from peak (configurable)
- ✅ Position size limits
- ✅ Pre-trade risk checks
- ✅ Trading halts on breach

### Autonomous Features
- ✅ Adaptive stop-loss/take-profit (volatility-based)
- ✅ Dynamic strategy weighting
- ✅ Auto ML retraining (when performance drops)
- ✅ Market regime detection

### Error Handling
- ✅ Automatic reconnection
- ✅ Circuit breakers on API failures
- ✅ Data validation
- ✅ State persistence
- ✅ Graceful degradation

---

## 🎮 Commands

### Training ML Model
```bash
python3 main.py --train
# or
python3 train_model.py
```

### Running Backtest
```bash
python3 backtest.py --symbols "BTC/USD,ETH/USD" \
    --data-dir data/live_data \
    --start-date 2024-01-01 \
    --end-date 2024-12-31
```

### Stopping Bot
- Interactive mode: `Ctrl+C` (bot will gracefully shutdown)
- Headless mode: Send SIGTERM/SIGINT signal

---

## 📈 Performance Expectations

### Paper Trading Phase (1-2 weeks)
- **Goal**: Validate system behavior
- **Watch for**: 
  - Clean order execution
  - Accurate position tracking
  - Risk limits working
  - No critical errors
  - State recovery after restart

### Live Trading Phase (Start Conservative)
- **Initial capital**: Start with 10-20% of intended capital
- **Position sizes**: Use RISK_PER_TRADE=0.005 (0.5%)
- **Instruments**: Start with 1-2 liquid pairs
- **Duration**: Monitor for 1 week before scaling

### Scaling Up
- Increase capital gradually (10% per week)
- Add instruments slowly (1 per week)
- Monitor performance metrics
- Adjust risk parameters based on results

---

## ⚠️ Critical Settings (config/settings.py)

### Risk Parameters (NEVER WEAKEN)
```python
MAX_DAILY_LOSS = 0.03          # 3% max daily loss
MAX_DRAWDOWN_LIMIT = 0.15      # 15% max drawdown
RISK_PER_TRADE = 0.01          # 1% risk per trade
```

### Trading Settings
```python
TRADING_MODE = 'crypto'        # stock/crypto/forex
TRADE_INSTRUMENTS = ['BTC/USD', 'ETH/USD']
TIMEFRAME = '30 secs'          # Bar size
TOTAL_CAPITAL = 10000          # Starting capital
```

### Autonomous Mode
```python
AUTONOMOUS_MODE = True
ENABLE_ADAPTIVE_RISK = True
ENABLE_AUTO_RETRAINING = True
ENABLE_DYNAMIC_STRATEGY_WEIGHTING = True
```

---

## 🐛 Troubleshooting

### Connection Issues
```
Problem: "Failed to connect to TWS"
Solution: 
1. Ensure TWS/Gateway is running
2. Check API is enabled
3. Verify port matches (7497/4002)
4. Check firewall rules
```

### No Market Data
```
Problem: "No ticks received"
Solution:
1. Check market data subscriptions in TWS
2. Verify instruments are correct format
3. Check market is open for that asset
4. Review error logs for rejections
```

### Orders Not Filling
```
Problem: "Orders stuck in PreSubmitted"
Solution:
1. Check available margin
2. Verify contract details
3. Check minimum trade sizes
4. Review order reject errors
```

### Model Not Loading
```
Problem: "ML Strategy: Model not loaded"
Solution:
1. Train model first: python3 main.py --train
2. Check models/trading_model.pkl exists
3. Review error logs for details
```

---

## 📞 Support Resources

### Documentation
- `CLAUDE.md` - Complete development guide
- `OPERATIONAL_RUNBOOK.md` - Operations manual
- `PRODUCTION_READY_REVIEW.md` - Full code review
- `README.md` - Project overview

### IBKR Resources
- API Documentation: https://ibkrcampus.com/ibkr-api-page/twsapi-doc/
- Paper Trading: https://www.interactivebrokers.com/en/index.php?f=1286
- API Configuration: https://ibkrcampus.com/ibkr-api-page/twsapi-doc/#

---

## ✅ Deployment Checklist

### Before First Run
- [ ] Dependencies installed
- [ ] `.env` file configured
- [ ] Directories created
- [ ] Tests passed (optional but recommended)
- [ ] TWS/Gateway running
- [ ] API enabled in TWS
- [ ] Paper trading account active

### First 24 Hours
- [ ] Bot connects successfully
- [ ] Market data flowing
- [ ] Orders executing
- [ ] Positions tracked correctly
- [ ] No critical errors
- [ ] State saving working

### First Week
- [ ] Daily PnL tracking accurate
- [ ] Risk limits tested (or observed)
- [ ] Strategy signals reasonable
- [ ] ML model loading (if enabled)
- [ ] Regime detection working
- [ ] Restart recovery successful

### Before Live Trading
- [ ] Paper trading for 1+ week
- [ ] Performance meets expectations
- [ ] All features validated
- [ ] Risk parameters tuned
- [ ] Monitoring set up
- [ ] Backup/recovery tested

---

## 🎯 Success Criteria

### Technical
- ✅ Uptime > 99%
- ✅ Zero critical errors
- ✅ Clean state recovery
- ✅ Accurate P&L tracking

### Trading
- ✅ Risk limits enforced
- ✅ Orders execute as expected
- ✅ Position management correct
- ✅ Performance tracking accurate

### Operational
- ✅ Logs comprehensive
- ✅ State persists correctly
- ✅ Monitoring working
- ✅ Alerts functioning

---

## 🚀 Ready to Deploy!

Your AI Stock Bot is **production-ready** with:
- ✅ 1 critical bug fixed
- ✅ Comprehensive code review completed
- ✅ All safety features active
- ✅ Excellent documentation
- ✅ Professional error handling

**Start with paper trading, monitor carefully, then scale gradually.**

Good luck! 🎉

---

**Last Updated:** 2025-10-27
**Version:** Production Ready v1.0
**Review Status:** ✅ APPROVED
