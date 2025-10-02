# AiStock Trading Bot - Operational Runbook

## Table of Contents
1. [Quick Reference](#quick-reference)
2. [Deployment](#deployment)
3. [Monitoring](#monitoring)
4. [Common Operations](#common-operations)
5. [Incident Response](#incident-response)
6. [Disaster Recovery](#disaster-recovery)
7. [Maintenance](#maintenance)

---

## Quick Reference

### Health Check Endpoints
- **Health Status**: `http://localhost:9090/health`
- **Metrics**: `http://localhost:9090/metrics` (Prometheus format)
- **Detailed Status**: `http://localhost:9090/status`
- **Ping**: `http://localhost:9090/ping`

### Critical Files
- **State File**: `data/bot_state.json`
- **State Backups**: `data/backups/`
- **Database**: `data/trading_bot.db`
- **Logs**: `logs/app.log`, `logs/error_logs/errors.log`
- **Config**: `config/settings.py`, `.env`

### Emergency Contacts
- **On-Call Engineer**: [TO BE FILLED]
- **Backup Contact**: [TO BE FILLED]
- **IBKR Support**: [TO BE FILLED]

---

## Deployment

### Prerequisites
1. **Python**: 3.9+
2. **TWS/IB Gateway**: Running and connected
3. **Dependencies**: All packages in `requirements.txt`

### Pre-Deployment Checklist
- [ ] Code passes all tests (`pytest --cov=.`)
- [ ] Type checking passes (`mypy .`)
- [ ] Security scan passes (`safety check`, `bandit -r .`)
- [ ] Configuration reviewed and validated
- [ ] Credentials properly encrypted
- [ ] Paper trading tested for 2+ weeks
- [ ] All metrics/alerts configured

### Deployment Steps

#### 1. Environment Setup
```bash
# Clone repository
git clone <repository_url>
cd AiStock

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For testing
```

#### 2. Configuration
```bash
# Copy environment template
cp .env.example .env

# Generate Fernet encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Edit .env file
# Add FERNET_KEY, IBKR credentials, etc.
nano .env
```

#### 3. Initialize Database
```bash
# Database is automatically created on first run
# To verify:
python -c "from database.models import DatabaseManager; db = DatabaseManager(); print('DB initialized')"
```

#### 4. Configuration Mode Selection

**Autonomous Mode** (Simple - 3 parameters):
```bash
python main.py
# When prompted, enter:
# 1. Max Capital (e.g., 10000)
# 2. Timeframe (e.g., "5 mins")
# 3. Symbols (e.g., "BTC/USD, ETH/USD")
```

**Expert Mode** (Full control - 167 parameters):
```bash
# Edit config/settings.py
# Set TRADING_MODE_TYPE = 'expert'
# Configure all parameters manually
python main.py
```

#### 5. Start Bot
```bash
# Paper trading first!
python main.py

# In separate terminal, verify health
curl http://localhost:9090/health
```

#### 6. Monitor Initial Run
```bash
# Watch logs
tail -f logs/app.log

# Check metrics
curl http://localhost:9090/metrics

# Detailed status
curl http://localhost:9090/status | jq
```

---

## Monitoring

### Health Status Interpretation

| Status | Meaning | Action Required |
|--------|---------|-----------------|
| `healthy` | All systems operational | None - routine monitoring |
| `degraded` | Trading halted but operational | Investigate why trading halted |
| `unhealthy` | Bot stopped or API disconnected | **IMMEDIATE ACTION REQUIRED** |

### Key Metrics to Monitor

#### System Health
- **bot_running**: Should be `1`
- **api_connected**: Should be `1`
- **trading_halted**: Should be `0`
- **last_heartbeat**: Should be < 120 seconds ago

#### Performance Metrics
- **total_equity**: Current account value
- **daily_pnl**: Today's profit/loss
- **open_positions**: Number of open positions
- **win_rate**: Percentage of winning trades
- **sharpe_ratio**: Risk-adjusted returns

#### System Metrics
- **circuit_breaker_state**: Should be `closed`
- **backup_count**: Number of state backups
- **last_backup_time**: Should be recent

### Alerting Rules

**Critical Alerts** (Page immediately):
```yaml
- api_connected == 0 for > 5 minutes
- bot_running == 0
- daily_pnl < -MAX_DAILY_LOSS
- drawdown > MAX_DRAWDOWN_LIMIT
- circuit_breaker_state == 'open' for > 10 minutes
```

**Warning Alerts** (Notify):
```yaml
- win_rate < 0.4 for > 24 hours
- sharpe_ratio < 0.5 for > 7 days
- last_backup_time > 1 hour
- trading_halted == 1
```

---

## Common Operations

### Viewing Current Status
```bash
# Quick health check
curl http://localhost:9090/health

# Detailed status
curl http://localhost:9090/status | jq

# View logs
tail -f logs/app.log

# View errors only
tail -f logs/error_logs/errors.log
```

### Checking Trade History
```bash
# Via database
sqlite3 data/trading_bot.db "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;"

# Via logs
grep "Trade executed" logs/app.log | tail -20
```

### Viewing Parameter Changes
```bash
# Check AI parameter modifications
sqlite3 data/trading_bot.db "SELECT * FROM parameter_history ORDER BY timestamp DESC LIMIT 10;"
```

### Viewing Optimization Runs
```bash
# Check AI optimization history
sqlite3 data/trading_bot.db "SELECT * FROM optimization_runs ORDER BY timestamp DESC LIMIT 5;"
```

### Listing Backups
```bash
# List available backups
ls -lah data/backups/

# View backup metadata
cat data/backups/backup_metadata.json | jq
```

### Restoring from Backup
```python
from persistence.backup_manager import BackupManager

bm = BackupManager('data/bot_state.json')

# List backups
backups = bm.list_backups()
for b in backups[:5]:
    print(f"{b['timestamp']}: {b['filename']}")

# Restore latest
bm.auto_restore_latest()

# Or restore specific backup
bm.restore_backup('data/backups/state_backup_20250102_120000.json')
```

### Switching Trading Modes
```bash
# Stop bot first
# Edit config/settings.py
# Change TRADING_MODE_TYPE = 'autonomous' or 'expert'
# Restart bot
```

### Resetting Circuit Breaker
```python
# If circuit breaker is stuck open
from api.circuit_breaker_wrapper import CircuitBreakerManager

cbm = CircuitBreakerManager()
cbm.reset_all()
```

---

## Incident Response

### Bot Stopped Unexpectedly

**Symptoms**: `bot_running == 0`, no recent logs

**Actions**:
1. Check system resources: `top`, `df -h`
2. Check for Python errors: `tail -100 logs/error_logs/errors.log`
3. Check system logs: `journalctl -u trading-bot` (if running as service)
4. Restart bot: `python main.py`
5. Monitor health: `curl http://localhost:9090/health`

### API Disconnected

**Symptoms**: `api_connected == 0`

**Actions**:
1. Check TWS/Gateway is running
2. Check network connectivity: `ping <tws_host>`
3. Check IBKR credentials in `.env`
4. Check TWS/Gateway port settings
5. Restart TWS/Gateway if needed
6. Bot should auto-reconnect (check logs)

### Trading Halted

**Symptoms**: `trading_halted == 1`

**Investigate**:
1. Check if daily loss limit hit: `curl http://localhost:9090/status | jq '.portfolio.daily_pnl'`
2. Check if drawdown limit hit: `curl http://localhost:9090/status | jq '.performance.max_drawdown'`
3. Check risk manager logs: `grep "Trading halted" logs/app.log`

**Recovery**:
- If limits hit: Normal operation, wait for next trading day
- If false trigger: Restart bot

### Circuit Breaker Open

**Symptoms**: `circuit_breaker_state == 'open'`

**Actions**:
1. Identify which breaker is open: Check logs
2. Investigate root cause (API failures, network issues)
3. Fix underlying issue
4. Wait for recovery timeout (60 seconds) OR manually reset
5. Monitor for repeated failures

### High Loss Rate

**Symptoms**: `win_rate < 0.4`, negative daily PnL

**Actions**:
1. **STOP TRADING IMMEDIATELY** if losses exceed comfort level
2. Review recent trades: `sqlite3 data/trading_bot.db "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 20;"`
3. Check market conditions (high volatility, news events)
4. Review AI optimization history
5. Consider switching to paper trading
6. Analyze strategy performance: Check which strategies are losing
7. May need to retrain ML models or adjust parameters

### Database Corruption

**Symptoms**: Database errors in logs

**Recovery**:
1. Stop bot
2. Backup corrupted database: `cp data/trading_bot.db data/trading_bot.db.corrupt`
3. Restore from latest backup
4. Verify data integrity
5. Restart bot

---

## Disaster Recovery

### Complete System Failure

**Recovery Steps**:

1. **Assess Damage**
   ```bash
   # Check what's available
   ls -lah data/
   ls -lah data/backups/
   ```

2. **Restore State**
   ```python
   from persistence.backup_manager import BackupManager
   bm = BackupManager('data/bot_state.json')
   bm.auto_restore_latest()
   ```

3. **Verify State**
   ```bash
   # Check restored state
   cat data/bot_state.json | jq
   ```

4. **Reconcile with Broker**
   ```python
   # Bot will auto-reconcile on startup
   # But verify manually:
   # - Open positions match
   # - Account value matches
   # - Pending orders match
   ```

5. **Resume Operations**
   ```bash
   # Start in paper trading mode first
   # Edit settings: DATA_SOURCE = 'paper'
   python main.py

   # Monitor for 1 hour
   # If stable, switch to live
   ```

### Data Loss Scenarios

| Lost Data | Recovery Method | Impact |
|-----------|-----------------|--------|
| bot_state.json | Restore from backup | Minimal - auto-reconciles |
| trading_bot.db | Cannot recover trade history | Historical data lost only |
| Backup directory | Cannot recover | Must reconcile manually with broker |
| Entire data/ | High impact | Manual position reconciliation required |

### Manual Position Reconciliation

If all state is lost:

```python
# 1. Get current positions from IBKR
# Bot does this automatically on startup

# 2. Verify against IBKR web portal
# https://www.interactivebrokers.com/portal

# 3. Manually close unexpected positions if needed

# 4. Reset state and continue
```

---

## Maintenance

### Daily Tasks
- [ ] Check health endpoint: `curl http://localhost:9090/health`
- [ ] Review error logs: `tail -50 logs/error_logs/errors.log`
- [ ] Verify trading performance: Check daily PnL
- [ ] Monitor win rate and Sharpe ratio

### Weekly Tasks
- [ ] Review optimization runs: Check if AI is improving performance
- [ ] Analyze trade history: Look for patterns
- [ ] Review parameter changes: Ensure AI isn't making erratic changes
- [ ] Database maintenance: `sqlite3 data/trading_bot.db "VACUUM;"`
- [ ] Backup cleanup: Verify old backups are being rotated

### Monthly Tasks
- [ ] Update dependencies: `pip list --outdated`
- [ ] Security scan: `safety check`, `bandit -r .`
- [ ] Review strategy performance: Disable underperforming strategies
- [ ] ML model retraining: Verify auto-retraining is working
- [ ] Performance review: Compare to benchmark

### Quarterly Tasks
- [ ] Code review: Check for technical debt
- [ ] Infrastructure review: Optimize system resources
- [ ] Disaster recovery drill: Test backup/restore procedures
- [ ] Documentation update: Keep runbook current

### Log Rotation
```bash
# Logs grow over time, rotate them
logrotate -f /etc/logrotate.d/trading-bot

# Or manually
cd logs
gzip app.log && mv app.log.gz "app_$(date +%Y%m%d).log.gz"
touch app.log
```

### Database Backup
```bash
# Backup database (in addition to automatic state backups)
sqlite3 data/trading_bot.db ".backup data/trading_bot_backup_$(date +%Y%m%d).db"

# Keep last 30 days
find data/ -name "trading_bot_backup_*.db" -mtime +30 -delete
```

### Dependency Updates
```bash
# Check for updates
pip list --outdated

# Update specific package
pip install --upgrade <package_name>

# Update requirements.txt
pip freeze > requirements.txt

# Test thoroughly before deploying
pytest --cov=.
```

---

## Performance Tuning

### Optimization Schedule
- **Parameter Optimization**: Every 24 hours or 50 trades
- **Strategy Selection**: Every 6 hours
- **Position Sizing**: Every 20 trades
- **ML Retraining**: Weekly or if win rate < 48%

### AI Optimization Bounds (Safety Limits)
```python
# These CANNOT be modified by AI:
MAX_DAILY_LOSS = 3%
MAX_DRAWDOWN_LIMIT = 15%
TOTAL_CAPITAL = [User Set]

# These CAN be optimized by AI:
RISK_PER_TRADE: 0.5% - 2%
STOP_LOSS_ATR_MULTIPLIER: 1.0 - 4.0
TAKE_PROFIT_RR_RATIO: 1.5 - 4.0
RSI_PERIOD: 5 - 30
MA Periods: Various ranges
```

---

## Troubleshooting

### Bot Starts But No Trades
1. Check if trading is halted: `curl http://localhost:9090/status | jq '.trading.halted'`
2. Check if strategies are enabled: `grep "enabled" logs/app.log`
3. Check if signals are being generated: `grep "Signal" logs/app.log`
4. Verify market is open: Check exchange hours
5. Check risk limits: May be too conservative

### High Memory Usage
1. Check max bars in memory: `SETTINGS.MAX_BARS_IN_MEMORY`
2. Reduce to 1000-2000 bars
3. Restart bot

### Slow Performance
1. Profile hot paths: `python -m cProfile main.py`
2. Check database size: `du -h data/trading_bot.db`
3. Optimize queries or vacuum database
4. Check for memory leaks: Monitor over time

---

## Appendix

### File Structure
```
AiStock/
├── ai_controller/          # NEW: Autonomous AI optimization
│   ├── autonomous_optimizer.py
│   └── mode_manager.py
├── api/                    # IBKR API integration
├── config/                 # Configuration
│   ├── autonomous_config.py  # NEW: Simplified config
│   └── settings.py
├── database/               # NEW: Trade persistence
│   └── models.py
├── monitoring/             # NEW: Health checks & metrics
│   ├── health_check.py
│   └── metrics.py
├── persistence/            # State management
│   ├── backup_manager.py   # NEW: Versioned backups
│   └── state_manager.py
├── security/               # Security features
├── strategies/             # Trading strategies
└── main.py                # Main entry point
```

### Useful Commands Cheat Sheet
```bash
# Health
curl http://localhost:9090/health

# Status
curl http://localhost:9090/status | jq

# Trades
sqlite3 data/trading_bot.db "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;"

# Performance
sqlite3 data/trading_bot.db "SELECT * FROM performance_metrics ORDER BY date DESC LIMIT 5;"

# Parameters
sqlite3 data/trading_bot.db "SELECT * FROM parameter_history ORDER BY timestamp DESC LIMIT 10;"

# Logs
tail -f logs/app.log
grep ERROR logs/error_logs/errors.log

# Backups
ls -lah data/backups/

# Stop bot
pkill -f "python main.py"

# Restart bot
python main.py &
```

---

## Emergency Procedures

### STOP TRADING IMMEDIATELY
```python
# Method 1: Via code
from main import TradingBot
bot.halt_trading(reason="Emergency stop")

# Method 2: Kill process
pkill -f "python main.py"

# Method 3: Disable in TWS/Gateway
# Log into TWS, cancel all orders, close positions
```

### CLOSE ALL POSITIONS
```python
# Emergency position closure
from main import TradingBot
bot.close_all_positions(reason="Emergency closure")
```

---

**Last Updated**: 2025-01-02
**Version**: 1.0
**Maintained By**: [TO BE FILLED]
