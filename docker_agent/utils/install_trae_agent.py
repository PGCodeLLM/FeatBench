"""
Trae-agent installer utility

This module provides functionality to install trae-agent in a specified directory.
It checks if the directory is empty before installation to avoid overwriting existing installations.
"""

import logging
import subprocess
from pathlib import Path


class TraeAgentInstaller:
    """Manages trae-agent installation"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def install(
        self,
        install_path: Path,
        repo_url: str = "https://github.com/PGCodeLLM/trae-agent.git",
        branch: str = "main"
    ) -> bool:
        """
        Install trae-agent to the specified path

        Args:
            install_path: Directory where trae-agent should be installed
            repo_url: Git repository URL for trae-agent
            branch: Branch to checkout

        Returns:
            True if installation successful or already exists, False otherwise
        """
        if install_path.exists():
            if any(install_path.iterdir()):
                self.logger.info(
                    f"Directory {install_path} already exists and is not empty, skipping trae-agent installation"
                )
                return True
            else:
                self.logger.info(f"Directory {install_path} exists but is empty, proceeding with installation")
        else:
            self.logger.info(f"Creating directory {install_path} for trae-agent installation")
            install_path.mkdir(parents=True, exist_ok=True)

        try:
            self.logger.info(f"Cloning trae-agent from {repo_url} to {install_path}")
            clone_cmd = [
                "git",
                "clone",
                "--branch", branch,
                repo_url,
                "."
            ]

            result = subprocess.run(
                clone_cmd,
                cwd=install_path,
                capture_output=True,
                text=True,
                check=True
            )

            self.logger.info(f"Successfully cloned trae-agent to {install_path}")
            self.logger.info(f"Running uv sync --all-extras in {install_path}")
            sync_cmd = ["uv", "sync", "--all-extras"]

            result = subprocess.run(
                sync_cmd,
                cwd=install_path,
                capture_output=True,
                text=True,
                check=True
            )

            self.logger.info(f"Successfully ran uv sync in {install_path}")
            self.logger.info("Trae-agent installation completed successfully")

            return True

        except subprocess.CalledProcessError as e:
            self.logger.error(
                f"Failed to install trae-agent: {e.stderr or e.stdout}"
            )
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during trae-agent installation: {e}")
            return False