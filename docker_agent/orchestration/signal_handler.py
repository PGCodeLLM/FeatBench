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
            return

        self.cleanup_in_progress = True
        print("\nReceived interrupt, cleaning up containers...", file=sys.stderr, flush=True)
        self.logger.info(f"Received signal {signum}, cleaning up containers...")

        if self.cleanup_callback:
            self.cleanup_callback()

        sys.exit(0)
