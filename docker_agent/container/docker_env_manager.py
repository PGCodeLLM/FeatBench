"""Docker environment manager"""

import docker
import logging

from docker_agent.core.types import Spec, Container
from docker_agent.container.cache_manager import CacheManager


class DockerEnvironmentManager:
    """Docker environment manager"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.client = docker.from_env()

    def create_container(self, sepc: Spec, timeout=300) -> Container:
        """Create Docker container and configure test environment (with cache support)"""

        # Create cache_manager as local variable to avoid race conditions in multi-threaded environment
        cache_manager = CacheManager(sepc.repo, sepc.number, sepc.instance_id, timeout)
        # Disabling cached container as it has no use and will make "agent" directory already exists issues
        # cached_container = cache_manager.check_cached_container()
        # if cached_container:
        #     return cached_container

        # Create the unique named volume for this container's isolated swap directory
        cache_manager.create_swap_volume()

        if cache_manager.check_cached_image():
            container = cache_manager.create_container_from_cached_image()
        else:
            container = cache_manager.create_new_container()

        # Populate the named volume with the current contents of the host swap directory
        cache_manager.copy_swap_to_volume(container)

        return container

    def cleanup_container(self, container: Container, force_remove: bool = False) -> None:
        """Clean up container resources"""
        if container:
            try:
                if force_remove:
                    # Read the swap volume name from the container label before stopping it
                    container.reload()
                    volume_name = container.labels.get("featbench.swap_volume")

                    container.stop()
                    container.remove()
                    self.logger.info(f"Container {container.name} has been deleted")

                    # Delete the named swap volume now that the container is gone
                    if volume_name:
                        try:
                            self.client.volumes.get(volume_name).remove(force=True)
                            self.logger.info(f"Deleted named swap volume: {volume_name}")
                        except docker.errors.NotFound:
                            self.logger.warning(f"Swap volume {volume_name} not found during cleanup")
                        except Exception as e:
                            self.logger.error(f"Failed to delete swap volume {volume_name}: {e}")
                else:
                    self.logger.info(f"Container {container.name} retained as cache")

            except Exception as e:
                self.logger.error(f"Error handling container: {str(e)}")
