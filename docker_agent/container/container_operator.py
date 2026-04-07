"""Container operator class"""

import logging
from pathlib import Path
from typing import List, Dict, Optional, Set

from docker_agent.core.types import TestStatus, CodeChange, Container
from docker_agent.parsing.patch_analyzer import PatchAnalyzer, PatchInfo
from docker_agent.parsing.pytest_parser import PytestResultParser
from docker_agent.utils.command_executor import LocalCommandExecutor, DockerCommandExecutor
from docker_agent.core.exceptions import ContainerOperationError
from docker_agent.container.cache_manager import get_cpu_limit

# ---------------------------------------------------------------------------
# Per-repo / per-instance pytest configuration (mirrored from stable harness)
# ---------------------------------------------------------------------------

_REPO_PYTEST_TIMEOUT: dict[str, int] = {
    "faststream": 20,
    "python-sdk": 60,
}
_DEFAULT_PYTEST_TIMEOUT = 1800

# Repos that actually benefit from xdist parallelism.
_XDIST_REPOS: set[str] = {"pybamm", "faststream", "xarray"}

# Instance-level: specific test files that need a different -n override.
_INSTANCE_FILE_XDIST_OVERRIDES: dict[str, dict[str, int]] = {
    "pybamm-team__PyBaMM-4073": {
        "tests/integration/test_models/test_full_battery_models/test_lithium_ion/test_spm.py": 1,
        "tests/unit/test_serialisation/test_serialisation.py": 1,
    },
    "pydata__xarray-10161": {
        "xarray/tests/test_backends.py": 1,
    },
    "pydata__xarray-10274": {
        "xarray/tests/test_backends.py": 1,
    },
}

# Repo-level: files that must run in a separate pytest invocation.
_REPO_ISOLATED_TEST_FILES: dict[str, set[str]] = {
    "tox": {
        "tests/tox_env/python/test_python_runner.py",
    },
    "dvc": {
        "tests/integration/test_studio_live_experiments.py",
    },
    "xarray": {
        "xarray/tests/test_strategies.py",
        "xarray/tests/test_backends.py",
    },
    "python-sdk": {
        "tests/shared/test_streamable_http.py",
    },
}


def _get_pytest_timeout(repo_name: str) -> int:
    """Return the per-test pytest-timeout value for the given repo."""
    repo_lower = repo_name.lower()
    for key, timeout in _REPO_PYTEST_TIMEOUT.items():
        if key in repo_lower:
            return timeout
    return _DEFAULT_PYTEST_TIMEOUT


def _should_use_xdist(repo_name: str) -> bool:
    """Return True if this repo should use xdist parallelism."""
    repo_lower = repo_name.lower()
    return any(r in repo_lower for r in _XDIST_REPOS)


