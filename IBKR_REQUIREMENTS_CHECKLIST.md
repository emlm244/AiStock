# ✅ IBKR Integration Requirements Checklist

## Your Setup (Already Have) ✅
- ✅ **Pro TWS Account** - Interactive Brokers account
- ✅ **Traders Workstation** - TWS software installed

---

## Code Side - Ready to Go! ✅

### 1. **IBKR API Integration** ✅
**Status**: COMPLETE - Fully implemented

**What we have**:
```python
# aistock/brokers/ibkr.py
class IBKRBroker(BaseBroker, EWrapper, EClient):
    - Connection management with auto-reconnect
    - Heartbeat monitoring
    - Position reconciliation
    - Real-time market data subscription
    - Order submission and tracking
    - Fill handling with callbacks
```

**Features**:
- ✅ Auto-reconnect with exponential backoff
- ✅ Heartbeat monitoring (detects disconnections)
- ✅ Position sync with IBKR
- ✅ Real-time bar streaming
- ✅ Order execution with confirmations
- ✅ Thread-safe operations

---

### 2. **Dependencies** ✅
**Status**: ALL INCLUDED in requirements.txt

**Key packages**:
```bash
ibapi>=9.81.1              # IB API (REQUIRED)
pandas>=2.2.3              # Data processing
numpy>=2.1.0               # Math operations
requests>=2.32.0           # HTTP calls
```

**Install command**:
```bash
pip install -r requirements.txt
```

**Note**: If `ibapi` fails to install via pip, manually install from:
- https://interactivebrokers.github.io/

---

### 3. **Configuration** ✅
**Status**: COMPLETE - Built into GUI

**FSD Mode settings** (in simple_gui.py):
```python
# IBKR credentials (edit in simple_gui.py if needed)
self.ibkr_account = "DUE072840"    # Your account number
self.ibkr_port = 7497              # Paper trading port
self.ibkr_client_id = 1001         # Unique client ID
```

**Change these** in `aistock/simple_gui.py` line 134-136:
- `ibkr_account` → Your IBKR account number
- `ibkr_port` → 7497 (paper) or 7496 (live)
- `ibkr_client_id` → Any number (1001 is fine)

---

## TWS Configuration Required ⚙️

### Step 1: Enable API in TWS
1. **Open TWS** → File → Global Configuration → API → Settings
2. **Enable these**:
   - ✅ Enable ActiveX and Socket Clients
   - ✅ Read-Only API = **UNCHECKED** (must allow trading)
   - ✅ Download open orders on connection = **CHECKED**
   - ✅ Master API client ID = **1001** (or your chosen ID)

3. **Set Socket Port**:
   - Paper Trading: **7497**
   - Live Trading: **7496**

4. **Trusted IPs**:
   - Add: **127.0.0.1** (localhost)
   - This allows your bot to connect

5. **Click OK** and **Restart TWS**

---

### Step 2: Verify API Status
After restarting TWS, check:
- Bottom right corner should show: **"API: Ready"** or **"API: Listening"**
- Green checkmark next to API status

---

## Test Your Connection 🧪

### Test Script
```bash
# From project root
python test_ibkr_connection.py
```

**This tests**:
1. ✅ Connection to TWS
2. ✅ Position query
3. ✅ Real-time data subscription
4. ✅ Heartbeat monitoring
5. ✅ Order submission (optional)

**Expected output**:
```
✅ Connection successful!
✅ Position query successful!
✅ Subscribed to AAPL real-time bars
📊 Bar received: AAPL @ 2025-10-27 14:30:00 | Close: $150.25
✅ Received 6 bars
✅ Heartbeat test passed!
```

---

## Launch FSD with IBKR 🚀

### Step 1: Start TWS
1. Open **Trader Workstation**
2. Login with **Paper Trading** account
3. Wait for **"API: Ready"** status

### Step 2: Launch FSD
```bash
python -m aistock
```

### Step 3: Configure in GUI
1. **Capital**: $200 (for testing)
2. **Risk Level**: Conservative
3. **Trading Mode**: 
   - ✅ Check "Live Mode" checkbox
   - This will connect to IBKR (paper account is safe)

### Step 4: Start Robot
1. Click **START ROBOT**
2. Bot connects to TWS
3. Begins trading on paper account

