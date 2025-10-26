#!/usr/bin/env python3
"""
AIStock Robot GUI Launcher

This script asks the user whether they want:
- Simple Mode (for beginners): Just capital, risk level, and START button
- Advanced Mode (for power users): Full control center with all features

Default: Simple Mode (perfect for beginners!)
"""

import sys


def main() -> None:
    print("=" * 60)
    print(" 🤖 AIStock Robot - GUI Launcher")
    print("=" * 60)
    print()
    print("Which interface do you want to use?")
    print()
    print("1. 🎯 SIMPLE MODE (Recommended for beginners)")
    print("   • Perfect if you're new to trading")
    print("   • Just answer 3 simple questions")
    print("   • Click START and let the AI do everything!")
    print("   • FSD (Full Self-Driving) mode enabled")
    print()
    print("2. ⚙️  ADVANCED MODE (For power users)")
    print("   • Full control over all settings")
    print("   • Backtesting studio")
    print("   • ML model training")
    print("   • Scenario testing")
    print("   • Live trading console with all options")
    print()
    print("=" * 60)

    while True:
        choice = input("Enter your choice (1 or 2) [default: 1]: ").strip()

        # Default to Simple Mode
        if choice == "" or choice == "1":
            print("\n✅ Launching SIMPLE MODE...\n")
            from aistock.simple_gui import SimpleGUI
            SimpleGUI().run()
            break
        elif choice == "2":
            print("\n✅ Launching ADVANCED MODE...\n")
            from aistock.gui import TradingGUI
            TradingGUI().run()
            break
        else:
            print("❌ Invalid choice. Please enter 1 or 2.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error launching GUI: {e}")
        sys.exit(1)