class ContainerOperator:
    """Container operator class"""

    def __init__(self, repo: str, container: Optional[Container] = None, log_dir=None):
        self.container = container
        self.logger = logging.getLogger(__name__)
        self.docker_executor = DockerCommandExecutor(container, log_dir=log_dir)
        self.local_executor = LocalCommandExecutor()
        self.base_path = Path(__file__).parent.parent  # Go up to the root
        self.repo = repo
        self.repo_name = repo.split("/")[-1]
        self.patch_analyzer = PatchAnalyzer()

        if self.container:
            self.docker_executor.execute(f"git config --global --add safe.directory /workdir/swap/{self.repo_name}")

    def repo_clone(self, use_docker=True):
        """Clone repository"""
        # Check if directory already exists
        if use_docker:
            check_cmd = f"test -d swap/{self.repo_name}"
            exit_code, _ = self.docker_executor.execute(check_cmd)
        else:
            repo_path = self.base_path / "swap" / self.repo_name
            if repo_path.exists():
                exit_code = 0
            else:
                exit_code = 1

        if exit_code == 0:
            self.logger.info(f"Directory {self.repo_name} already exists, skipping clone")
            return

        repo_url = f"https://github.com/{self.repo}.git"
        command = f"git clone {repo_url}"

        if use_docker:
            exit_code, output = self.docker_executor.execute(command, "/workdir/swap", stream=True, tty=True)
        else:
            exit_code, output = self.local_executor.execute(command, self.base_path / "swap", stream=True, tty=True)

        self.logger.info(f"Command completed, return code: {exit_code}")
        if exit_code is not None and exit_code != 0:
            self.logger.error(f"Command execution failed: {command}\nError: {output}")
            raise ContainerOperationError(f"Command execution failed: {command}\nError: {output}", container_id=self.container.id if self.container else None)

    def checkout_commit(self, commit_hash: str, exclude_file: List[str] = None, use_docker=True) -> None:
        """Switch to specified commit"""
        self.logger.info(f"Forcibly switching to commit: {commit_hash}")
        if exclude_file is None:
            exclude_file = []
        commands = [
            "git reset --hard",
            "git clean -fd " + " ".join([f"-e {f}" for f in exclude_file]),
            f"git checkout {commit_hash}"
        ]

        for cmd in commands:
            if use_docker:
                exit_code, output = self.docker_executor.execute(cmd, str(Path("/workdir/swap") / self.repo_name), tty=False, timeout=30)
            else:
                exit_code, output = self.local_executor.execute(cmd, self.base_path / "swap" / self.repo_name, tty=False, timeout=30)

            if exit_code != 0:
                self.logger.error(f"Command execution failed: {cmd}\nError: {output}")
                raise ContainerOperationError(f"Command execution failed: {cmd}\nError: {output}", container_id=self.container.id if self.container else None)

            self.logger.info(f"Execution successful: {cmd.split('&&')[-1].strip()}")

        self.logger.info(f"Successfully forcibly switched to commit: {commit_hash}")

    def apply_patches(self, file_changes: List[Dict]) -> List[str]:
        """Apply file changes - compatible with original interface, using unified patch analyzer"""
        patches = []
        for change in file_changes:
            filename = change.get("filename")
            patch_content = change.get("patch", "")
            status = change.get("status", "")

            if not filename or not patch_content or not status:
                continue

            patch_info = PatchInfo(
                filename=filename,
                status=status,
                patch_content=patch_content,
                is_test_file=self.patch_analyzer.is_test_file(filename)
            )
            patches.append(patch_info)

        workdir = str(Path("/workdir/swap") / self.repo_name)
        return self.patch_analyzer.apply_patches_to_container(patches, self.docker_executor, workdir)

    def _find_test_dirs(self, repo_name: str, use_docker: bool = True) -> List[str]:
        """Recursively detect test directories in repository (in container or locally), return list of existing directories (if not detected return ['tests'])"""
        candidates = ["tests", "test", "Tests", "TESTS", "unit_tests", "TEST"]
        ignore_dirs = [".venv", "build"]

        # First search in root directory
        root_find_cmd = (
            "find . -maxdepth 1 -type d \\( " +
            " -o ".join([f"-name '{d}'" for d in candidates]) +
            " \\) -print"
        )

        if use_docker:
            workdir = f"/workdir/swap/{repo_name}"
            exit_code, output = self.docker_executor.execute(root_find_cmd, workdir, tty=False, timeout=30)
        else:
            workdir = str(self.base_path / "swap" / repo_name)
            exit_code, output = self.local_executor.execute(root_find_cmd, workdir, tty=False, timeout=30)

        if output is None:
            output = ""

        found = [line.strip().lstrip('./') for line in output.splitlines() if line.strip()]

        # If test directories found in root directory, return directly
        if found:
            self.logger.info(f"Test directories detected in root directory: {found}")
            return found

        # Root directory not found, continue recursive search
        prune_expr = " -o ".join([f"-path './{d}' -prune" for d in ignore_dirs])
        prune_expr = f"\\( {prune_expr} \\) -o "

        find_cmd = (
            f"find . {prune_expr}-type d \\( " +
            " -o ".join([f"-name '{d}'" for d in candidates]) +
            " \\) -print"
        )

        if use_docker:
            exit_code, output = self.docker_executor.execute(find_cmd, workdir, tty=False, timeout=30)
        else:
            exit_code, output = self.local_executor.execute(find_cmd, workdir, tty=False, timeout=30)

        if output is None:
            output = ""

        found = [line.strip().lstrip('./') for line in output.splitlines() if line.strip()]

        if not found:
            self.logger.info(f"Common test directories not detected ({candidates}), falling back to default 'tests'")
            return ["tests"]

        self.logger.info(f"Test directories detected recursively: {found}")
        return found

    def _install_xdist(self, repo_name) -> None:
        """Install pytest-xdist in container"""
        self.logger.info("Installing pytest-xdist in container")
        cmd = "pip install pytest-xdist"
        exit_code, output = self.docker_executor.execute(cmd, f"/workdir/swap/{repo_name}", tty=False, timeout=300)
        if exit_code != 0:
            self.logger.error(f"Failed to install pytest-xdist: {output}")
            raise ContainerOperationError(f"Failed to install pytest-xdist: {output}", container_id=self.container.id if self.container else None)
        self.logger.info("Successfully installed pytest-xdist in container")

    def _setup_conan_cmake_env(self, repo_name: str) -> None:
        """Prepare the cmake environment expected by conan's test/conftest.py.

        Conan's conftest.py has hardcoded Linux paths per cmake version. This:
        1. Symlinks the system cmake binary to all configured paths so any-version tests pass.
        2. Installs cmake 3.15.7 (the default version in conftest.py) if not already present,
           so version-checking tests pass. Skipped entirely if the sentinel file exists.
        """
        sentinel = "/usr/share/cmake-3.15.7/.conan_setup_done"
        cmake_315_bin = "/usr/share/cmake-3.15.7/bin"
        script = (
            f"if [ -f {sentinel} ]; then exit 0; fi && "
            # Capture the current system cmake (before potentially installing 3.15)
            "cmake_bin=$(which cmake 2>/dev/null) && "
            "[ -n \"$cmake_bin\" ] && "
            # Symlink system cmake to all configured paths except the 3.15 path
            "python3 -c \""
            "import re; "
            "f=open('test/conftest.py'); c=f.read(); f.close(); "
            "paths=re.findall(r\\\"'Linux': ['\\\\\\\"]([^'\\\\\\\"]+)['\\\\\\\"]\\\", c); "
            "print('\\\\n'.join(paths))"
            f"\" | while read path; do "
            f"[ \"$path\" != \"$(dirname $cmake_bin)\" ] && [ \"$path\" != \"{cmake_315_bin}\" ] && mkdir -p \"$path\" && ln -sf \"$cmake_bin\" \"$path/cmake\"; "
            "done && "
            # Install cmake 3.15.7 only if system cmake is not already 3.15.x
            "cmake_ver=$(cmake --version 2>/dev/null | head -1) && "
            "if ! echo \"$cmake_ver\" | grep -q 'cmake version 3\\.15'; then "
            "  wget -q https://cmake.org/files/v3.15/cmake-3.15.7-Linux-x86_64.sh -O /tmp/cmake-3.15.sh && "
            "  chmod +x /tmp/cmake-3.15.sh && "
            "  /tmp/cmake-3.15.sh --prefix=/usr/local --skip-license && "
            f"  mkdir -p {cmake_315_bin} && "
            f"  ln -sf /usr/local/bin/cmake {cmake_315_bin}/cmake; "
            "else "
            f"  mkdir -p {cmake_315_bin} && ln -sf \"$cmake_bin\" \"{cmake_315_bin}/cmake\"; "
            "fi && "
            f"touch {sentinel}"
        )
        workdir = f"/workdir/swap/{repo_name}"
        exit_code, output = self.docker_executor.execute(script, workdir, tty=False, timeout=120)
        if exit_code != 0:
            self.logger.warning(f"conan cmake env setup failed (non-fatal): {output}")
        else:
            self.logger.info("conan cmake env set up successfully")

    # Repos that should NOT receive the generic `pip install -e .` step.
    _NO_EDITABLE_INSTALL_REPOS: set[str] = {
        "scikit-learn/scikit-learn",
        "jupyterlab/jupyter-ai",
        "reflex-dev/reflex",
    }

    def _setup_editable_install(self, repo_name: str) -> None:
        """Generic `pip install -e .` for repos that need an editable install."""
        self.logger.info(f"Running pip install -e . for {repo_name}")
        exit_code, output = self.docker_executor.execute(
            "pip install -e .", f"/workdir/swap/{repo_name}", tty=False, timeout=600
        )
        if exit_code != 0:
            self.logger.warning(f"pip install -e . for {repo_name} failed (non-fatal): {output}")
        else:
            self.logger.info(f"pip install -e . for {repo_name} succeeded")

    def _setup_pybamm_env(self, repo_name: str) -> None:
        """Prepare PyBaMM test environment by installing package with all extras."""
        self.logger.info("Setting up PyBaMM env with editable install and [all] extras")
        exit_code, output = self.docker_executor.execute(
            "pip install -e '.[all]'", f"/workdir/swap/{repo_name}", tty=False, timeout=300
        )
        if exit_code != 0:
            self.logger.error(f"PyBaMM env setup failed: {output}")
            raise ContainerOperationError(
                f"PyBaMM env setup failed: {output}",
                container_id=self.container.id if self.container else None,
            )
        self.logger.info("PyBaMM env set up successfully")

    def _setup_jupyter_ai_env(self, repo_name: str) -> None:
        """Prepare jupyter-ai test environment by upgrading Node.js and installing packages."""
        self.logger.info("Setting up jupyter-ai env with Node.js upgrade and editable installs")
        cmd = (
            "npm install -g n && n 14 && hash -r && "
            'pip install -e "packages/jupyter-ai-magics[test]" -e "packages/jupyter-ai-test[test]" -e "packages/jupyter-ai[test]"'
        )
        exit_code, output = self.docker_executor.execute(cmd, f"/workdir/swap/{repo_name}", tty=False, timeout=600)
        if exit_code != 0:
            self.logger.error(f"jupyter-ai env setup failed: {output}")
            raise ContainerOperationError(
                f"jupyter-ai env setup failed: {output}",
                container_id=self.container.id if self.container else None,
            )
        self.logger.info("jupyter-ai env set up successfully")

    def setup_repo_env(self, repo_name: str, instance_id: Optional[str] = None) -> None:
        """Run repo-specific environment setup (cmake, editable installs, etc.).

        Safe to call multiple times — editable installs (pip install -e) are
        idempotent, and the conan cmake setup is sentinel-guarded since it
        writes outside the repo dir and survives git checkout.

        Called once before the agent runs and once before tests run, so that
        git checkout in between doesn't break the environment.
        """
        # Repo-specific custom setup steps (run in addition to the generic install).
        if repo_name == "conan":
            self._setup_conan_cmake_env(repo_name)
        if repo_name == "jupyter-ai":
            self._setup_jupyter_ai_env(repo_name)

        # PyBaMM needs the [all] extras, so it has its own install path.
        if repo_name.lower() == "pybamm" and instance_id != "pybamm-team__PyBaMM-4394":
            self._setup_pybamm_env(repo_name)
            return

        # Generic `pip install -e .` for everything else, except excluded repos.
        if self.repo not in self._NO_EDITABLE_INSTALL_REPOS:
            self._setup_editable_install(repo_name)

    def run_tests_in_container(
        self,
        repo_name: str,
        test_files: Optional[List[Dict[str, CodeChange] | str]] = None,
        expected_statuses: Optional[List[TestStatus]] = None,
        use_xdist: bool = True,
        log_file: Optional[str] = None,
        instance_id: Optional[str] = None,
    ) -> tuple[Set[str], str]:
        """Run tests in container and return passed test files and logs"""
        pytest_args = []

        if test_files is None:
            dirs = self._find_test_dirs(repo_name, use_docker=True)
            for d in dirs:
                pytest_args.append(f"{d}/")
                expected_tests = pytest_args
        else:
            if isinstance(test_files[0], Dict):
                for test_file in test_files:
                    for file_name, changes in test_file.items():
                        for change in changes:
                            if change.change_type == 'deleted':
                                continue
                            elif change.code_type == 'function':
                                pytest_args.append(f"{file_name}::{change.name}")
                            elif change.code_type == 'method':
                                class_name, method_name = change.name.split('.', 1)
                                pytest_args.append(f"{file_name}::{class_name}::{method_name}")
                expected_tests = pytest_args
            else:
                tests_files_union = {t.split("::")[0] for t in test_files}
                pytest_args.extend(list(tests_files_union))
                expected_tests = test_files

        # --- Build the base pytest command (no xdist flags) ----------------
        timeout_val = _get_pytest_timeout(repo_name)
        base_cmd = (
            f"python3 -m pytest -q -rA --tb=no -p no:pretty"
            f" --timeout={timeout_val} --continue-on-collection-errors"
            f" --timeout-method=signal"
        )
        if instance_id == "tox-dev__tox-3534":
            base_cmd += " --run-integration"

        # --- Determine xdist configuration ---------------------------------
        # base_cmd has NO xdist-related flags. Each invocation below decides
        # whether to add `-n N` or `-p no:xdist` to override any project-level
        # `addopts = -n auto`.
        xdist_enabled_repo = _should_use_xdist(repo_name)
        use_xdist_effective = use_xdist and xdist_enabled_repo
        xdist_workers = 0
        if use_xdist_effective:
            self._install_xdist(repo_name)
            xdist_workers = get_cpu_limit(self.repo)

        if log_file:
            self.docker_executor.execute(f"bash -c '> /logs/{log_file}'", "/")

        # --- Split test args into execution groups -------------------------
        isolated_files = _REPO_ISOLATED_TEST_FILES.get(repo_name, set())
        xdist_overrides = _INSTANCE_FILE_XDIST_OVERRIDES.get(instance_id, {}) if instance_id else {}

        # Only split when we have string-based test node IDs (the evaluation path)
        # A file may be in isolated_files, xdist_overrides, both, or neither.
        # Files in either set always get their own pytest invocation.
        # The xdist override (if any) sets the worker count for that invocation.
        if test_files is not None and test_files and isinstance(test_files[0], str):
            normal_args = []
            # file_path -> {"n": Optional[int], "args": list[str]}
            #   n is None  -> isolated only (disable xdist)
            #   n is int   -> override (with explicit -n N), implies own invocation
            per_file_groups: dict[str, dict] = {}

            for arg in pytest_args:
                file_path = arg.split("::")[0]
                is_isolated = file_path in isolated_files
                override_n = xdist_overrides.get(file_path)
                if is_isolated or override_n is not None:
                    if file_path not in per_file_groups:
                        per_file_groups[file_path] = {"n": override_n, "args": []}
                    per_file_groups[file_path]["args"].append(arg)
                else:
                    normal_args.append(arg)

            has_splits = bool(per_file_groups)
        else:
            normal_args = pytest_args
            per_file_groups = {}
            has_splits = False

        all_matched: Set[str] = set()
        all_output: list[str] = []

        def _with_xdist(cmd: str, n: Optional[int]) -> str:
            """Append the right xdist flag(s) to a base pytest command.

            n is None  -> disable xdist (overrides project-level `-n auto`),
                          but only if the repo's project config might enable it.
            n is int   -> explicitly run with `-n {n}` workers.
            """
            if n is None:
                if xdist_enabled_repo:
                    return f"{cmd} -p no:xdist"
                return cmd
            return f"{cmd} -n {n}"

        # --- Run main group ------------------------------------------------
        if normal_args:
            n_main = xdist_workers if (use_xdist_effective and xdist_workers > 1) else None
            cmd_main = _with_xdist(base_cmd, n_main)
            matched, output = self._run_pytest_group(
                repo_name, normal_args, cmd_main, expected_tests, expected_statuses, log_file
            )
            all_matched.update(matched)
            all_output.append(output)

        # --- Run per-file groups (isolated and/or xdist-override) ----------
        if has_splits:
            for file_path, group in per_file_groups.items():
                n_workers = group["n"]
                args = group["args"]
                if n_workers is not None:
                    self.logger.info(f"Running per-file group with -n {n_workers}: {file_path}")
                else:
                    self.logger.info(f"Running isolated test file: {file_path}")
                cmd = _with_xdist(base_cmd, n_workers)
                matched, output = self._run_pytest_group(
                    repo_name, args, cmd, expected_tests, expected_statuses, log_file
                )
                all_matched.update(matched)
                all_output.append(output)

        combined_output = "\n".join(all_output)
        return all_matched, combined_output

    def _run_pytest_group(
        self,
        repo_name: str,
        pytest_args: List[str],
        cmd_template: str,
        expected_tests: List[str],
        expected_statuses: Optional[List[TestStatus]],
        log_file: Optional[str],
    ) -> tuple[Set[str], str]:
        """Run a single pytest invocation for a group of test args.

        Handles command-length batching internally if needed.
        """
        estimated_length = len(cmd_template) + sum(len(a) + 1 for a in pytest_args)

        if estimated_length > 100000:
            self.logger.info(f"Too many test parameters ({len(pytest_args)}), using batch execution")
            return self._run_tests_in_batches(repo_name, pytest_args, cmd_template, expected_tests, expected_statuses, log_file)

        cmd = f"{cmd_template} {' '.join(pytest_args)}"
        if log_file:
            cmd = f'bash -c "set -o pipefail; {cmd} 2>&1 | tee -a /logs/{log_file}"'

        exit_code, output = self.docker_executor.execute(
            cmd, f"/workdir/swap/{repo_name}", stream=True, tty=False, timeout=3600
        )
        matched = self.parse_pytest_output(output, expected_tests, expected_statuses)
        return matched, output

    def _run_tests_in_batches(
        self,
        repo_name: str,
        pytest_args: List[str],
        base_cmd_template: str,
        expected_tests: List[str],
        expected_statuses: Optional[List[TestStatus]] = None,
        log_file: Optional[str] = None,
    ) -> tuple[Set[str], str]:
        """When command is too long, execute tests in batches"""
        self.logger.info("Executing tests in batches to avoid command length limit")

        batch_size = 250
        all_output = []
        all_matched = set()

        for i in range(0, len(pytest_args), batch_size):
            batch = pytest_args[i:i + batch_size]
            self.logger.info(f"Executing batch {i//batch_size + 1} of tests ({len(batch)})")

            cmd = f"{base_cmd_template} {' '.join(batch)}"
            if log_file:
                cmd = f'bash -c "set -o pipefail; {cmd} 2>&1 | tee -a /logs/{log_file}"'
            exit_code, output = self.docker_executor.execute(
                cmd, f"/workdir/swap/{repo_name}", stream=True, tty=False, timeout=3600
            )

            all_output.append(output)
            batch_matched = self.parse_pytest_output(output, expected_tests, expected_statuses)
            all_matched.update(batch_matched)

        combined_output = '\n'.join(all_output)
        return all_matched, combined_output

    def parse_pytest_output(self, logs: str, test_cases: List[str], expected_statuses: List[TestStatus]) -> Set[str]:
        """Parse pytest output, extract files with completely passed tests (no failures or errors)"""

        parser = PytestResultParser(logs)

        is_directory_test = any(arg.endswith('/') for arg in test_cases)

        if is_directory_test:
            matched = parser.filter_tests_by_status(expected_statuses)
            self.logger.info(f"Directory test matched {len(matched)} tests with expected status")
            return matched
        else:
            results = parser.query_tests(test_cases)
            self.logger.info("Query results:")
            for test, status in results.items():
                self.logger.info(f"  {test}: {status.value}")
            return set(test for test, status in results.items() if status in expected_statuses)
