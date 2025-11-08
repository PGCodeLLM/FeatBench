"""Cleanup manager for container resources"""

import logging
from typing import List

from docker_agent.core.types import Container


class CleanupManager:
    """Manages container cleanup with user interaction"""

    def __init__(self, docker_manager):
        self.docker_manager = docker_manager
        self.logger = logging.getLogger(__name__)

    def cleanup_all(self, active_containers: List[Container]):
        """Clean up all active containers"""
        for container in active_containers[:]:
            if container:
                try:
                    try:
                        response = input(f"\nDo you want to delete container {container.name}? (y/N): ").strip().lower()
                        force_remove = response in ['y', 'yes']
                    except (EOFError, KeyboardInterrupt):
                        force_remove = False
                        self.logger.info("User interrupted input, defaulting to keep container")

                    self.docker_manager.cleanup_container(container, force_remove=force_remove)
                    active_containers.remove(container)
                except Exception as e:
                    self.logger.error(f"Error cleaning up container {container.name}: {e}")