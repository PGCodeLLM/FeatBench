"""Specific implementation of Claude Code Agent"""

import shlex
import re
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.core.types import Spec
from docker_agent.container.container_operator import ContainerOperator
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
    #  Evaluate                                                            #
    # ------------------------------------------------------------------ #

    def evaluate(self, spec: Spec, operator: ContainerOperator) -> Dict[str, Any]:
        """
        Evaluate ClaudeCodeAgent on a specific spec.

        Evaluation pipeline:
        1. Setup the agent environment (install claude CLI).
        2. Checkout the base commit.
        3. Run the agent → produces patch.diff via git diff.
        4. Checkout base commit (preserving patch.diff), apply patch + test
           patch, run FAIL_TO_PASS tests.
        5. Repeat step 4 for PASS_TO_PASS tests.
        6. Return a structured result dict.
        """
        from docker_agent.parsing.pytest_parser import TestStatus

        try:
            self.setup()

            operator.checkout_commit(spec.base_commit, use_docker=True)
            agent_success, agent_output = self.run(
                spec.problem_statement,
                spec.instance_id,
                spec.repo_name,
            )

            if agent_success:
                # ---- FAIL_TO_PASS ----------------------------------------
                operator.checkout_commit(
                    spec.base_commit,
                    exclude_file=["patch.diff"],
                    use_docker=True,
                )

                self.path_analyzer.apply_patch_file_to_container(
                    self.base_path / "swap" / spec.repo_name / "patch.diff",
                    self.docker_executor,
                    "/workdir/swap/" + spec.repo_name,
                    include_test=False,
                )

                if spec.test_patch:
                    operator.apply_patches(spec.test_patch)

                f2p_tests: List[str] = []
                p2p_tests: List[str] = []
                if spec.FAIL_TO_PASS:
                    f2p_tests.extend(spec.FAIL_TO_PASS.split(", "))
                if spec.PASS_TO_PASS:
                    p2p_tests.extend(spec.PASS_TO_PASS.split(", "))

                f2p_passed: set = set()
                if f2p_tests:
                    f2p_passed, _ = operator.run_tests_in_container(
                        spec.repo_name, f2p_tests, [TestStatus.PASSED], False
                    )

                # ---- PASS_TO_PASS ----------------------------------------
                operator.checkout_commit(
                    spec.base_commit,
                    exclude_file=["patch.diff"],
                    use_docker=True,
                )

                self.path_analyzer.apply_patch_file_to_container(
                    self.base_path / "swap" / spec.repo_name / "patch.diff",
                    self.docker_executor,
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
                    tokens_count = self.parse_agent_log(agent_output)
                except Exception as e:
                    self.logger.warning(f"Token parsing failed, continuing without token counts: {e}")
                    tokens_count = {"Total Tokens": None, "Input Tokens": None, "Output Tokens": None}

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
                    "total_tokens": tokens_count["Total Tokens"],
                    "input_tokens": tokens_count["Input Tokens"],
                    "output_tokens": tokens_count["Output Tokens"],
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
            self.logger.error(
                f"Error evaluating {self.agent_config.name} on {spec.instance_id}: {e}"
            )
            return {
                "agent": self.agent_config.name,
                "model": self.agent_config.model,
                "instance_id": spec.instance_id,
                "success": False,
                "error": str(e),
            }

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
