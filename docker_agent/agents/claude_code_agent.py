"""Specific implementation of Claude Code Agent"""

import shlex
import re
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.core.exceptions import AgentSetupError


class ClaudeCodeAgent(BaseAgent):
    """
    Specific implementation of Claude Code Agent.

    Uses the official claude CLI (https://claude.ai/install.sh) running in
    non-interactive / headless mode via ``--dangerously-skip-permissions -p``.
    Authentication and model selection are forwarded via environment variables:
        ANTHROPIC_AUTH_TOKEN  – API key / auth token
        ANTHROPIC_BASE_URL    – optional proxy base URL (trailing /v1 stripped)
        ANTHROPIC_MODEL       – model name
        ANTHROPIC_API_KEY     – set to empty string so the CLI uses AUTH_TOKEN
        IS_SANDBOX            – set to 1 to suppress interactive prompts
    """

    # ------------------------------------------------------------------ #
    #  Setup                                                               #
    # ------------------------------------------------------------------ #

    def _prepare_agent_code(self):
        """Install Claude Code via the official installation script."""
        self.logger.info("Installing Claude Code via official install script...")

        install_cmd = 'bash -c "curl -fsSL https://claude.ai/install.sh | bash"'
        exit_code, output = self.docker_executor.execute(
            install_cmd, "/workdir", stream=True, timeout=300
        )

        if exit_code != 0:
            raise AgentSetupError(
                f"Failed to install Claude Code: {output}",
                agent_name=self.agent_config.name,
            )

        self.logger.info("Updating /root/.bashrc with PATH...")
        bashrc_append = '\nexport PATH="$HOME/.local/bin:$PATH"\n'
        path_cmd = f'bash -c "echo {shlex.quote(bashrc_append)} >> /root/.bashrc"'
        exit_code, output = self.docker_executor.execute(
            path_cmd, "/root", stream=True
        )
        if exit_code != 0:
            raise AgentSetupError(
                f"Failed to update .bashrc: {output}",
                agent_name=self.agent_config.name,
            )

        self.logger.info("Creating ~/.claude/projects symlink to /logs...")
        symlink_cmd = 'bash -c "mkdir -p ~/.claude && ln -sf /logs ~/.claude/projects"'
        exit_code, output = self.docker_executor.execute(
            symlink_cmd, "/root", stream=True
        )
        if exit_code != 0:
            self.logger.warning(f"Failed to create claude projects symlink: {output}")

        self.logger.info("Claude Code installed successfully")

    # ------------------------------------------------------------------ #
    #  Run                                                                 #
    # ------------------------------------------------------------------ #

    def run(self, problem_statement: str, instance_id: str, repo_name: str) -> tuple[bool, str]:
        """Run claude CLI non-interactively to solve the problem."""
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
            self.logger.error(f"Error running claude: {str(e)}")
            return False, str(e)

    def _build_command(self, escaped_problem: str) -> str:
        """Build the claude CLI headless command with auth env vars."""
        env_prefix = self._build_env_prefix()
        return (
            f"{env_prefix}"
            f'$HOME/.local/bin/claude --dangerously-skip-permissions -p {escaped_problem}'
        )

    def _build_env_prefix(self) -> str:
        """Build the shell environment-variable prefix for the CLI invocation."""
        parts: List[str] = []

        api_key = getattr(self.agent_config, "api_key", None) or ""
        base_url = getattr(self.agent_config, "base_url", None) or ""
        model = getattr(self.agent_config, "model", None) or ""

        # Remove trailing /v1 if present – the claude CLI expects the base URL
        # without the version path segment.
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        parts.append(f"ANTHROPIC_AUTH_TOKEN={shlex.quote(api_key)}")
        parts.append(f"ANTHROPIC_API_KEY=''")          # must be empty so AUTH_TOKEN is used
        parts.append(f"IS_SANDBOX=1")

        if base_url:
            parts.append(f"ANTHROPIC_BASE_URL={shlex.quote(base_url)}")
        if model:
            parts.append(f"ANTHROPIC_MODEL={shlex.quote(model)}")
            # Claude Code might still use Haiku or some other subagent internally, so set those as well to ensure consistent model usage across all components.
            parts.append(f"ANTHROPIC_DEFAULT_OPUS_MODEL={shlex.quote(model)}")
            parts.append(f"ANTHROPIC_DEFAULT_SONNET_MODEL={shlex.quote(model)}")
            parts.append(f"ANTHROPIC_DEFAULT_HAIKU_MODEL={shlex.quote(model)}")
            parts.append(f"CLAUDE_CODE_SUBAGENT_MODEL={shlex.quote(model)}")

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
        Parse claude CLI output to extract token usage if present.

        Claude Code may emit token usage as part of a JSON summary line such as:
            {"type":"result","subtype":"success","cost_usd":...,"usage":{"input_tokens":N,"output_tokens":N}}

        Returns a dict with keys "Total Tokens", "Input Tokens", "Output Tokens".
        All values default to None when not found; never raises.
        """
        import json

        empty: Dict[str, Optional[int]] = {
            "Total Tokens": None,
            "Input Tokens": None,
            "Output Tokens": None,
        }
        try:
            clean_log = self.clean_ansi_codes(log)

            for line in reversed(clean_log.splitlines()):
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                usage = event.get("usage") or {}
                inp = usage.get("input_tokens")
                out = usage.get("output_tokens")
                if inp is not None or out is not None:
                    inp = int(inp) if inp is not None else None
                    out = int(out) if out is not None else None
                    total = (inp or 0) + (out or 0) if (inp is not None or out is not None) else None
                    return {
                        "Input Tokens": inp,
                        "Output Tokens": out,
                        "Total Tokens": total,
                    }

            return empty
        except Exception as e:
            self.logger.warning(f"parse_agent_log failed (token counts unavailable): {e}")
            return empty

    # ------------------------------------------------------------------ #
    #  Resources                                                           #
    # ------------------------------------------------------------------ #

    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """ClaudeCodeAgent does not require pre-computed resources."""
        return None
