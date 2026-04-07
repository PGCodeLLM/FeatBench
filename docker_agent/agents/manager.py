"""Agent manager, responsible for setting up and running different agents in container"""

import logging
import os
import time
import docker.models.containers
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.parsing.patch_analyzer import PatchAnalyzer
from docker_agent.utils.command_executor import DockerCommandExecutor
from docker_agent.agents.trae_agent import TraeAgent
from docker_agent.agents.gemini_cli_agent import GeminiCLIAgent
from docker_agent.agents.claude_code_agent import ClaudeCodeAgent
from docker_agent.agents.openhands_agent import OpenHandsAgent
from docker_agent.agents.oracle_agent import OracleAgent
# from docker_agent.agents.agentless import Agentless
from docker_agent.core.exceptions import ConfigurationError


class AgentManager:
    """Agent manager, responsible for setting up and running different agents in container"""

    def __init__(self, container: docker.models.containers.Container, agent_config, log_dir=None):
        self.container = container
        self.agent_config = agent_config
        self.log_dir = log_dir
        self.logger = logging.getLogger(__name__)
        self.agent = self._create_agent()

    def _create_agent(self) -> BaseAgent:
        """Create corresponding agent instance based on configuration"""
        agent_name = self.agent_config.name.lower()

        if agent_name == "trae-agent":
            return TraeAgent(self.container, self.agent_config, log_dir=self.log_dir)
        elif agent_name == "gemini-cli":
            return GeminiCLIAgent(self.container, self.agent_config, log_dir=self.log_dir)
        elif agent_name == "claude-code":
            return ClaudeCodeAgent(self.container, self.agent_config, log_dir=self.log_dir)
        elif agent_name == "openhands":
            return OpenHandsAgent(self.container, self.agent_config, log_dir=self.log_dir)
        elif agent_name == "oracle":
            return OracleAgent(self.container, self.agent_config, log_dir=self.log_dir)
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

    _MAX_TEST_RETRIES = 3

    def _run_tests(self, spec, operator, patch_content) -> Dict[str, Any]:
        """Run F2P and P2P tests with a given patch. Shared by evaluate() and reevaluate()."""
        from docker_agent.parsing.pytest_parser import TestStatus

        f2p_tests: List[str] = []
        p2p_tests: List[str] = []
        if spec.FAIL_TO_PASS:
            f2p_tests.extend(spec.FAIL_TO_PASS.split(", "))
        if spec.PASS_TO_PASS:
            p2p_tests.extend(spec.PASS_TO_PASS.split(", "))

        patch_analyzer = PatchAnalyzer()
        docker_executor = DockerCommandExecutor(self.container, log_dir=self.log_dir)

        # Re-run repo env setup once before tests in case git checkout
        # between agent run and test run removed build artifacts.
        operator.setup_repo_env(spec.repo_name, instance_id=spec.instance_id)

        # ---- FAIL_TO_PASS ----------------------------------------
        f2p_passed: set = set()
        if f2p_tests:
            f2p_passed = self._run_test_group_with_retries(
                spec, operator, patch_analyzer, docker_executor,
                patch_content, f2p_tests,
                use_xdist=True, log_file="f2p_pytest.log",
                expected_status=[TestStatus.PASSED],
            )

        # ---- PASS_TO_PASS ----------------------------------------
        p2p_passed: set = set()
        if p2p_tests:
            p2p_passed = self._run_test_group_with_retries(
                spec, operator, patch_analyzer, docker_executor,
                patch_content, p2p_tests,
                use_xdist=True, log_file="p2p_pytest.log",
                expected_status=[TestStatus.PASSED],
            )

        success_f2p = all(test in f2p_passed for test in f2p_tests)
        success_p2p = all(test in p2p_passed for test in p2p_tests)
        success = success_f2p and success_p2p

        return {
            "success_f2p": success_f2p,
            "success_p2p": success_p2p,
            "success": success,
            "patch": patch_content,
            "passed_f2p_tests": list(f2p_passed),
            "passed_p2p_tests": list(p2p_passed),
            "expected_f2p_tests": f2p_tests,
            "expected_p2p_tests": p2p_tests,
        }

    def _run_test_group_with_retries(
        self, spec, operator, patch_analyzer, docker_executor,
        patch_content: str, expected_tests: List[str],
        use_xdist: bool, log_file: str,
        expected_status: List,
    ) -> set:
        """Run a test group (F2P or P2P) with up to _MAX_TEST_RETRIES retries.

        The checkout + patch is done once. Retries re-run only the files that
        contain still-failing expected tests, without resetting the repo.
        """
        # Checkout and apply patches once
        operator.checkout_commit(spec.base_commit, exclude_file=["patch.diff"], use_docker=True)
        patch_analyzer.apply_patch_content_to_container(
            patch_content,
            docker_executor,
            "/workdir/swap/" + spec.repo_name,
            include_test=False,
        )
        if spec.test_patch:
            operator.apply_patches(spec.test_patch)

        all_passed: set = set()

        for attempt in range(1, self._MAX_TEST_RETRIES + 1):
            remaining = [t for t in expected_tests if t not in all_passed]
            if not remaining:
                break

            if attempt > 1:
                self.logger.info(
                    f"Retry {attempt}/{self._MAX_TEST_RETRIES}: "
                    f"re-running {len({t.split('::')[0] for t in remaining})} file(s) "
                    f"for {len(remaining)} failing test(s)"
                )

            tests_to_run = expected_tests if attempt == 1 else remaining
            retry_log = log_file if attempt == 1 else f"{log_file}.retry{attempt}"

            passed, _ = operator.run_tests_in_container(
                spec.repo_name, tests_to_run, expected_status, use_xdist,
                log_file=retry_log, instance_id=spec.instance_id,
            )
            all_passed.update(passed)

            if all(t in all_passed for t in expected_tests):
                break

        return all_passed

    def evaluate(self, spec, operator, *args, **kwargs) -> Dict[str, Any]:
        """Evaluate agent on spec"""
        # We are not locking repos anymore, since we copy the repo into a unique named volume for each container
        # with self.lock_repo(spec.repo_name):
        try:
            self.agent.setup()

            operator.checkout_commit(spec.base_commit, use_docker=True)

            # Repo-specific env setup (cmake, editable installs, etc.) so
            # the agent sees a fully configured environment when it runs.
            operator.setup_repo_env(spec.repo_name, instance_id=spec.instance_id)

            if isinstance(self.agent, OracleAgent):
                self.agent.spec_patch = spec.patch

            agent_success, agent_output = self.agent.run(
                spec.problem_statement,
                spec.instance_id,
                spec.repo_name,
                spec.base_commit,
            )

            # Copy patch.diff into /logs if it exists
            patch_path = f"/workdir/swap/{spec.repo_name}/patch.diff"
            self.agent.docker_executor.execute(
                f"bash -c 'if [ -f {patch_path} ]; then cp {patch_path} /logs/; fi'", "/"
            )
            # Read the patch content from the container via cat
            cat_exit_code, patch_content = self.agent.docker_executor.execute(
                f"cat {patch_path}", "/", tty=False
            )
            if cat_exit_code != 0:
                patch_content = None

            # Fix /logs ownership so the host user can access files written by the container
            uid, gid = os.getuid(), os.getgid()
            self.agent.docker_executor.execute(f"chown -R {uid}:{gid} /logs", "/")

            if agent_success:
                test_result = self._run_tests(spec, operator, patch_content)

                try:
                    tokens_count = self.agent.parse_agent_log(agent_output)
                except Exception as e:
                    self.logger.warning(f"Token parsing failed, continuing without token counts: {e}")
                    tokens_count = {"Total Tokens": None, "Input Tokens": None, "Output Tokens": None}

                return {
                    "agent": self.agent.agent_config.name,
                    "model": self.agent.agent_config.model,
                    "instance_id": spec.instance_id,
                    **test_result,
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

    def reevaluate(self, spec, operator, patch_content: str, agent_name: str, model_name: str) -> Dict[str, Any]:
        """Re-evaluate a cached patch against the spec's tests, bypassing the agent run."""
        from datetime import datetime, timezone

        reeval_ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

        try:
            operator.checkout_commit(spec.base_commit, use_docker=True)
            test_result = self._run_tests(spec, operator, patch_content)

            return {
                "agent": agent_name,
                "model": model_name,
                "instance_id": spec.instance_id,
                **test_result,
                "reevaluated_at": reeval_ts,
            }

        except Exception as e:
            self.logger.error(f"Error re-evaluating {agent_name} on {spec.instance_id}: {e}")
            return {
                "agent": agent_name,
                "model": model_name,
                "instance_id": spec.instance_id,
                "success": False,
                "error": str(e),
                "reevaluated_at": reeval_ts,
            }

    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """
        Prepare agent-specific resources

        Returns:
            Agent-specific resources (e.g., agentless patches) or None
        """
        return self.agent.prepare_resources()