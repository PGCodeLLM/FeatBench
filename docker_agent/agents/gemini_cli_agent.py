"""Specific implementation of Gemini CLI Agent"""

import json
import shlex
import re
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.core.exceptions import AgentSetupError


class GeminiCLIAgent(BaseAgent):
    """
    Specific implementation of Gemini CLI Agent.

    Uses gemini-cli (https://github.com/google-gemini/gemini-cli) running in
    headless / non-interactive mode.  When a LiteLLM proxy is configured the
    following environment variables are forwarded to the CLI process:
        GOOGLE_GEMINI_BASE_URL  – LiteLLM proxy base URL
        GEMINI_API_KEY          – LiteLLM proxy API key
        GEMINI_MODEL            – model name (overrides --model flag)
    """

    # ------------------------------------------------------------------ #
    #  Setup                                                               #
    # ------------------------------------------------------------------ #

    def _prepare_agent_code(self):
        """Install Node.js (via nvm) and gemini-cli globally via npm."""
        self.logger.info("Installing Node.js via nvm for gemini-cli...")

        # Install nvm and a current LTS Node, then install gemini-cli in one
        # compound shell command so that the nvm environment is available for
        # the npm install step.
        install_cmd = (
            "bash -c '"
            "export NVM_DIR=\"$HOME/.nvm\" && "
            "curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash && "
            "source \"$NVM_DIR/nvm.sh\" && "
            "nvm install --lts && "
            "npm install -g @google/gemini-cli"
            "'"
        )
        exit_code, output = self.docker_executor.execute(
            install_cmd, "/workdir", stream=True, timeout=600
        )

        if exit_code != 0:
            raise AgentSetupError(
                f"Failed to install gemini-cli: {output}",
                agent_name=self.agent_config.name,
            )

        self.logger.info("Creating ~/.gemini/tmp symlink to /logs...")
        symlink_cmd = 'bash -c "mkdir -p ~/.gemini && ln -sf /logs ~/.gemini/tmp"'
        exit_code, output = self.docker_executor.execute(
            symlink_cmd, "/root", stream=True
        )
        if exit_code != 0:
            self.logger.warning(f"Failed to create gemini tmp symlink: {output}")

    # ------------------------------------------------------------------ #
    #  Run                                                                 #
    # ------------------------------------------------------------------ #

    def run(self, problem_statement: str, instance_id: str, repo_name: str) -> tuple[bool, str]:
        """Run gemini-cli non-interactively to solve the problem."""
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
            self.logger.error(f"Error running gemini-cli: {str(e)}")
            return False, str(e)

    def _build_command(self, escaped_problem: str) -> str:
        """Build the gemini-cli headless command with LiteLLM proxy env vars."""
        env_prefix = self._build_env_prefix()
        # Prepend the nvm node bin dir to PATH so the gemini binary is found.
        # $(ls -d ...) picks whichever node version was installed by nvm --lts.
        node_bin = '$(ls -d "$HOME/.nvm/versions/node/"*/bin | tail -1)'
        return (
            f'{env_prefix}PATH="{node_bin}:$PATH" '
            f'gemini -p {escaped_problem} '
            f"--yolo "
            f"--output-format json"
        )

    def _build_env_prefix(self) -> str:
        """Build the shell environment-variable prefix for the CLI invocation."""
        parts: List[str] = []

        if hasattr(self.agent_config, "base_url") and self.agent_config.base_url:
            parts.append(
                f"GOOGLE_GEMINI_BASE_URL={shlex.quote(str(self.agent_config.base_url))}"
            )
        if hasattr(self.agent_config, "api_key") and self.agent_config.api_key:
            parts.append(
                f"GEMINI_API_KEY={shlex.quote(str(self.agent_config.api_key))}"
            )
        if hasattr(self.agent_config, "model") and self.agent_config.model:
            parts.append(
                f"GEMINI_MODEL={shlex.quote(str(self.agent_config.model))}"
            )

        return (" ".join(parts) + " ") if parts else ""

    # ------------------------------------------------------------------ #
    #  Evaluate                                                            #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Log parsing                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def clean_ansi_codes(text: str) -> str:
        """Strip ANSI escape codes from a string."""
        return re.compile(r"\x1b\[[0-9;]*[mGKHF]").sub("", text)

    def parse_agent_log(self, log: str) -> Dict[str, Optional[int]]:
        """
        Parse gemini-cli ``--output-format json`` output to extract token usage.

        The CLI emits a single JSON object:
            {
              "stats": {
                "models": {
                  "<model>": {
                    "tokens": {"input": N, "candidates": N, "total": N, ...}
                  }
                }
              }
            }

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

            # The output may be prefixed with non-JSON lines (progress text).
            # Find the last '{' … '}' block that parses successfully.
            event: Optional[Dict] = None
            for line in reversed(clean_log.splitlines()):
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

            # Also try parsing the whole stripped log as one JSON object.
            if event is None:
                try:
                    event = json.loads(clean_log.strip())
                except json.JSONDecodeError:
                    return empty

            if not isinstance(event, dict):
                return empty

            stats = event.get("stats", {})
            if not isinstance(stats, dict):
                return empty

            # ---- --output-format json: stats.models.<model>.tokens ---- #
            models = stats.get("models", {})
            if isinstance(models, dict) and models:
                input_total = candidates_total = grand_total = 0
                for model_data in models.values():
                    t = model_data.get("tokens", {}) if isinstance(model_data, dict) else {}
                    input_total += t.get("input", 0) or 0
                    candidates_total += t.get("candidates", 0) or 0
                    grand_total += t.get("total", 0) or 0
                return {
                    "Input Tokens": input_total or None,
                    "Output Tokens": candidates_total or None,
                    "Total Tokens": grand_total or (
                        (input_total + candidates_total) if (input_total or candidates_total) else None
                    ),
                }

            # ---- Fallback: flat camelCase keys on the stats object ---- #
            def _pick(d: Dict, *keys) -> Optional[int]:
                for k in keys:
                    v = d.get(k)
                    if v is not None:
                        try:
                            return int(v)
                        except (TypeError, ValueError):
                            pass
                return None

            inp = _pick(stats, "inputTokenCount", "inputTokens", "input_tokens")
            out = _pick(stats, "outputTokenCount", "outputTokens", "output_tokens", "candidatesTokenCount")
            tot = _pick(stats, "totalTokenCount", "totalTokens", "total_tokens")
            return {
                "Input Tokens": inp,
                "Output Tokens": out,
                "Total Tokens": tot if tot is not None else (
                    (inp + out) if (inp is not None and out is not None) else None
                ),
            }
        except Exception as e:
            self.logger.warning(f"parse_agent_log failed (token counts unavailable): {e}")
            return empty

    # ------------------------------------------------------------------ #
    #  Resources                                                           #
    # ------------------------------------------------------------------ #

    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """GeminiCLIAgent does not require pre-computed resources."""
        return None
