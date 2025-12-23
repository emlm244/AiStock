# 🤖 AIStock Robot v2.0 - FSD Mode

**Full Self-Driving AI Trading System** powered by Reinforcement Learning (Q-Learning)

---

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Launch FSD Mode
python -m aistock
```

---

## 🎯 What is FSD Mode?

**FSD (Full Self-Driving)** = AI makes **ALL trading decisions** automatically

- 🤖 **Reinforcement Learning** - Q-Learning algorithm
- 📚 **Learns from every trade** - Gets smarter over time
- 🎯 **Fully autonomous** - No manual configuration needed
- 📈 **Risk-managed** - Built-in safety limits
- 💰 **Paper & Live trading** - Test before going live

---

## 📊 Features

- **AI Decision Making**: Q-Learning RL agent
- **Custom Trading Engine**: Built from scratch (no external dependencies)
- **Risk Management**: Daily loss limits, position sizing, drawdown protection
- **Broker Integration**: Paper trading + Interactive Brokers (IBKR)
- **Real-time Learning**: Updates Q-values after every trade
- **State Persistence**: Saves learned strategies
- **Crash Recovery**: Auto-saves portfolio state

---

## 🎮 Usage

### 1. Configure FSD
- **Capital**: How much to trade ($200 recommended for testing)
- **Risk Level**: Conservative / Moderate / Aggressive
- **Trading Goal**: Quick Gains / Steady Growth
- **Time Limit**: Session duration (1-4 hours)

### 2. Choose Mode
- **Paper Trading**: Practice with fake money (recommended)
- **Live Trading**: Real money via Interactive Brokers

### 3. Start Trading
- Click **START ROBOT**
- AI begins analyzing markets
- Makes autonomous trading decisions
- Learns from every outcome

---

## 🔧 Configuration

### FSD Config (`aistock/fsd.py`)
```python
@dataclass
class FSDConfig:
    learning_rate: float = 0.001           # How fast AI learns
    discount_factor: float = 0.95          # Future reward importance
    exploration_rate: float = 0.1          # Randomness level
    max_capital: float = 10000.0           # Capital limit
    min_confidence_threshold: float = 0.6  # Min confidence to trade
```

---

## 📁 Project Structure

```
aistock/
├── fsd.py              # FSD RL Agent (CORE)
├── engine.py           # Custom trading engine
├── simple_gui.py       # FSD GUI interface
├── session.py          # Live trading orchestration
├── portfolio.py        # Position tracking
├── risk.py             # Risk management
└── brokers/            # Broker integrations
    ├── paper.py        # Paper trading
    └── ibkr.py         # Interactive Brokers
```

---

## 🧪 Testing

```bash
# Install dev/test tooling
pip install -r requirements-dev.txt

# Run tests
pytest tests/

# Test FSD import
python -c "from aistock.fsd import FSDEngine; print('✅ OK')"

# Launch GUI
python -m aistock
```

---

## 📚 Documentation

- **START_HERE.md** - Quick start guide for new users
- **IBKR_REQUIREMENTS_CHECKLIST.md** - IBKR connection setup
- **docs/FSD_COMPLETE_GUIDE.md** - FSD technical deep dive
- **CODE_REVIEW_FIXES_IMPLEMENTATION_COMPLETE.md** - Recent improvements (Oct 30, 2025)
- **CLAUDE.md** - Developer guide for working with the codebase

---

## 🔒 Risk Disclaimer

**Trading involves risk of loss. Past performance does not guarantee future results.**

⚠️ **IMPORTANT**: Always start with paper trading and use extreme caution with live trading.

**Before trading with real money:**
1. Run paper trading successfully for 1-2 weeks
2. Review `CODE_REVIEW_FIXES_IMPLEMENTATION_COMPLETE.md` for recent improvements
3. Start with **very small capital** ($1K-2K, NOT $10K)
4. Use **single symbol** initially (e.g., AAPL only)
5. Set **conservative FSD parameters** (learning_rate=0.0001, min_confidence=0.8)
6. Set **strict risk limits** (2% max daily loss)
7. Monitor every trade manually for first week
8. Never trade more than you can afford to lose completely

---

## 🛠️ Tech Stack

- **Python 3.10+**
- **Tkinter** - GUI
- **NumPy** - Math operations
- **Custom Engine** - No BackTrader dependency
- **Q-Learning** - Reinforcement learning algorithm

---

## 🎯 Quick Tips

### For Beginners:
1. Start with **$200 capital**
2. Choose **Conservative risk**
3. Use **Paper trading** first
4. Let it run for **1 hour**
5. Review trades in dashboard

### For Advanced Users:
- Adjust `FSDConfig` parameters
- Modify Q-Learning settings
- Integrate custom features
- Export Q-values for analysis

---

## 🚀 What's New in v2.0

- ✅ **FSD-only** - Removed BOT and Supervised modes (50% smaller codebase)
- ✅ **Custom engine** - Eliminated BackTrader dependency
- ✅ **Simplified GUI** - Single focused interface
- ✅ **Better performance** - Optimized for FSD
- ✅ **Cleaner code** - 23,000 lines vs 46,000 lines

---

## 📞 Support

- **Errors?** Check logs (if logging is enabled)
- **IBKR Setup?** See `IBKR_REQUIREMENTS_CHECKLIST.md`
- **FSD Questions?** Read `docs/FSD_COMPLETE_GUIDE.md`
- **Recent Improvements?** See `CODE_REVIEW_FIXES_IMPLEMENTATION_COMPLETE.md`
- **Code Development?** See `CLAUDE.md` for developer guidelines

---

## 📚 Documentation Index

| Document | Purpose | Audience |
|----------|---------|----------|
| `README.md` | Project overview and quick start | Everyone |
| `START_HERE.md` | Step-by-step setup guide | New users |
| `IBKR_REQUIREMENTS_CHECKLIST.md` | IBKR connection setup | Live trading users |
| `docs/FSD_COMPLETE_GUIDE.md` | FSD deep dive & implementation | Advanced users |
| `CODE_REVIEW_FIXES_IMPLEMENTATION_COMPLETE.md` | Recent improvements (Oct 30, 2025) | Developers & advanced users |
| `CLAUDE.md` | Developer guide & codebase instructions | Developers |

---

**Ready to trade? Launch FSD mode now:**
```bash
python -m aistock
```

🎯 **Let the AI trade for you!** 🚀
