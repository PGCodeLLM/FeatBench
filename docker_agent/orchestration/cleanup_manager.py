"""Cleanup manager for container resources"""

import logging
from typing import List

from docker_agent.core.types import Container


class CleanupManager:
    """Manages container cleanup"""

    def __init__(self, docker_manager):
        self.docker_manager = docker_manager
        self.logger = logging.getLogger(__name__)

    def cleanup_all(self, active_containers: List[Container]):
        """Remove all active containers and their volumes."""
        self.logger.info(f"Cleaning up {len(active_containers)} container(s)...")
        for container in active_containers[:]:
            if container:
                try:
                    self.docker_manager.cleanup_container(container, force_remove=True)
                    active_containers.remove(container)
                except Exception as e:
                    self.logger.error(f"Error cleaning up container {container.name}: {e}")
