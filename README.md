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
├── runtime_settings.py # Runtime .env parsing for GUI/IBKR
├── session/            # Live trading orchestration (modular)
│   ├── coordinator.py  # Orchestrates trading flow
│   ├── bar_processor.py
│   ├── analytics_reporter.py
│   ├── checkpointer.py
│   └── reconciliation.py
├── ml/                 # Advanced RL algorithms (NEW)
│   ├── buffers/        # Experience replay (uniform, PER)
│   ├── networks/       # Neural networks (Dueling, LSTM, Transformer)
│   └── agents/         # RL agents (Double Q, DQN, Sequential)
├── engines/            # Decision engine implementations (NEW)
├── portfolio.py        # Position tracking
├── risk.py             # Risk management
├── stop_control.py     # Manual/EOD stop handling
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

- **IBKR_REQUIREMENTS_CHECKLIST.md** - IBKR connection setup
- **docs/FSD_COMPLETE_GUIDE.md** - FSD technical deep dive
- **CLAUDE.md** - Developer guide for working with the codebase

---

## 🔒 Risk Disclaimer

**Trading involves risk of loss. Past performance does not guarantee future results.**

⚠️ **IMPORTANT**: Always start with paper trading and use extreme caution with live trading.

**Before trading with real money:**
1. Run paper trading successfully for 1-2 weeks
2. Review `docs/FSD_COMPLETE_GUIDE.md` for implementation details
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
- **NumPy/Pandas** - Math operations
- **PyTorch** - Deep learning (optional, for advanced RL)
- **Custom Engine** - No BackTrader dependency
- **Q-Learning** - Reinforcement learning algorithm
- **Advanced RL** - Double Q-Learning, PER, Dueling DQN, LSTM/Transformer

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
- Enable advanced RL: `engine_type='dueling'` or `'transformer'`
- Use GPU acceleration: `device='cuda'`
- Export Q-values for analysis

---

## 🚀 What's New in v2.0

- ✅ **FSD-only** - Removed BOT and Supervised modes (50% smaller codebase)
- ✅ **Custom engine** - Eliminated BackTrader dependency
- ✅ **Simplified GUI** - Single focused interface
- ✅ **Better performance** - Optimized for FSD
- ✅ **Cleaner code** - 23,000 lines vs 46,000 lines

## 🧠 Advanced RL Algorithms (New!)

Enable state-of-the-art reinforcement learning:

| Algorithm | Benefit |
|-----------|---------|
| **Double Q-Learning** | Reduces overestimation bias |
| **Prioritized Experience Replay** | Learns from important trades |
| **Dueling DQN** | Better value estimation |
| **LSTM/Transformer** | Captures temporal patterns |

```python
# Enable in FSDConfig
config = FSDConfig(
    engine_type='dueling',    # Use neural network
    enable_per=True,          # Prioritized replay
    device='cuda',            # GPU acceleration
)
```

See `CLAUDE.md` for detailed configuration options.

---

## 📞 Support

- **Errors?** Check logs (if logging is enabled)
- **IBKR Setup?** See `IBKR_REQUIREMENTS_CHECKLIST.md`
- **FSD Questions?** Read `docs/FSD_COMPLETE_GUIDE.md`
- **Code Development?** See `CLAUDE.md` for developer guidelines

---

## 📚 Documentation Index

| Document | Purpose | Audience |
|----------|---------|----------|
| `README.md` | Project overview and quick start | Everyone |
| `IBKR_REQUIREMENTS_CHECKLIST.md` | IBKR connection setup | Live trading users |
| `docs/FSD_COMPLETE_GUIDE.md` | FSD deep dive & implementation | Advanced users |
| `CLAUDE.md` | Developer guide & codebase instructions | Developers |

---

**Ready to trade? Launch FSD mode now:**
```bash
python -m aistock
```

🎯 **Let the AI trade for you!** 🚀
