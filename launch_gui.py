#!/usr/bin/env python3
"""
AIStock Robot GUI Launcher - FSD Mode Only

Launches the Full Self-Driving (FSD) trading interface.
The AI makes all trading decisions using reinforcement learning.
"""

import sys


def main() -> None:
    print('=' * 70)
    print(' 🤖 AIStock Robot - FSD Mode (Full Self-Driving)')
    print('=' * 70)
    print()
    print('🚗 Launching FSD Mode...')
    print('   • AI-driven trading with reinforcement learning')
    print('   • Simple interface, just configure and start')
    print('   • Perfect for hands-off trading')
    print()

    from aistock.simple_gui import SimpleGUI

    SimpleGUI().run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n👋 Goodbye!')
        sys.exit(0)
    except Exception as e:
        print(f'\n❌ Error launching GUI: {e}')
        sys.exit(1)
