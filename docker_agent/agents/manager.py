"""Agent manager, responsible for setting up and running different agents in container"""

import logging
import os
import time
import docker.models.containers
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.agents.trae_agent import TraeAgent
from docker_agent.agents.gemini_cli_agent import GeminiCLIAgent
from docker_agent.agents.claude_code_agent import ClaudeCodeAgent
from docker_agent.agents.openhands_agent import OpenHandsAgent
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
        elif agent_name == "openhands":
            return OpenHandsAgent(self.container, self.agent_config)
        elif agent_name == "agentless":
            raise NotImplementedError("Agentless evaluation is not included")
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
        from docker_agent.parsing.pytest_parser import TestStatus

        with self.lock_repo(spec.repo_name):
            try:
                self.agent.setup()

                operator.checkout_commit(spec.base_commit, use_docker=True)
                agent_success, agent_output = self.agent.run(
                    spec.problem_statement,
                    spec.instance_id,
                    spec.repo_name,
                )

                # Fix /logs ownership so the host user can access files written by the container
                uid, gid = os.getuid(), os.getgid()
                self.agent.docker_executor.execute(f"chown -R {uid}:{gid} /logs", "/")

                if agent_success:
                    f2p_tests: List[str] = []
                    p2p_tests: List[str] = []
                    if spec.FAIL_TO_PASS:
                        f2p_tests.extend(spec.FAIL_TO_PASS.split(", "))
                    if spec.PASS_TO_PASS:
                        p2p_tests.extend(spec.PASS_TO_PASS.split(", "))

                    # ---- FAIL_TO_PASS ----------------------------------------
                    operator.checkout_commit(spec.base_commit, exclude_file=["patch.diff"], use_docker=True)
                    self.agent.path_analyzer.apply_patch_file_to_container(
                        self.agent.base_path / "swap" / spec.repo_name / "patch.diff",
                        self.agent.docker_executor,
                        "/workdir/swap/" + spec.repo_name,
                        include_test=False,
                    )
                    if spec.test_patch:
                        operator.apply_patches(spec.test_patch)

                    f2p_passed: set = set()
                    if f2p_tests:
                        f2p_passed, _ = operator.run_tests_in_container(
                            spec.repo_name, f2p_tests, [TestStatus.PASSED], False
                        )

                    # ---- PASS_TO_PASS ----------------------------------------
                    operator.checkout_commit(spec.base_commit, exclude_file=["patch.diff"], use_docker=True)
                    self.agent.path_analyzer.apply_patch_file_to_container(
                        self.agent.base_path / "swap" / spec.repo_name / "patch.diff",
                        self.agent.docker_executor,
                        "/workdir/swap/" + spec.repo_name,
                        include_test=False,
                    )
                    if spec.test_patch:
                        operator.apply_patches(spec.test_patch)

                    p2p_passed: set = set()
                    if p2p_tests:
                        p2p_passed, _ = operator.run_tests_in_container(
                            spec.repo_name, p2p_tests, [TestStatus.PASSED]
                        )

                    success_f2p = all(test in f2p_passed for test in f2p_tests)
                    success_p2p = all(test in p2p_passed for test in p2p_tests)
                    success = success_f2p and success_p2p

                    try:
                        tokens_count = self.agent.parse_agent_log(agent_output)
                    except Exception as e:
                        self.logger.warning(f"Token parsing failed, continuing without token counts: {e}")
                        tokens_count = {"Total Tokens": None, "Input Tokens": None, "Output Tokens": None}

                    return {
                        "agent": self.agent.agent_config.name,
                        "model": self.agent.agent_config.model,
                        "instance_id": spec.instance_id,
                        "success_f2p": success_f2p,
                        "success_p2p": success_p2p,
                        "success": success,
                        "passed_f2p_tests": list(f2p_passed),
                        "passed_p2p_tests": list(p2p_passed),
                        "expected_f2p_tests": f2p_tests,
                        "expected_p2p_tests": p2p_tests,
                        "total_tokens": tokens_count["Total Tokens"],
                        "input_tokens": tokens_count["Input Tokens"],
                        "output_tokens": tokens_count["Output Tokens"],
                    }
                else:
                    return {
                        "agent": self.agent.agent_config.name,
                        "model": self.agent.agent_config.model,
                        "instance_id": spec.instance_id,
                        "success": False,
                        "error": agent_output,
                    }

            except Exception as e:
                self.logger.error(f"Error evaluating {self.agent.agent_config.name} on {spec.instance_id}: {e}")
                return {
                    "agent": self.agent.agent_config.name,
                    "model": self.agent.agent_config.model,
                    "instance_id": spec.instance_id,
                    "success": False,
                    "error": str(e),
                }

    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """
        Prepare agent-specific resources

        Returns:
            Agent-specific resources (e.g., agentless patches) or None
        """
        return self.agent.prepare_resources()