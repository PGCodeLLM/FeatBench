import docker
import json
import logging

from docker_agent.config.config import (
    RECOMMENDED_PYTHON_VERSION, DEFAULT_PYTHON_VERSION,
    DOCKERFILE_TEMPLATE
)
from docker_agent.core.exceptions import ContainerCreationError

class DockerImageBuilder:
    """Docker image builder"""

    def __init__(self, base_path, timeout=300):
        self.logger = logging.getLogger(__name__)
        self.client = docker.from_env(timeout=timeout)
        self.api_client = docker.APIClient(timeout=timeout)  # Add low-level API client
        self.base_path = base_path
    
    def _read_python_version(self, repo: str) -> str:
        """Read recommended Python version from project"""
        version_file = self.base_path / "swap" / RECOMMENDED_PYTHON_VERSION

        try:
            if version_file.exists():
                version = json.loads(version_file.read_text())
                self.logger.info(f"Read Python version from file: {version[repo]}")
                return version[repo]
            else:
                self.logger.info(f"Version file not found, using default version: {DEFAULT_PYTHON_VERSION}")
                return DEFAULT_PYTHON_VERSION
        except Exception as e:
            self.logger.warning(f"Failed to read Python version: {e}, using default version")
            return DEFAULT_PYTHON_VERSION
    
    def _generate_dockerfile_content(self, python_version: str) -> str:
        """Generate Dockerfile content"""
        return DOCKERFILE_TEMPLATE.format(python_version=python_version)
    
    def build_image(self, repo: str) -> str:
        """Build Docker image"""
        python_version = self._read_python_version(repo)
        image_name = f"codegen_{python_version}"
        
        try:
            self.client.images.get(image_name)
            self.logger.info(f"Found existing image: {image_name}")
            return image_name
        except docker.errors.ImageNotFound:
            pass
        
        try:
            dockerfile_content = self._generate_dockerfile_content(python_version)
            dockerfile_path = self.base_path / "Dockerfile.tmp"
            dockerfile_path.write_text(dockerfile_content)

            self.logger.info(f"Starting image build: {image_name} (Python {python_version})")
            
            for chunk in self.api_client.build(
                path=str(self.base_path),
                tag=image_name,
                rm=True,
                forcerm=True,
                dockerfile=dockerfile_path,
                network_mode="host",
                decode=True
            ):
                if 'stream' in chunk:
                    log_line = chunk['stream'].strip()
                    if log_line:
                        self.logger.info(log_line)
            
            self.logger.info(f"Image build successful: {image_name}")
            return image_name
            
        except Exception as e:
            self.logger.error(f"Image build failed: {e}")
            raise ContainerCreationError(f"Image build failed: {e}")
        finally:
            if dockerfile_path.exists():
                dockerfile_path.unlink()
                self.logger.debug("Temporary Dockerfile cleaned up")