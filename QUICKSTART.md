# AIStock Robot - QUICKSTART GUIDE

**⏱️ Get trading in 10 minutes**

---

## 📋 Prerequisites

- Python 3.8+
- Interactive Brokers account (paper or live)
- TWS or IB Gateway installed and running

---

## 🚀 Installation (5 minutes)

### Step 1: Clone & Setup

```bash
git clone <your-repo-url>
cd AIStock
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set **ONLY** this required value:
```bash
IBKR_ACCOUNT_ID=DU1234567  # Your IB paper account ID
```

That's it! Other settings use safe defaults.

### Step 3: Enable TWS API

1. Open TWS or IB Gateway
2. Go to **File → Global Configuration → API → Settings**
3. Check ✅ **"Enable ActiveX and Socket Clients"**
4. Add `127.0.0.1` to **Trusted IP Addresses**
5. Set **Socket Port** to `7497` (paper trading)
6. **Uncheck** "Read-Only API"
7. Click **OK** and restart TWS

---

## 🎯 Choose Your Mode

### Option 1: FSD Mode (RECOMMENDED - Easiest)

**What**: AI makes ALL decisions. You just watch.

```bash
python main.py
```

When prompted:
1. Select **"1: FSD (Full Self-Driving)"**
2. Enter stocks (e.g., `AAPL,MSFT,GOOGL`)
3. Confirm paper trading
4. ✅ Done! AI is now trading.

**FSD learns as it trades**. After 100-500 trades, performance improves significantly.

---

### Option 2: Supervised Mode (AI-Assisted)

**What**: AI optimizes parameters, you choose what to trade.

```bash
python main.py
```

When prompted:
1. Select **"2: SUPERVISED"**
2. Enter stocks
3. Review AI suggestions
4. ✅ AI handles optimization

---

### Option 3: BOT Mode (Full Control)

**What**: You control everything. For power users.

```bash
python main.py
```

When prompted:
1. Select **"3: BOT"**
2. Choose asset type (stocks/crypto/forex)
3. Enter instruments
4. Configure parameters
5. ✅ Manual trading

---

## 📊 Monitor Your Bot

### Real-Time Display

The bot shows live status every second:

```
[14:35:22 EST] Eq:10,234.50 | DD:2.1% | DailyPnL:+234.50 | Conn:Connected | Status:Running |
```

**Key Metrics**:
- `Eq`: Current equity
- `DD`: Drawdown from peak
- `DailyPnL`: Today's profit/loss
- `Conn`: API connection status
- `Status`: Running or HALTED

### Check Logs

```bash
# Main log (trades, signals, decisions)
tail -f logs/app.log

# Errors only
tail -f logs/error_logs/errors.log

# Trade executions
tail -f logs/trade_logs/trades.log
```

---

## 🛑 Stop The Bot

**Safe Shutdown**:
```
Press Ctrl+C once
```

The bot will:
1. ✅ Stop evaluating new signals
2. ✅ Save state to disk
3. ✅ (Optional) Cancel open orders
4. ✅ Disconnect from API
5. ✅ Exit cleanly

**DO NOT** kill the process forcefully (Ctrl+C twice or kill -9).

---

## 🔧 Headless Mode (For Servers/Docker)

**FSD Mode**:
```bash
python main.py --headless --intelligence-mode fsd --instruments "AAPL,MSFT"
```

**BOT Mode (Crypto)**:
```bash
python main.py --headless --intelligence-mode bot --mode crypto --instruments "BTC/USD,ETH/USD"
```

**Add to systemd/supervisor** for auto-restart on crashes.

---

## 📈 View Performance

### FSD Mode Stats

```python
# After 100+ trades, check FSD learning:
python -c "
import json
with open('data/bot_state.json') as f:
    state = json.load(f)
    print('FSD Q-Values Learned:', len(state.get('fsd_q_values', {})))
"
```

### Backtest Results

```bash
ls -lh data/backtest_results/
# View equity_curve_*.csv and trades_*.csv
```

---

## ⚠️ Common Issues

### Issue: "API connection timeout"

**Fix**:
1. Verify TWS/Gateway is running
2. Check API is enabled (see Step 3 above)
3. Confirm port 7497 (paper) or 7496 (live)

### Issue: "No valid instruments"

**Fix**:
- FSD/Supervised: Use stock tickers only (AAPL, MSFT, GOOGL)
- BOT: Match mode to instruments (crypto needs BTC/USD format)

### Issue: "Trading halted - Max daily loss"

**Cause**: Daily loss limit reached (default: 3% of capital)

**Fix**: Risk manager will auto-reset at next trading day. Adjust `MAX_DAILY_LOSS` in `config/settings.py` if needed (NOT recommended).

---

## 🎓 Next Steps

### Learn FSD Reinforcement Learning

Read: `/workspace/IMPLEMENTATION_SUMMARY.md` → **Understanding FSD** section

### Run Backtests

```bash
python backtest.py --symbols "AAPL,MSFT" --data-dir data/live_data
```

### Train ML Model (for BOT mode)

```bash
python main.py --train
```

### Enable Live Trading (⚠️ USE WITH CAUTION)

```bash
# 1. Change port to 7496 in .env:
echo "IBKR_TWS_PORT=7496" >> .env

# 2. Add --live-trading flag:
python main.py --headless --intelligence-mode fsd --instruments "AAPL" --live-trading

# 3. Type "I ACCEPT THE RISK" when prompted
```

**ONLY do this after**:
- ✅ 2+ weeks successful paper trading
- ✅ FSD win rate > 55%
- ✅ Sharpe ratio > 1.0
- ✅ Max drawdown < 10%

---

## 📚 Documentation

- **Full Guide**: `/workspace/README.md`
- **Implementation Details**: `/workspace/IMPLEMENTATION_SUMMARY.md`
- **API Reference**: `/workspace/CLAUDE.md`
- **Tests**: `pytest tests/ -v`

---

## 🆘 Getting Help

1. **Check logs**: `logs/app.log` and `logs/error_logs/errors.log`
2. **Read docs**: Start with `IMPLEMENTATION_SUMMARY.md`
3. **Run tests**: `pytest tests/test_aistock_integration.py -v`
4. **Check state**: `data/bot_state.json`

---

## ✅ Checklist

Before going live:

- [ ] Paper trading successful for 2+ weeks
- [ ] Win rate consistently > 55%
- [ ] Sharpe ratio > 1.0
- [ ] Maximum drawdown < 10%
- [ ] No unexplained errors in logs
- [ ] FSD Q-values > 1,000 (if using FSD mode)
- [ ] Understand all risk limits
- [ ] Have explicit `--live-trading` flag
- [ ] Start with small capital ($100-$500)

---

**🎉 Congratulations! You're now running an AI-powered trading bot.**

Remember: **Start with FSD mode in paper trading**. Let it learn for 100-500 trades before trusting it with real money.

**Questions?** Read `/workspace/IMPLEMENTATION_SUMMARY.md` for detailed explanations.
