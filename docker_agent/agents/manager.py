"""Agent manager, responsible for setting up and running different agents in container"""

import logging
import docker.models.containers
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.agents.trae_agent import TraeAgent
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
        elif agent_name == "agentless":
            return Agentless(self.container, self.agent_config)
        else:
            raise ConfigurationError(f"Unsupported agent type: {self.agent_config.name}")

    def setup_agent(self):
        """Set up agent environment"""
        self.agent.setup()

    def evaluate(self, spec, operator, *args, **kwargs) -> Dict[str, Any]:
        """Evaluate agent on spec"""
        return self.agent.evaluate(spec, operator, *args, **kwargs)

    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """
        Prepare agent-specific resources

        Returns:
            Agent-specific resources (e.g., agentless patches) or None
        """
        return self.agent.prepare_resources()