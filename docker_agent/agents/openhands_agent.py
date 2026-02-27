"""Specific implementation of OpenHands Agent"""

import json
import shlex
import re
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.core.exceptions import AgentSetupError


class OpenHandsAgent(BaseAgent):
    """
    Specific implementation of OpenHands Agent.

    Uses the official OpenHands CLI installed via ``uv tool install openhands``
    running in headless mode via ``--headless -t``.
    Authentication and model selection are forwarded via environment variables
    combined with ``--override-with-envs``:
        LLM_API_KEY   – API key for the LLM provider
        LLM_MODEL     – model name
        LLM_BASE_URL  – custom LLM base URL (optional)
    """

    # ------------------------------------------------------------------ #
    #  Setup                                                               #
    # ------------------------------------------------------------------ #

    def _prepare_agent_code(self):
        """Install OpenHands CLI via uv tool install (requires Python 3.12+)."""
        self.logger.info("Installing OpenHands CLI via uv tool install...")

        install_cmd = "uv tool install openhands --python 3.12"
        exit_code, output = self.docker_executor.execute(
            install_cmd, "/workdir", stream=True, timeout=300
        )

        if exit_code != 0:
            raise AgentSetupError(
                f"Failed to install OpenHands CLI: {output}",
                agent_name=self.agent_config.name,
            )

        self.logger.info("Updating shell PATH via uv tool update-shell...")
        exit_code, output = self.docker_executor.execute(
            "uv tool update-shell", "/workdir", stream=True
        )
        if exit_code != 0:
            self.logger.warning(f"uv tool update-shell failed (non-fatal): {output}")

        self.logger.info("OpenHands CLI installed successfully")

    # ------------------------------------------------------------------ #
    #  Run                                                                 #
    # ------------------------------------------------------------------ #

    def run(self, problem_statement: str, instance_id: str, repo_name: str) -> tuple[bool, str]:
        """Run OpenHands CLI in headless mode to solve the problem."""
        self.logger.info(
            f"Running {self.agent_config.name} to solve problem {instance_id}"
        )

        repo_workdir = f"/workdir/swap/{repo_name}"
        patch_path = f"{repo_workdir}/patch.diff"

        try:
            escaped_problem = shlex.quote(problem_statement)
            run_cmd = self._build_command(escaped_problem)

            exit_code, agent_output = self.docker_executor.execute(
                run_cmd, repo_workdir, stream=True, tty=True
            )

            if exit_code != 0:
                return False, agent_output

            # Capture the changes made by the agent as a unified diff.
            diff_cmd = f"git diff > {patch_path}"
            diff_exit, diff_output = self.docker_executor.execute(
                diff_cmd, repo_workdir, stream=True
            )

            if diff_exit != 0:
                self.logger.warning(f"Failed to generate git diff: {diff_output}")
                return False, agent_output

            return True, agent_output

        except Exception as e:
            self.logger.error(f"Error running openhands: {str(e)}")
            return False, str(e)

    def _build_command(self, escaped_problem: str) -> str:
        """Build the openhands headless command with auth env vars."""
        env_prefix = self._build_env_prefix()
        return (
            f"{env_prefix}"
            f"$HOME/.local/bin/openhands --headless --json "
            f"-t {escaped_problem} --override-with-envs "
            f"| tee /logs/output.jsonl"
        )

    def _build_env_prefix(self) -> str:
        """Build the shell environment-variable prefix for the CLI invocation."""
        parts: List[str] = []

        api_key = getattr(self.agent_config, "api_key", None) or ""
        base_url = getattr(self.agent_config, "base_url", None) or ""
        model = getattr(self.agent_config, "model", None) or ""

        if api_key:
            parts.append(f"LLM_API_KEY={shlex.quote(api_key)}")
        if model:
            parts.append(f"LLM_MODEL={shlex.quote(model)}")
        if base_url:
            parts.append(f"LLM_BASE_URL={shlex.quote(base_url)}")

        return (" ".join(parts) + " ") if parts else ""

    # ------------------------------------------------------------------ #
    #  Log parsing                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def clean_ansi_codes(text: str) -> str:
        """Strip ANSI escape codes from a string."""
        return re.compile(r"\x1b\[[0-9;]*[mGKHF]").sub("", text)

    def parse_agent_log(self, log: str) -> Dict[str, Optional[int]]:
        """
        Parse OpenHands CLI JSONL output (``--json``) to extract token usage.

        When run with ``--json``, OpenHands emits one JSON object per line.
        We accumulate token counts across all events that carry usage data,
        looking for the following key shapes:

            {"usage": {"prompt_tokens": N, "completion_tokens": N, ...}}
            {"usage": {"input_tokens": N, "output_tokens": N, ...}}
            {"metrics": {"total_input_tokens": N, "total_output_tokens": N}}

        Returns a dict with keys "Total Tokens", "Input Tokens", "Output Tokens".
        All values default to None when not found; never raises.
        """
        empty: Dict[str, Optional[int]] = {
            "Total Tokens": None,
            "Input Tokens": None,
            "Output Tokens": None,
        }
        try:
            clean_log = self.clean_ansi_codes(log)

            total_input = 0
            total_output = 0
            found_any = False

            for line in clean_log.splitlines():
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Probe several possible locations for usage data
                for key in ("usage", "metrics", "token_usage"):
                    usage = event.get(key)
                    if not isinstance(usage, dict):
                        continue

                    inp = (
                        usage.get("prompt_tokens")
                        or usage.get("input_tokens")
                        or usage.get("total_input_tokens")
                    )
                    out = (
                        usage.get("completion_tokens")
                        or usage.get("output_tokens")
                        or usage.get("total_output_tokens")
                    )

                    if inp is not None or out is not None:
                        found_any = True
                        total_input += int(inp) if inp is not None else 0
                        total_output += int(out) if out is not None else 0
                        break  # avoid double-counting across keys in same event

            if found_any:
                return {
                    "Input Tokens": total_input,
                    "Output Tokens": total_output,
                    "Total Tokens": total_input + total_output,
                }

            return empty
        except Exception as e:
            self.logger.warning(f"parse_agent_log failed (token counts unavailable): {e}")
            return empty

    # ------------------------------------------------------------------ #
    #  Resources                                                           #
    # ------------------------------------------------------------------ #

    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """OpenHandsAgent does not require pre-computed resources."""
        return None
