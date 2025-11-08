"""Specific implementation of Trae-Agent"""

import shlex
import re
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.core.types import Spec
from docker_agent.container.container_operator import ContainerOperator
from docker_agent.core.exceptions import AgentSetupError


class TraeAgent(BaseAgent):
    """Specific implementation of Trae-Agent"""

    def _prepare_agent_code(self):
        """Clone trae-agent repository"""
        self.docker_executor.execute("mkdir -p agent/", "/workdir", stream=True)
        clone_cmd = f"git clone {self.agent_config.repo_url} agent/"
        exit_code, output = self.docker_executor.execute(clone_cmd, "/workdir", stream=True, timeout=300)

        if exit_code != 0:
            raise AgentSetupError(f"Failed to clone agent repository: {output}", agent_name=self.agent_config.name)

    def run(self, problem_statement: str, instance_id: str, repo_name: str) -> tuple[bool, str]:
        """Run trae-agent to solve problem"""
        self.logger.info(f"Running {self.agent_config.name} to solve problem {instance_id}")

        try:
            escaped_problem = shlex.quote(problem_statement)
            run_cmd = self._build_command(escaped_problem, repo_name)

            exit_code, agent_output = self.docker_executor.execute(
                run_cmd, "/workdir/agent", stream=True, tty=True
            )

            success = exit_code == 0
            return success, agent_output

        except Exception as e:
            self.logger.error(f"Error running trae-agent: {str(e)}")
            return False, str(e)

    def _build_command(self, escaped_problem: str, repo_name: str) -> str:
        """Build trae-agent run command"""
        return (".venv/bin/python3.12 -m trae_agent.cli run "
            f"{escaped_problem} "
            "--must-patch "
            f"--patch-path /workdir/swap/{repo_name}/patch.diff "
            f"--working-dir /workdir/swap/{repo_name} "
            f"--model {self.agent_config.model} "
            f"--provider {self.agent_config.provider} "
            f"--config-file /workdir/swap/trae-agent/trae_config.yaml")

    def evaluate(self, spec: Spec, operator: ContainerOperator) -> Dict[str, Any]:
        """
        Evaluate TraeAgent on a specific spec

        This method contains TraeAgent-specific evaluation logic:
        - Setup agent environment
        - Run agent on problem
        - Extract tokens from output
        """
        from docker_agent.parsing.pytest_parser import TestStatus

        try:
            self.setup()

            operator.checkout_commit(spec.base_commit, use_docker=True)
            agent_success, agent_output = self.run(
                spec.problem_statement,
                spec.instance_id,
                spec.repo_name
            )

            if agent_success:
                operator.checkout_commit(spec.base_commit, exclude_file=["patch.diff"], use_docker=True)

                self.path_analyzer.apply_patch_file_to_container(
                    self.base_path / "swap" / spec.repo_name / "patch.diff", self.docker_executor, "/workdir/swap/" + spec.repo_name, include_test=False
                )

                if spec.test_patch:
                    operator.apply_patches(spec.test_patch)

                f2p_tests, p2p_tests = [], []
                if spec.FAIL_TO_PASS:
                    f2p_tests.extend(spec.FAIL_TO_PASS.split(", "))
                if spec.PASS_TO_PASS:
                    p2p_tests.extend(spec.PASS_TO_PASS.split(", "))

                f2p_passed, _ = set(), set()
                if f2p_tests:
                    f2p_passed, _ = operator.run_tests_in_container(
                        spec.repo_name, f2p_tests, [TestStatus.PASSED], False
                    )

                operator.checkout_commit(spec.base_commit, exclude_file=["patch.diff"], use_docker=True)

                self.path_analyzer.apply_patch_file_to_container(
                    self.base_path / "swap" / spec.repo_name / "patch.diff", self.docker_executor, "/workdir/swap/" + spec.repo_name, include_test=False
                )

                if spec.test_patch:
                    operator.apply_patches(spec.test_patch)

                p2p_passed, _ = set(), set()
                if p2p_tests:
                    p2p_passed, _ = operator.run_tests_in_container(
                        spec.repo_name, p2p_tests, [TestStatus.PASSED]
                    )

                success_f2p = all(test in f2p_passed for test in f2p_tests)
                success_p2p = all(test in p2p_passed for test in p2p_tests)
                success = success_f2p and success_p2p

                total_tokens = self.parse_agent_log(agent_output)

                return {
                    "agent": self.agent_config.name,
                    "model": self.agent_config.model,
                    "instance_id": spec.instance_id,
                    "success_f2p": success_f2p,
                    "success_p2p": success_p2p,
                    "success": success,
                    "passed_f2p_tests": list(f2p_passed),
                    "passed_p2p_tests": list(p2p_passed),
                    "expected_f2p_tests": f2p_tests,
                    "expected_p2p_tests": p2p_tests,
                    "total_tokens": total_tokens,
                }
            else:
                return {
                    "agent": self.agent_config.name,
                    "model": self.agent_config.model,
                    "instance_id": spec.instance_id,
                    "success": False,
                    "error": agent_output,
                }

        except Exception as e:
            self.logger.error(f"Error evaluating {self.agent_config.name} on {spec.instance_id}: {e}")
            return {
                "agent": self.agent_config.name,
                "model": self.agent_config.model,
                "instance_id": spec.instance_id,
                "success": False,
                "error": str(e),
            }

    @staticmethod
    def clean_ansi_codes(text: str) -> str:
        """Clean ANSI escape codes"""
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        return ansi_escape.sub('', text)

    def parse_agent_log(self, log: str) -> Optional[int]:
        """
        Parse agent log to extract total tokens

        Args:
            log: Agent log text

        Returns:
            Total tokens or None if not found
        """
        # Clean ANSI escape codes
        clean_log = self.clean_ansi_codes(log)

        execution_summary_start = clean_log.find("Execution Summary")
        if execution_summary_start == -1:
            return None

        summary_section = clean_log[execution_summary_start:]

        # Extract Total Tokens
        for line in summary_section.split('\n'):
            line = line.strip()
            if line.startswith("│ Total Tokens"):
                # Extract number
                match = re.search(r'│ Total Tokens\s*│\s*(\d+)', line)
                if match:
                    return int(match.group(1))

        return None
    
    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """
        TraeAgent doesn't need special resources

        Returns:
            None
        """
        return None
