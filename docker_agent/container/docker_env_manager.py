"""Docker environment manager"""

import logging

from docker_agent.core.types import Spec, Container
from docker_agent.container.cache_manager import CacheManager


class DockerEnvironmentManager:
    """Docker environment manager"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def create_container(self, sepc: Spec, timeout=300) -> Container:
        """Create Docker container and configure test environment (with cache support)"""

        self.cache_manager = CacheManager(sepc.repo, sepc.number, timeout)
        # Disabling cached container as it has no use and will make "agent" directory already exists issues
        # cached_container = self.cache_manager.check_cached_container()
        # if cached_container:
        #     return cached_container

        if self.cache_manager.check_cached_image():
            return self.cache_manager.create_container_from_cached_image()

        return self.cache_manager.create_new_container()

    def cleanup_container(self, container: Container, force_remove: bool = False) -> None:
        """Clean up container resources"""
        if container:
            try:
                if force_remove:
                    container.stop()
                    container.remove()
                    self.logger.info(f"Container {container.name} has been deleted")
                else:
                    self.logger.info(f"Container {container.name} retained as cache")

            except Exception as e:
                self.logger.error(f"Error handling container: {str(e)}")
