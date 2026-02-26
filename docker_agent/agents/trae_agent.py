"""Specific implementation of Trae-Agent"""

import shlex
import re
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
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
            f"--config-file /workdir/swap/trae-agent/{self.agent_config.config_file}")

    @staticmethod
    def clean_ansi_codes(text: str) -> str:
        """Clean ANSI escape codes"""
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        return ansi_escape.sub('', text)

    def parse_agent_log(self, log: str) -> Dict[str, Optional[int]]:
        """
        Parse agent log to extract token usage

        Args:
            log: Agent log text

        Returns:
            Dict with "Total Tokens", "Input Tokens", "Output Tokens"
        """
        empty: Dict[str, Optional[int]] = {
            "Total Tokens": None,
            "Input Tokens": None,
            "Output Tokens": None,
        }
        # Clean ANSI escape codes
        clean_log = self.clean_ansi_codes(log)

        execution_summary_start = clean_log.find("Execution Summary")
        if execution_summary_start == -1:
            return empty

        summary_section = clean_log[execution_summary_start:]

        tokens_count: Dict[str, Optional[int]] = {
            "Total Tokens": None,
            "Input Tokens": None,
            "Output Tokens": None,
        }
        for line in summary_section.split('\n'):
            line = line.strip()
            for token_type in ["Input Tokens", "Output Tokens", "Total Tokens"]:
                if line.startswith(f"│ {token_type}"):
                    match = re.search(rf'│ {token_type}\s*│\s*(\d+)', line)
                    if match:
                        tokens_count[token_type] = int(match.group(1))

        return tokens_count
    
    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """
        TraeAgent doesn't need special resources

        Returns:
            None
        """
        return None
