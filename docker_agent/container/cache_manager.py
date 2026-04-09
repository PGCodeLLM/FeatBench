"""Container and image cache manager"""

import docker
import io
import os
import logging
import tarfile
from pathlib import Path
from typing import Any, Dict, Optional

from docker_agent.core.types import Container
from docker_agent.container.image_builder import DockerImageBuilder
from docker_agent.config.config import DOCKER_ENVIRONMENT, EXP_UUID, EXP_ID, RESOURCE_LIMITS_ENABLED
from docker_agent.core.exceptions import CacheError


_REPO_CPU_OVERRIDES: dict[str, int] = {
    "pybamm": 16,
    "smolagents": 8,
    "faststream": 32,
    "xarray": 16,
    "opcua-asyncio": 8,
    "python-sdk": 8,
}

_REPO_MEM_OVERRIDES: dict[str, str] = {
    "pybamm": "24g",
    "smolagents": "8g",
    "faststream": "48g",
    "xarray": "24g",
    "opcua-asyncio": "8g",
    "python-sdk": "8g",
}

_DEFAULT_CPU = 2
_DEFAULT_MEM = "4g"


def get_cpu_limit(repo: str) -> int:
    """Return the hard CPU cap for the given repo."""
    repo_lower = repo.replace("/", "_").lower()
    for key, cpus in _REPO_CPU_OVERRIDES.items():
        if key in repo_lower:
            return cpus
    return _DEFAULT_CPU


