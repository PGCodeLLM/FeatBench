"""Specific implementation of Claude Code Agent"""

import io
import shlex
import re
import tarfile
from pathlib import Path
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.core.exceptions import AgentSetupError


class ClaudeCodeAgent(BaseAgent):
    """
    Specific implementation of Claude Code Agent.

    Uses the official claude CLI (https://claude.ai/install.sh) running in
    non-interactive / headless mode via ``--dangerously-skip-permissions -p``.
    Authentication and model selection are forwarded via environment variables:

    API-key mode (default):
        ANTHROPIC_AUTH_TOKEN  – API key / auth token
        ANTHROPIC_API_KEY     – set to empty string so the CLI uses AUTH_TOKEN
        ANTHROPIC_BASE_URL    – optional proxy base URL (trailing /v1 stripped)

    OAuth mode (api_key starts with ``sk-ant-oat``):
        CLAUDE_CODE_OAUTH_TOKEN – OAuth token; no ANTHROPIC_* key vars are set

    Common:
        ANTHROPIC_MODEL       – model name
        IS_SANDBOX            – set to 1 to suppress interactive prompts
    """

    # ------------------------------------------------------------------ #
    #  Setup                                                               #
    # ------------------------------------------------------------------ #

    def _prepare_agent_code(self):
        """Install Claude Code – either from a pinned local binary or the official install script.

        Which path is taken is controlled by the ``use_local_binary`` field in the
        agent configuration (default: ``False``):

        * ``use_local_binary = true``  – copy the ``claude`` binary that lives in
          the project root into ``~/.local/bin/`` inside the container and make it
          executable.  Raises :class:`AgentSetupError` if the binary is missing.
        * ``use_local_binary = false`` (default) – download and install the latest
          release via ``https://claude.ai/install.sh``.
        """
        use_local_binary = getattr(self.agent_config, "use_local_binary", False)

        if use_local_binary:
            self._install_local_binary()
        else:
            self._install_from_script()

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
    #  Installation helpers                                                #
    # ------------------------------------------------------------------ #

    def _install_from_script(self):
        """Download and install the latest Claude Code via the official install script."""
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

    def _install_local_binary(self):
        """Copy the pinned ``claude`` binary from the project root into the container.

        The binary must exist at ``<project_root>/claude``.  It is copied to
        ``/root/.local/bin/claude`` inside the container and made executable.
        """
        # Project root is one level above the docker_agent package directory.
        binary_path = self.base_path.parent / "claude"

        if not binary_path.exists():
            raise AgentSetupError(
                f"Local claude binary not found at '{binary_path}'. "
                "Either place the binary there or set use_local_binary = false "
                "to download the latest release instead."
                "Download the binary from a URL similar to 'https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases/2.1.72/linux-x64/claude' (exact URL may vary based on version and platform).",
                agent_name=self.agent_config.name,
            )

        self.logger.info(f"Copying local claude binary from '{binary_path}' into container...")

        # Ensure destination directory exists inside the container.
        mkdir_exit, mkdir_out = self.docker_executor.execute(
            "mkdir -p /root/.local/bin", "/root", stream=False
        )
        if mkdir_exit != 0:
            raise AgentSetupError(
                f"Failed to create /root/.local/bin in container: {mkdir_out}",
                agent_name=self.agent_config.name,
            )

        # Pack the binary into an in-memory tar archive and stream it into the container.
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(str(binary_path), arcname="claude")
        tar_data = tar_buffer.getvalue()

        success = self.container.put_archive("/root/.local/bin", tar_data)
        if not success:
            raise AgentSetupError(
                "Failed to copy claude binary into container (put_archive returned False).",
                agent_name=self.agent_config.name,
            )

        # Make the binary executable.
        chmod_exit, chmod_out = self.docker_executor.execute(
            "chmod +x /root/.local/bin/claude", "/root", stream=False
        )
        if chmod_exit != 0:
            raise AgentSetupError(
                f"Failed to chmod +x /root/.local/bin/claude: {chmod_out}",
                agent_name=self.agent_config.name,
            )

        self.logger.info("Local claude binary installed successfully.")

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

        # OAuth tokens (sk-ant-oat…) are passed via CLAUDE_CODE_OAUTH_TOKEN;
        # regular API keys use the AUTH_TOKEN / empty API_KEY pair.
        is_oauth = api_key.startswith("sk-ant-oat")
        if is_oauth:
            parts.append(f"CLAUDE_CODE_OAUTH_TOKEN={shlex.quote(api_key)}")
        else:
            parts.append(f"ANTHROPIC_AUTH_TOKEN={shlex.quote(api_key)}")
            parts.append(f"ANTHROPIC_API_KEY=''")      # must be empty so AUTH_TOKEN is used
        parts.append(f"IS_SANDBOX=1")
        parts.append(f"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1")  # Equivalent of setting DISABLE_AUTOUPDATER, DISABLE_BUG_COMMAND, DISABLE_ERROR_REPORTING, and DISABLE_TELEMETRY

        if base_url and not is_oauth:
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
