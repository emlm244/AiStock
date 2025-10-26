#!/usr/bin/env python3
"""
AIStock Robot GUI Launcher

Choose your trading mode:
1. FSD (Full Self-Driving) - For beginners: AI handles everything
2. Headless (Semi-Autonomous) - For advanced users: AI assists, you approve
3. BOT (Manual Control) - For power users: Full manual control

Default: FSD Mode (perfect for beginners!)
"""

import sys


def main() -> None:
    print("=" * 70)
    print(" 🤖 AIStock Robot - Mode Selection")
    print("=" * 70)
    print()
    print("Choose your trading mode:")
    print()
    print("1. 🚗 FSD MODE (Full Self-Driving) - DEFAULT")
    print("   ★ RECOMMENDED FOR BEGINNERS")
    print("   • 100% AI-driven trading")
    print("   • Just set capital + risk level, AI does everything")
    print("   • AI chooses stocks, entry/exit, position sizes")
    print("   • Learns from every trade, saves state between sessions")
    print("   • Stocks only")
    print()
    print("2. 🛫 HEADLESS MODE (Semi-Autonomous)")
    print("   ★ FOR ADVANCED USERS")
    print("   • AI suggests trades, you approve/reject")
    print("   • Set strategy parameters, AI executes")
    print("   • You control risk limits, AI enforces them")
    print("   • Monitor AI suggestions, adjust as needed")
    print("   • Stocks only")
    print()
    print("3. 🎮 BOT MODE (Manual Control)")
    print("   ★ FOR POWER USERS")
    print("   • Full manual control over everything")
    print("   • Configure all indicators, strategies, parameters")
    print("   • Backtesting studio, ML model training")
    print("   • Multi-asset: Stocks + Forex + Crypto")
    print("   • Advanced trading console with all options")
    print()
    print("=" * 70)

    while True:
        choice = input("Enter your choice (1, 2, or 3) [default: 1]: ").strip()

        # Default to FSD Mode
        if choice == "" or choice == "1":
            print("\n✅ Launching FSD MODE (Full Self-Driving)...\n")
            from aistock.simple_gui import SimpleGUI
            SimpleGUI().run()
            break
        elif choice == "2":
            print("\n✅ Launching HEADLESS MODE (Semi-Autonomous)...\n")
            print("⚠️  Headless GUI coming soon! For now, launching FSD mode.\n")
            # TODO: Create HeadlessGUI
            from aistock.simple_gui import SimpleGUI
            SimpleGUI().run()
            break
        elif choice == "3":
            print("\n✅ Launching BOT MODE (Manual Control)...\n")
            from aistock.gui import TradingGUI
            TradingGUI().run()
            break
        else:
            print("❌ Invalid choice. Please enter 1, 2, or 3.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error launching GUI: {e}")
        sys.exit(1)