class CacheManager:
    """Container and image cache manager"""

    def __init__(self, repo: str, repo_id: str, instance_id: str, timeout=300):
        self.base_path = Path(__file__).parent.parent
        self.logger = logging.getLogger(__name__)
        self.client = docker.from_env(timeout=timeout)
        self.repo = repo.replace("/", "_")
        self.repo_name = repo.split("/")[-1]
        self.repo_id = repo_id
        self.repo_lower = self.repo.lower()
        self.image_builder = DockerImageBuilder(self.base_path, timeout)
        self.instance_log_dir = self.base_path / "logs" / EXP_ID / instance_id
        self.instance_log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _resource_limits(self) -> dict[str, Any]:
        """CPU and memory limits for this repo's containers."""
        cpus = get_cpu_limit(self.repo)
        mem = _DEFAULT_MEM
        for key, m in _REPO_MEM_OVERRIDES.items():
            if key in self.repo_lower:
                mem = m
                break
        return {"nano_cpus": cpus * 10**9, "mem_limit": mem}

    @property
    def swap_volume_name(self) -> str:
        """Unique named Docker volume for this container's swap directory"""
        return f"featbench_swap_{self.repo_lower}_{self.repo_id}_{EXP_UUID}"

    @property
    def common_container_config(self) -> Dict[str, Any]:
        """Extract and return common container creation parameters"""

        config = {
            "name": f"{self.repo}_{self.repo_id}_{EXP_UUID}",
            "command": "/bin/bash",
            "detach": True,
            "tty": True,

            # Each container gets Docker's default bridge network (its own
            # network namespace) so containers cannot collide on ports or
            # interfere with each other, while still having outbound internet
            # access via the bridge's NAT.
            # "network_mode": "host",
            
            # "runtime": "nvidia",
            # "device_requests": [{
            #     'count': -1,
            #     'capabilities': [['gpu']]
            # }],
            "environment": DOCKER_ENVIRONMENT,
            "labels": {
                "featbench.swap_volume": self.swap_volume_name
            },
            "volumes": {
                self.swap_volume_name: {
                    "bind": "/workdir/swap",
                    "mode": "rw"
                },
                str(self.instance_log_dir): {
                    "bind": "/logs",
                    "mode": "rw"
                }
            },
            **(self._resource_limits if RESOURCE_LIMITS_ENABLED else {}),
        }

        # Disabling this for now, as it may cause disk permission issues in some environments
        # if os.name == 'posix':
        #     uid = os.getuid()
        #     gid = os.getgid()
        #     self.logger.info(f"Running on POSIX system, setting container user to UID={uid}, GID={gid}")
        #     config['user'] = f"{uid}:{gid}"

        return config

    def create_swap_volume(self) -> None:
        """Create a unique named Docker volume for this container's swap directory"""
        self.client.volumes.create(name=self.swap_volume_name)
        self.logger.info(f"Created named swap volume: {self.swap_volume_name}")

    def copy_swap_to_volume(self, container) -> None:
        """Copy repo and trae-agent directories from local swap into the container's named swap volume"""
        swap_path = self.base_path / "swap"

        dirs_to_copy = [
            (swap_path / self.repo_name, self.repo_name),
            (swap_path / "trae-agent", "trae-agent"),
        ]

        self.logger.info(f"Copying swap dirs into volume {self.swap_volume_name}")
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w|") as tar:
            for src, arcname in dirs_to_copy:
                if src.exists():
                    self.logger.info(f"Including {src} in swap volume copy")
                    tar.add(str(src), arcname=arcname)
                else:
                    self.logger.info(f"Skipping {src} (does not exist)")
        tar_stream.seek(0)
        container.put_archive("/workdir/swap", tar_stream)
        self.logger.info("Swap content copied into named volume successfully")

    def delete_swap_volume(self) -> None:
        """Delete the named swap volume"""
        try:
            vol = self.client.volumes.get(self.swap_volume_name)
            vol.remove(force=True)
            self.logger.info(f"Deleted named swap volume: {self.swap_volume_name}")
        except docker.errors.NotFound:
            self.logger.warning(f"Swap volume {self.swap_volume_name} not found during cleanup")
        except Exception as e:
            self.logger.error(f"Failed to delete swap volume {self.swap_volume_name}: {e}")

    def check_cached_container(self) -> Optional[Container]:
        """Check if cached container exists"""

        try:
            # Find existing containers
            container = self.client.containers.get(self.repo)

            # Check container status
            if container.status == 'running':
                self.logger.info(f"Found running cached container: {self.repo}")
                return container
            elif container.status == 'exited':
                self.logger.info(f"Found stopped cached container: {self.repo}, restarting...")
                container.start()
                return container
            else:
                self.logger.warning(f"Container {self.repo} status abnormal: {container.status}, will recreate")
                container.remove(force=True)
                return None

        except docker.errors.NotFound:
            self.logger.info(f"Cached container not found: {self.repo}")
            return None
        except Exception as e:
            self.logger.error(f"Error checking cached container: {str(e)}")
            return None

    def save_container_as_image(self, container: Container) -> str:
        """Save container as new image"""

        # Image name must be lowercase
        image_name = f"featbench_{self.repo_lower}"

        try:
            self.logger.info(f"Saving container as image: {image_name}")

            # Commit container as new image
            image = container.commit(repository=image_name, tag=self.repo_id)

            self.logger.info(f"Successfully saved image: {image_name}:latest (ID: {image.id[:12]})")
            return image.id

        except Exception as e:
            self.logger.error(f"Failed to save container image: {str(e)}")
            raise CacheError(f"Failed to save container image: {str(e)}")

    def check_cached_image(self) -> bool:
        """Check if cached image exists"""

        image_name = f"featbench_{self.repo_lower}:{self.repo_id}"

        try:
            self.client.images.get(image_name)
            self.logger.info(f"Found cached image: {image_name}")
            return True
        except docker.errors.ImageNotFound:
            self.logger.info(f"Cached image not found: {image_name}")
            return False
        except Exception as e:
            self.logger.error(f"Error checking cached image: {str(e)}")
            return False

    def create_container_from_cached_image(self) -> Container:
        """Create container from cached image"""

        image_name = f"featbench_{self.repo_lower}:{self.repo_id}"

        self.logger.info(f"Creating container from cached image: {image_name}")

        container = self.client.containers.run(
            image=image_name,
            **self.common_container_config
        )

        self.logger.info(f"Successfully created container from cached image: {container.name}")
        return container

    def create_new_container(self) -> Container:
        """Create new container"""
        self.logger.info(f"Creating new container: {self.repo}")

        # Build dynamic image
        image_name = self.image_builder.build_image(self.repo)

        # Create container with GPU support
        container = self.client.containers.run(
            image=image_name,
            **self.common_container_config
        )

        self.logger.info(f"Container {container.name} created successfully")
        return container