"""
Entry point for running AIStock Robot as a module.

Usage:
    python -m aistock              # Launch FSD Mode (Full Self-Driving)
    python -m aistock --fsd        # Launch FSD Mode (explicit)
    python -m aistock --help       # Show this help message
"""

import signal
import sys
import logging

# Global reference to GUI instance for signal handlers
_gui_instance = None

logger = logging.getLogger(__name__)


def _signal_handler(signum: int, frame) -> None:
    """
    CRITICAL-3 Fix: Handle SIGINT (CTRL+C) and SIGTERM for clean shutdown.

    Ensures:
    - Checkpoint queue is drained (no data loss)
    - Active session is stopped cleanly
    - Resources are released
    """
    signal_name = 'SIGINT' if signum == signal.SIGINT else 'SIGTERM'
    logger.info(f'{signal_name} received - initiating clean shutdown...')
    print(f'\n\n⚠️ {signal_name} received - shutting down gracefully...')

    if _gui_instance and _gui_instance.session:
        try:
            print('📦 Draining checkpoint queue...')
            _gui_instance.session.stop()  # Checkpoint queue drain is in session.stop()
            print('✅ Clean shutdown complete')
        except Exception as e:
            logger.error(f'Error during shutdown: {e}', exc_info=True)
            print(f'⚠️ Shutdown error: {e}')

    sys.exit(0)


def main() -> None:
    global _gui_instance

    # Check command-line arguments
    if '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
    else:
        # CRITICAL-3 Fix: Register signal handlers for clean shutdown
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        logger.info('Signal handlers registered (SIGINT, SIGTERM)')

        # Always launch FSD mode
        from .simple_gui import SimpleGUI

        print('🚀 Launching AIStock Robot - FSD Mode (Full Self-Driving)')
        _gui_instance = SimpleGUI()
        _gui_instance.run()


if __name__ == '__main__':
    main()
