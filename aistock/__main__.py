"""
Entry point for running AIStock Robot as a module.

Usage:
    python -m aistock             # Launch Simple Mode (beginner-friendly)
    python -m aistock --simple    # Launch Simple Mode (explicit)
    python -m aistock --advanced  # Launch Advanced Mode (power users)
    python -m aistock.gui         # Launch Advanced Mode directly
    python -m aistock.simple_gui  # Launch Simple Mode directly
"""

import sys


def main() -> None:
    # Check command-line arguments
    if "--advanced" in sys.argv:
        from .gui import TradingGUI
        print("🚀 Launching AIStock Robot - Advanced Mode")
        TradingGUI().run()
    elif "--simple" in sys.argv or len(sys.argv) == 1:
        # Default to Simple Mode for beginners!
        from .simple_gui import SimpleGUI
        print("🚀 Launching AIStock Robot - Simple Mode")
        SimpleGUI().run()
    elif "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
    else:
        print("❌ Invalid argument. Use --help for usage information.")
        sys.exit(1)


if __name__ == "__main__":
    main()
