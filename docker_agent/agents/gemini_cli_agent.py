"""Specific implementation of Gemini CLI Agent"""

import json
import shlex
import re
from typing import Dict, Any, Optional, List

from docker_agent.agents.base import BaseAgent
from docker_agent.core.types import Spec
from docker_agent.container.container_operator import ContainerOperator
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

    def evaluate(self, spec: Spec, operator: ContainerOperator) -> Dict[str, Any]:
        """
        Evaluate GeminiCLIAgent on a specific spec.

        Evaluation pipeline:
        1. Setup the agent environment.
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
