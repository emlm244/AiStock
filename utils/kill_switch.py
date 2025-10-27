"""
Emergency Kill Switch Mechanism

Provides multiple ways to immediately halt trading:
1. File-based kill switch (create kill.txt)
2. Signal-based kill switch (SIGUSR1)
3. API endpoint kill switch (if monitoring enabled)
4. Manual intervention via logs
"""

import os
import signal
import threading
from pathlib import Path
from typing import Callable, Optional


class KillSwitch:
    """
    Emergency kill switch with multiple trigger mechanisms.

    Usage:
        kill_switch = KillSwitch(callback=bot.emergency_stop)
        kill_switch.start()
        # ... bot runs ...
        kill_switch.stop()
    """

    def __init__(self, callback: Callable[[], None], check_interval: float = 1.0):
        """
        Initialize kill switch.

        Args:
            callback: Function to call when kill switch is triggered
            check_interval: How often to check file-based kill switch (seconds)
        """
        self.callback = callback
        self.check_interval = check_interval
        self.kill_file = Path('kill.txt')
        self.running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._original_sigusr1_handler = None

    def start(self):
        """Start monitoring for kill switch triggers."""
        if self.running:
            return

        self.running = True

        # Start file monitor thread
        self._monitor_thread = threading.Thread(target=self._monitor_kill_file, daemon=True, name='KillSwitchMonitor')
        self._monitor_thread.start()

        # Register signal handler (Unix-like systems only)
        if hasattr(signal, 'SIGUSR1'):
            self._original_sigusr1_handler = signal.signal(signal.SIGUSR1, self._signal_handler)

    def stop(self):
        """Stop monitoring kill switch."""
        self.running = False

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)

        # Restore original signal handler
        if hasattr(signal, 'SIGUSR1') and self._original_sigusr1_handler:
            signal.signal(signal.SIGUSR1, self._original_sigusr1_handler)

    def trigger(self, reason: str = 'Manual kill switch triggered'):
        """Manually trigger the kill switch."""
        print(f'\n🚨 KILL SWITCH ACTIVATED: {reason} 🚨\n')
        if self.callback:
            self.callback()

    def _monitor_kill_file(self):
        """Monitor for kill.txt file creation."""
        import time

        while self.running:
            try:
                if self.kill_file.exists():
                    # Read reason from file if present
                    try:
                        reason = self.kill_file.read_text().strip() or 'Kill file detected'
                    except Exception:
                        reason = 'Kill file detected'

                    self.trigger(reason)

                    # Remove kill file after triggering
                    try:
                        self.kill_file.unlink()
                    except Exception:
                        pass

                    break

                time.sleep(self.check_interval)
            except Exception as e:
                print(f'Error in kill switch monitor: {e}')
                time.sleep(self.check_interval)

    def _signal_handler(self, signum, frame):
        """Handle SIGUSR1 signal."""
        self.trigger('SIGUSR1 signal received')

    @staticmethod
    def create_kill_file(reason: str = 'Emergency stop requested'):
        """
        Create kill file to trigger emergency stop.

        This can be called from another process or manually:
            echo "Market crash detected" > kill.txt
        """
        Path('kill.txt').write_text(reason)
        print(f'Kill switch file created: {reason}')


def install_kill_switch(bot, check_interval: float = 1.0) -> KillSwitch:
    """
    Install kill switch on a trading bot instance.

    Args:
        bot: TradingBot instance with a stop() method
        check_interval: How often to check for kill triggers

    Returns:
        KillSwitch instance (already started)
    """

    def emergency_stop_callback():
        """Emergency stop callback that calls bot.stop()."""
        if hasattr(bot, 'stop'):
            bot.stop(reason='EMERGENCY KILL SWITCH ACTIVATED')

    kill_switch = KillSwitch(callback=emergency_stop_callback, check_interval=check_interval)
    kill_switch.start()

    # Print usage instructions
    print('\n' + '=' * 70)
    print('🛡️  KILL SWITCH ARMED')
    print('=' * 70)
    print('Emergency stop methods:')
    print('  1. Create file: touch kill.txt')
    print('  2. Send signal: kill -USR1 <pid>')
    print('  3. Press Ctrl+C')
    print('=' * 70 + '\n')

    return kill_switch


__all__ = ['KillSwitch', 'install_kill_switch']