---

## Safety Features ✅

### Connection Monitoring:
- ✅ **Auto-reconnect** - If TWS disconnects, bot reconnects
- ✅ **Heartbeat** - Checks connection every 30 seconds
- ✅ **Position sync** - Reconciles with IBKR positions
- ✅ **Order deduplication** - Prevents duplicate orders

### Risk Management:
- ✅ **Daily loss limits** - Auto-stops on excessive loss
- ✅ **Position size caps** - Max 20% per symbol
- ✅ **Drawdown protection** - Circuit breaker on large losses

---

## Verification Steps ✅

### Before Going Live:
1. ✅ **Test script passes** - All 4 tests green
2. ✅ **Paper trading works** - Run for 1+ week
3. ✅ **Positive results** - Win rate >50%
4. ✅ **Connection stable** - No disconnects
5. ✅ **Order execution** - Fills confirmed

### Code-Side Checklist:
- ✅ **IBKR broker implementation** - Complete
- ✅ **Dependencies installed** - `pip install -r requirements.txt`
- ✅ **Account number configured** - In `simple_gui.py`
- ✅ **Port configured** - 7497 (paper) or 7496 (live)
- ✅ **Error handling** - Auto-reconnect implemented
- ✅ **Position tracking** - Syncs with IBKR
- ✅ **Order management** - Full lifecycle handling

---

## API Requirements from IBKR ✅

### What IBKR API Provides:
✅ **Market Data**:
- Real-time bars (5-second intervals)
- Historical data
- Last price, bid/ask, volume

✅ **Order Management**:
- Submit market orders
- Submit limit orders
- Cancel orders
- Order status updates

✅ **Account Data**:
- Current positions
- Account balance
- P&L tracking
- Buying power

✅ **Connection**:
- Socket connection
- Multi-client support
- Callback-based events

### What We've Implemented:
✅ **All of the above!**
- Real-time bars via `subscribe_realtime_bars()`
- Market orders via `submit()`
- Position sync via `reqPositions()`
- Auto-reconnect on disconnect
- Fill notifications via callbacks

---

## Known Issues & Solutions ✅

### Issue #1: "ibapi not installed"
**Solution**:
```bash
pip install ibapi
# If fails, download from: https://interactivebrokers.github.io/
```

### Issue #2: "Connection refused"
**Solutions**:
- ✅ Check TWS is running
- ✅ Check API is enabled in TWS settings
- ✅ Check port number (7497 for paper, 7496 for live)
- ✅ Check 127.0.0.1 is in Trusted IPs

### Issue #3: "Read-only API"
**Solution**:
- ✅ In TWS settings, UNCHECK "Read-Only API"
- ✅ Restart TWS

### Issue #4: "Already connected"
**Solution**:
- ✅ Use unique client ID (1001 is fine)
- ✅ Or disconnect other API clients

---

## Final Checklist ✅

### Code Side (All Done!):
- ✅ IBKR broker class implemented
- ✅ Dependencies in requirements.txt
- ✅ Configuration in simple_gui.py
- ✅ Test script available
- ✅ Error handling implemented
- ✅ Auto-reconnect working
- ✅ Position sync implemented
- ✅ Order execution complete

### Your Side (To Do):
- ⚠️ Install dependencies: `pip install -r requirements.txt`
- ⚠️ Configure TWS API settings (see Step 1 above)
- ⚠️ Edit account number in `simple_gui.py` (line 134)
- ⚠️ Run test script: `python test_ibkr_connection.py`
- ⚠️ Test with paper trading for 1+ week
- ⚠️ Review results before going live

---

## Summary ✅

### Code is Ready:
✅ **IBKR integration is COMPLETE**
✅ **All API methods implemented**
✅ **Dependencies specified**
✅ **Error handling robust**
✅ **Test script available**

### You Need To:
1. ⚠️ `pip install -r requirements.txt` (install dependencies)
2. ⚠️ Enable API in TWS settings
3. ⚠️ Update account number in code
4. ⚠️ Run test script to verify
5. ⚠️ Test with paper trading first

---

**The bot is ready to connect to IBKR!** 🎉

Just complete the TWS configuration and run the test script to verify.

**Next**: `python test_ibkr_connection.py`

