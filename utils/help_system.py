# utils/help_system.py

"""
Beginner-Friendly Help System

Provides context-sensitive help and guidance for users.
"""


class HelpSystem:
    """Interactive help system for beginners"""

    @staticmethod
    def display_main_help():
        """Display main help menu"""
        print('\n' + '=' * 70)
        print(' 📖 AIStocker Help System')
        print('=' * 70 + '\n')

        print('Available Help Topics:\n')
        print('  1. Getting Started')
        print('  2. Configuration Guide')
        print('  3. Risk Management')
        print('  4. Trading Modes')
        print('  5. Troubleshooting')
        print('  6. FAQ')
        print('  7. Emergency Procedures')
        print('  8. Back to Main Menu\n')

        choice = input('Select a topic (1-8): ').strip()

        if choice == '1':
            HelpSystem.show_getting_started()
        elif choice == '2':
            HelpSystem.show_configuration_guide()
        elif choice == '3':
            HelpSystem.show_risk_management()
        elif choice == '4':
            HelpSystem.show_trading_modes()
        elif choice == '5':
            HelpSystem.show_troubleshooting()
        elif choice == '6':
            HelpSystem.show_faq()
        elif choice == '7':
            HelpSystem.show_emergency_procedures()

    @staticmethod
    def show_getting_started():
        """Display getting started guide"""
        print('\n' + '=' * 70)
        print(' 🚀 Getting Started with AIStocker')
        print('=' * 70 + '\n')

        print('Prerequisites:')
        print('  1. Interactive Brokers account (paper or live)')
        print('  2. TWS (Trader Workstation) or IB Gateway installed and running')
        print('  3. API enabled in TWS (File > Global Configuration > API > Settings)')
        print('  4. Python 3.9+ with required packages installed\n')

        print('First-Time Setup:')
        print('  1. Configure config/credentials.py with your:')
        print('     • ACCOUNT_ID (from TWS: Account > Account Info)')
        print('     • TWS_PORT (7497 for paper, 7496 for live)')
        print("     • TWS_HOST (usually '127.0.0.1')\n")

        print('  2. Review config/settings.py:')
        print("     • Set TRADING_MODE ('stock', 'crypto', or 'forex')")
        print('     • Configure TRADE_INSTRUMENTS (symbols to trade)')
        print('     • Set risk limits (RISK_PER_TRADE, MAX_DAILY_LOSS, etc.)\n')

        print('  3. Start with paper trading!')
        print('     • Always test with paper account first')
        print('     • Port 7497 = TWS Paper Trading')
        print('     • Port 4002 = IB Gateway Paper Trading\n')

        print('Running the Bot:')
        print('  python main.py\n')

        print('For detailed documentation, see: CLAUDE.md\n')
        input('Press Enter to continue...')

    @staticmethod
    def show_configuration_guide():
        """Display configuration guide"""
        print('\n' + '=' * 70)
        print(' ⚙️  Configuration Guide')
        print('=' * 70 + '\n')

        print('Key Configuration Files:\n')

        print('1. config/credentials.py (DO NOT COMMIT TO GIT)')
        print('   IBKR = {')
        print("       'ACCOUNT_ID': 'YOUR_ACCOUNT_ID',    # From TWS")
        print("       'TWS_HOST': '127.0.0.1',            # Usually localhost")
        print("       'TWS_PORT': 7497,                   # 7497=paper, 7496=live")
        print("       'CLIENT_ID': 1,                     # Usually 1")
        print('   }\n')

        print('2. config/settings.py - Main Configuration\n')

        print('   Trading Configuration:')
        print("   • TRADING_MODE: 'stock', 'crypto', or 'forex'")
        print("   • TRADE_INSTRUMENTS: ['BTC/USD', 'ETH/USD'] or ['AAPL', 'MSFT']")
        print("   • TIMEFRAME: '30 secs', '5 mins', '1 hour', etc.\n")

        print('   Risk Management (IMPORTANT!):')
        print('   • RISK_PER_TRADE: 0.01 = 1% of capital per trade')
        print('   • MAX_DAILY_LOSS: 0.03 = Stop trading if lose 3% in a day')
        print('   • MAX_DRAWDOWN_LIMIT: 0.15 = Stop if drawdown reaches 15%\n')

        print('   Stop Loss / Take Profit:')
        print("   • STOP_LOSS_TYPE: 'PERCENT' or 'ATR'")
        print('   • STOP_LOSS_PERCENT: 0.005 = 0.5% below entry')
        print('   • STOP_LOSS_ATR_MULTIPLIER: 2.0 = 2x ATR distance\n')

        print("   • TAKE_PROFIT_TYPE: 'PERCENT', 'ATR', or 'RATIO'")
        print('   • TAKE_PROFIT_RR_RATIO: 2.0 = 2:1 risk/reward\n')

        print('Recommended Beginner Settings:')
        print('  • Start with RISK_PER_TRADE = 0.005 (0.5%)')
        print("  • Use STOP_LOSS_TYPE = 'PERCENT' for simplicity")
        print("  • Set TAKE_PROFIT_TYPE = 'RATIO' with RR = 2.0")
        print('  • Enable AUTONOMOUS_MODE = False initially\n')

        input('Press Enter to continue...')

    @staticmethod
    def show_risk_management():
        """Display risk management guide"""
        print('\n' + '=' * 70)
        print(' 🛡️  Risk Management Guide')
        print('=' * 70 + '\n')

        print('Understanding Risk Parameters:\n')

        print('1. RISK_PER_TRADE (Default: 0.01 = 1%)')
        print('   • Controls position size')
        print('   • 1% means you risk 1% of capital on each trade')
        print('   • Example: $10,000 capital, 1% risk = $100 max loss per trade')
        print('   • Recommended: 0.005-0.02 (0.5%-2%)\n')

        print('2. MAX_DAILY_LOSS (Default: 0.03 = 3%)')
        print('   • Bot stops trading if daily loss exceeds this')
        print('   • Resets at midnight in your timezone')
        print('   • Prevents catastrophic losses from bad days')
        print('   • Recommended: 0.02-0.05 (2%-5%)\n')

        print('3. MAX_DRAWDOWN_LIMIT (Default: 0.15 = 15%)')
        print('   • Bot stops if equity drops this % from peak')
        print('   • Only resumes when drawdown recovers')
        print('   • Protects long-term capital')
        print('   • Recommended: 0.10-0.20 (10%-20%)\n')

        print('Risk Layering (Defense in Depth):')
        print('  • Per-Trade Risk: Limits individual trade damage')
        print('  • Daily Loss Limit: Prevents bad trading days')
        print('  • Drawdown Limit: Protects overall capital')
        print('  • All three work together for maximum protection\n')

        print('Best Practices:')
        print('  • Never risk more than 2% per trade')
        print('  • Daily loss should be 2-5x per-trade risk')
        print('  • Drawdown limit should be 5-10x per-trade risk')
        print('  • Always use stop losses on every trade')
        print('  • Start small and increase gradually\n')

        input('Press Enter to continue...')

    @staticmethod
    def show_trading_modes():
        """Display trading modes guide"""
        print('\n' + '=' * 70)
        print(' 📊 Trading Modes Guide')
        print('=' * 70 + '\n')

        print('Available Modes:\n')

        print('1. STOCK MODE')
        print('   • Trades US stocks')
        print("   • Instrument format: 'AAPL', 'MSFT', 'SPY'")
        print('   • Market hours: 9:30 AM - 4:00 PM ET')
        print('   • Extended hours available with CONTINUE_AFTER_CLOSE=True')
        print("   • Example instruments: ['AAPL', 'MSFT', 'GOOGL']\n")

        print('2. CRYPTO MODE')
        print('   • Trades cryptocurrency pairs')
        print("   • Instrument format: 'BTC/USD', 'ETH/USD'")
        print('   • 24/7 trading')
        print('   • Higher volatility - use wider stops')
        print("   • Example instruments: ['BTC/USD', 'ETH/USD']\n")

        print('3. FOREX MODE')
        print('   • Trades currency pairs')
        print("   • Instrument format: 'EUR/USD', 'GBP/USD'")
        print('   • Sunday 5 PM ET - Friday 5 PM ET')
        print('   • Lower volatility - use tighter stops')
        print("   • Example instruments: ['EUR/USD', 'GBP/USD', 'USD/JPY']\n")

        print('Choosing the Right Mode:')
        print('  • Beginners: Start with STOCK mode (more predictable hours)')
        print('  • Tech-savvy: CRYPTO mode (24/7, high volatility)')
        print('  • Experienced: FOREX mode (requires deep understanding)\n')

        input('Press Enter to continue...')

    @staticmethod
    def show_troubleshooting():
        """Display troubleshooting guide"""
        print('\n' + '=' * 70)
        print(' 🔧 Troubleshooting Common Issues')
        print('=' * 70 + '\n')

        print('Problem: Cannot connect to TWS/Gateway\n')
        print('Solutions:')
        print('  1. Verify TWS or IB Gateway is running')
        print('  2. Check TWS API is enabled:')
        print('     File > Global Configuration > API > Settings')
        print('     ✓ Enable ActiveX and Socket Clients')
        print('     ✓ Read-Only API: OFF')
        print('  3. Verify port number in credentials.py matches TWS:')
        print('     • 7497 = TWS Paper Trading')
        print('     • 7496 = TWS Live Trading')
        print('     • 4002 = Gateway Paper Trading')
        print('     • 4001 = Gateway Live Trading')
        print("  4. Check firewall isn't blocking connection")
        print('  5. Restart TWS and try again\n')

        print('-' * 70 + '\n')

        print('Problem: Orders are rejected\n')
        print('Solutions:')
        print('  1. Verify account has sufficient funds')
        print('  2. Check market is open for the instrument')
        print('  3. Verify instrument symbol is correct')
        print('  4. Check order quantity meets minimum requirements')
        print('  5. Review error logs: logs/error_logs/errors.log\n')

        print('-' * 70 + '\n')

        print('Problem: No market data received\n')
        print('Solutions:')
        print('  1. Verify you have market data subscriptions in TWS')
        print('  2. Check instrument symbol spelling')
        print('  3. Ensure market is open')
        print('  4. Try canceling and resubscribing to data')
        print('  5. Restart TWS and the bot\n')

        print('-' * 70 + '\n')

        print('Problem: Bot stops unexpectedly\n')
        print('Solutions:')
        print('  1. Check logs/error_logs/errors.log for errors')
        print('  2. Check if risk limits were hit (daily loss/drawdown)')
        print('  3. Verify system resources (memory, disk space)')
        print("  4. Check TWS connection didn't drop")
        print('  5. Review emergency shutdown log: logs/emergency_shutdowns.log\n')

        input('Press Enter to continue...')

    @staticmethod
    def show_faq():
        """Display FAQ"""
        print('\n' + '=' * 70)
        print(' ❓ Frequently Asked Questions')
        print('=' * 70 + '\n')

        print('Q: Is this safe to use with real money?')
        print('A: The bot includes extensive safety features, but ALL trading involves')
        print('   risk. Always start with paper trading, test thoroughly, and never')
        print('   risk more than you can afford to lose.\n')

        print('Q: How much capital do I need?')
        print('A: Minimum recommended: $1,000 for paper trading, $5,000+ for live.')
        print('   Smaller amounts work but limit diversification and position sizing.\n')

        print('Q: What returns can I expect?')
        print('A: Returns vary greatly and are NEVER guaranteed. Past performance')
        print('   does not indicate future results. Focus on risk management first.\n')

        print('Q: Can I run this 24/7?')
        print('A: Yes for crypto. Stocks/forex have market closures. Use a VPS')
        print('   (Virtual Private Server) for uninterrupted operation.\n')

        print('Q: How do I stop the bot?')
        print('A: Press Ctrl+C. The bot will safely shutdown, optionally canceling')
        print('   orders and saving state. Never force-kill the process.\n')

        print('Q: Where are my trades logged?')
        print('A: logs/trade_logs/trades.log contains all trade execution details.\n')

        print('Q: Can I modify the strategies?')
        print('A: Yes! Strategies are in the strategies/ folder. Read CLAUDE.md')
        print('   for guidance on creating custom strategies.\n')

        print('Q: What if I lose money?')
        print("A: Trading involves risk. The bot's risk limits help minimize losses,")
        print('   but losses can still occur. Never trade with money you need.\n')

        input('Press Enter to continue...')

    @staticmethod
    def show_emergency_procedures():
        """Display emergency procedures"""
        print('\n' + '=' * 70)
        print(' 🚨 Emergency Procedures')
        print('=' * 70 + '\n')

        print('Emergency Shutdown:')
        print('  • Press Ctrl+C to initiate safe shutdown')
        print('  • Bot will stop trading loop')
        print('  • Optionally cancel all open orders')
        print('  • Save final state to data/bot_state.json')
        print('  • Disconnect from API\n')

        print('If Bot Crashes:')
        print("  1. Don't panic - positions are tracked by broker")
        print('  2. Check logs/error_logs/errors.log for cause')
        print('  3. Log into TWS manually to review positions')
        print('  4. Cancel any unwanted orders manually if needed')
        print('  5. Fix the issue before restarting\n')

        print('If You Lose Connection to TWS:')
        print('  • Bot will attempt to reconnect automatically')
        print('  • If reconnection fails, bot will shutdown')
        print('  • Your positions remain active in TWS')
        print('  • Monitor positions manually in TWS while reconnecting\n')

        print('If Risk Limits Are Breached:')
        print('  • Daily loss limit: Bot stops, resumes next day')
        print('  • Drawdown limit: Bot stops, requires manual review')
        print('  • You can manually resume with caution\n')

        print('Manual Order Cancellation:')
        print('  • In TWS: Right-click order > Cancel')
        print('  • All Orders: Account > Global Cancel\n')

        print('Getting Help:')
        print('  • GitHub Issues: https://github.com/anthropics/claude-code/issues')
        print('  • Read CLAUDE.md for detailed documentation')
        print('  • Review logs for specific error details\n')

        input('Press Enter to continue...')


def show_help():
    """Show interactive help system"""
    HelpSystem.display_main_help()
