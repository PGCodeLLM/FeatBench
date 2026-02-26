"""Agent manager, responsible for setting up and running different agents in container"""

import logging
import time
import docker.models.containers
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.agents.trae_agent import TraeAgent
from docker_agent.agents.gemini_cli_agent import GeminiCLIAgent
from docker_agent.agents.claude_code_agent import ClaudeCodeAgent
# from docker_agent.agents.agentless import Agentless
from docker_agent.core.exceptions import ConfigurationError


class AgentManager:
    """Agent manager, responsible for setting up and running different agents in container"""

    def __init__(self, container: docker.models.containers.Container, agent_config):
        self.container = container
        self.agent_config = agent_config
        self.logger = logging.getLogger(__name__)
        self.agent = self._create_agent()

    def _create_agent(self) -> BaseAgent:
        """Create corresponding agent instance based on configuration"""
        agent_name = self.agent_config.name.lower()

        if agent_name == "trae-agent":
            return TraeAgent(self.container, self.agent_config)
        elif agent_name == "gemini-cli":
            return GeminiCLIAgent(self.container, self.agent_config)
        elif agent_name == "claude-code":
            return ClaudeCodeAgent(self.container, self.agent_config)
        elif agent_name == "agentless":
            return Agentless(self.container, self.agent_config)
        else:
            raise ConfigurationError(f"Unsupported agent type: {self.agent_config.name}")

    def setup_agent(self):
        """Set up agent environment"""
        self.agent.setup()
    
    @staticmethod
    def remove_all_locks():
        """Remove all existing repository lock files"""
        swap_path = Path(__file__).parent.parent / "swap"
        lock_files = swap_path.glob("*.repo.lock")
        for lock_file in lock_files:
            try:
                lock_file.unlink()
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to remove lock file {lock_file}: {e}")

    @contextmanager
    def lock_repo(self, repo_name: str):
        """Create repository lock file before agent run"""
        swap_path = self.agent.base_path / "swap"
        repo_lock_path = swap_path / f"{repo_name}.repo.lock"
        
        # Atomically acquire lock
        self.logger.info(f"Waiting for lock on {repo_name}...")
        while True:
            try:
                # Use 'x' mode for exclusive creation - fails if file exists
                with open(repo_lock_path, 'x') as f:
                    f.write(str(time.time()))
                self.logger.info(f"Acquired lock for {repo_name}")
                break
            except FileExistsError:
                # Lock is held by another process
                time.sleep(1)
        
        try:
            yield
        finally:
            # Release the lock
            if repo_lock_path.exists():
                repo_lock_path.unlink()
                self.logger.info(f"Released lock for {repo_name}")

    def evaluate(self, spec, operator, *args, **kwargs) -> Dict[str, Any]:
        """Evaluate agent on spec"""
        with self.lock_repo(spec.repo_name):
            return self.agent.evaluate(spec, operator, *args, **kwargs)

    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """
        Prepare agent-specific resources

        Returns:
            Agent-specific resources (e.g., agentless patches) or None
        """
        return self.agent.prepare_resources()