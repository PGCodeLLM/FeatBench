"""Agent base abstract class"""

import logging
import shlex
import time
from abc import abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List

from docker_agent.core.types import Container
from docker_agent.parsing.patch_analyzer import PatchAnalyzer
from docker_agent.utils.command_executor import DockerCommandExecutor
from docker_agent.core.exceptions import AgentSetupError


class BaseAgent:
    """Agent base abstract class"""

    def __init__(self, container: Container, agent_config, log_dir=None):
        self.container = container
        self.agent_config = agent_config
        self.logger = logging.getLogger(__name__)
        self.base_path = Path(__file__).parent.parent
        self.path_analyzer = PatchAnalyzer()
        self.docker_executor = DockerCommandExecutor(container, log_dir=log_dir)

    def setup(self):
        """General logic for setting up agent environment"""
        self.logger.info(f"Setting up {self.agent_config.name} environment")

        self._prepare_agent_code()
        self._checkout_branch()
        self._install_dependencies()

        self.logger.info(f"{self.agent_config.name} environment setup completed")

    def _checkout_branch(self):
        """Switch to specified branch"""
        if hasattr(self.agent_config, 'branch') and self.agent_config.branch != "main":
            branch_cmd = f"git checkout {self.agent_config.branch}"
            exit_code, output = self.docker_executor.execute(branch_cmd, "/workdir/agent", stream=True)
            if exit_code != 0:
                self.logger.warning(f"Branch switch failed, continuing with default branch: {output}")

    def _install_dependencies(self):
        """General logic for installing dependencies"""
        if hasattr(self.agent_config, 'install_command') and self.agent_config.install_command:
            self.logger.info(f"Installing {self.agent_config.name} dependencies")
            exit_code, output = self.docker_executor.execute(
                self.agent_config.install_command, "/workdir/agent", stream=True, tty=True, timeout=600
            )
            if exit_code != 0:
                raise AgentSetupError(f"Failed to install agent dependencies: {output}", agent_name=self.agent_config.name)

    @abstractmethod
    def _prepare_agent_code(self):
        """Prepare agent code - must be implemented by subclass (clone or copy)"""
        pass

    @abstractmethod
    def run(
        self,
        problem_statement: str,
        instance_id: str,
        repo_name: str,
        base_commit: str,
    ) -> tuple[bool, str]:
        """Run agent to solve problem - must be implemented by subclass"""
        pass

    # ------------------------------------------------------------------ #
    #  Patch generation                                                   #
    # ------------------------------------------------------------------ #

    _PATCH_DIFF_MAX_RETRIES = 5
    _PATCH_DIFF_RETRY_DELAY = 10  # seconds

    def _generate_patch_diff(
        self,
        repo_workdir: str,
        patch_path: str,
        base_commit: str,
    ) -> tuple[bool, str]:
        """Produce ``patch.diff`` for the changes the agent made.

        Steps (mirrored from the stable harness):
          1. Disable git's pager so streaming exec doesn't hang on `less`.
          2. Remove any nested .git directories the agent may have created
             (e.g. via `git clone` inside the repo) so they don't shadow
             the real working tree.
          3. Stage every file with `git add -A`.
          4. Drop binary files from the index — diffs of binaries are huge
             and useless for evaluation.
          5. Run `git diff --no-color --cached {base_commit}` and write the
             output to ``patch_path``.  Retried up to ``_PATCH_DIFF_MAX_RETRIES``
             times because the diff occasionally fails on flaky filesystems.

        Returns ``(success, message)``.
        """
        self.logger.info(f"Generating git patch from changes in {repo_workdir}")

        # 1. Disable git pager
        self.docker_executor.execute(
            "git config --global core.pager ''", repo_workdir, tty=False, timeout=30
        )

        # 2. Remove nested .git directories (preserve the root one)
        find_cmd = 'find . -type d -name .git -not -path "./.git"'
        find_exit, find_output = self.docker_executor.execute(
            find_cmd, repo_workdir, tty=False, timeout=60
        )
        if find_exit == 0 and find_output:
            nested = [p.strip() for p in find_output.splitlines() if p.strip()]
            if nested:
                self.logger.info(f"Removing {len(nested)} nested .git director(y/ies): {nested}")
                for d in nested:
                    self.docker_executor.execute(
                        f"rm -rf {shlex.quote(d)}", repo_workdir, tty=False, timeout=30
                    )

        # 3. Stage all changes
        add_exit, add_output = self.docker_executor.execute(
            "git add -A", repo_workdir, tty=False, timeout=120
        )
        if add_exit != 0:
            self.logger.warning(f"git add -A failed (continuing): {add_output}")

        # 4. Unstage binary files (numstat reports `- - <file>` for binaries)
        remove_binary_cmd = (
            "git diff --cached --numstat | "
            "awk '$1 == \"-\" && $2 == \"-\" {print $3}' | "
            "xargs -r git reset HEAD --"
        )
        bin_exit, bin_output = self.docker_executor.execute(
            f"bash -c {shlex.quote(remove_binary_cmd)}",
            repo_workdir, tty=False, timeout=60,
        )
        if bin_exit != 0:
            self.logger.warning(f"Failed to drop binary files from index: {bin_output}")

        # 5. Generate the diff with retries
        diff_cmd = (
            f"git diff --no-color --cached {shlex.quote(base_commit)} "
            f"> {shlex.quote(patch_path)}"
        )
        last_err = ""
        for attempt in range(1, self._PATCH_DIFF_MAX_RETRIES + 1):
            self.logger.info(
                f"git diff attempt {attempt}/{self._PATCH_DIFF_MAX_RETRIES}"
            )
            diff_exit, diff_output = self.docker_executor.execute(
                f"bash -c {shlex.quote(diff_cmd)}",
                repo_workdir, tty=False, timeout=300,
            )
            if diff_exit == 0:
                self.logger.info(f"git diff succeeded on attempt {attempt}")
                return True, ""
            last_err = diff_output
            self.logger.warning(f"git diff failed (attempt {attempt}): {diff_output}")
            if attempt < self._PATCH_DIFF_MAX_RETRIES:
                time.sleep(self._PATCH_DIFF_RETRY_DELAY)

        self.logger.error(
            f"Failed to generate git patch after {self._PATCH_DIFF_MAX_RETRIES} retries"
        )
        return False, last_err

    @abstractmethod
    def parse_agent_log(self, log: str) -> Dict[str, Optional[int]]:
        """Parse agent log to extract token usage - must be implemented by subclass"""
        pass

    @abstractmethod
    def prepare_resources(self) -> Optional[List[Dict[str, Any]]]:
        """
        Prepare agent-specific resources before evaluation - must be implemented by subclass (clone or copy)

        Returns:
            Agent-specific resources (e.g., agentless patches) or None
        """
        return None