"""Signal handler for graceful shutdown"""

import signal
import logging
import sys


class SignalHandler:
    """Handles SIGINT/SIGTERM signals with graceful cleanup"""

    def __init__(self, cleanup_callback):
        self.cleanup_callback = cleanup_callback
        self.cleanup_in_progress = False
        self.logger = logging.getLogger(__name__)

    def register(self):
        """Register signal handlers"""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        """Handle termination signal"""
        if self.cleanup_in_progress:
            self.logger.info("Cleanup already in progress, ignoring duplicate signal")
            return

        self.cleanup_in_progress = True
        self.logger.info(f"\nReceived signal {signum}, cleaning up containers...")

        if self.cleanup_callback:
            self.cleanup_callback()

        self.cleanup_in_progress = False
        sys.exit(0)