"""File management for setup files and test logs"""

import json
import logging
from pathlib import Path
from docker_agent.execution.agent_executor import AgentExecutor, AgentTaskType
from docker_agent.container.container_operator import ContainerOperator
from docker_agent.core.types import Spec
from docker_agent.utils.install_trae_agent import TraeAgentInstaller


class FileManager:
    """Manages setup files, transfers, and test logs"""

    def __init__(self, base_path: Path, docker_executor: AgentExecutor, local_executor: AgentExecutor):
        self.base_path = base_path
        self.docker_executor = docker_executor
        self.local_executor = local_executor
        self.logger = logging.getLogger(__name__)

    def prepare_setup_files(self, spec: Spec):
        """Prepare setup files for a repository"""
        self._init_directory()
        self._ensure_trae_agent_installed()

        setup_files_json = self.base_path / "swap" / "setup_files_list.json"
        operator = ContainerOperator(repo=spec.repo)

        if setup_files_json.exists():
            try:
                with setup_files_json.open("r", encoding="utf-8") as f:
                    existing_data = json.load(f)

                if spec.repo.replace("/", "_") in existing_data:
                    operator.checkout_commit(spec.base_commit, use_docker=False)
                    self.logger.info(f"Configuration file list for repository {spec.repo} already exists, skipping first stage")
                    return
            except Exception as e:
                self.logger.warning(f"Error reading existing configuration file list: {e}")

        operator.repo_clone(use_docker=False)
        operator.checkout_commit(spec.base_commit, use_docker=False)

        self.logger.info(f"First stage: List environment configuration files for repository {spec.repo}")
        self.local_executor.call_trae_agent(
            spec.repo_name,
            spec.instance_id, AgentTaskType.FILE_LIST
        )
        self.transfer_and_merge(spec.repo, spec.repo_name)

    def transfer_and_merge(self, repo: str, repo_name: str):
        """Transfer generated JSON files to swap directory and merge by repository"""
        try:
            base_dir = self.base_path / "swap" / repo_name
            swap_dir = self.base_path / "swap"

            files_to_process = [
                "recommended_python_version.json",
                "setup_files_list.json"
            ]

            for filename in files_to_process:
                if filename == "recommended_python_version.json":
                    source_file = base_dir / filename
                    target_file = swap_dir / filename
                    if source_file.exists():
                        with source_file.open("r", encoding="utf-8") as f:
                            new_data = f.read().strip()
                    else:
                        self.logger.warning(f"Source file does not exist: {source_file}")
                        continue

                    merged_data = {}
                    if target_file.exists():
                        with target_file.open("r", encoding="utf-8") as f:
                            merged_data = json.load(f)
                    merged_data[repo.replace("/", "_")] = new_data
                    with target_file.open("w", encoding="utf-8") as f:
                        json.dump(merged_data, f, indent=2, ensure_ascii=False)
                    self.logger.info(f"Transferred and merged {filename} to {target_file}")
                    source_file.unlink()
                else:
                    source_file = base_dir / filename
                    target_file = swap_dir / filename
                    if source_file.exists():
                        with source_file.open("r", encoding="utf-8") as f:
                            new_data = json.load(f)
                        merged_data = {}
                        if target_file.exists():
                            with target_file.open("r", encoding="utf-8") as f:
                                merged_data = json.load(f)
                        merged_data[repo.replace("/", "_")] = new_data
                        with target_file.open("w", encoding="utf-8") as f:
                            json.dump(merged_data, f, indent=2, ensure_ascii=False)
                        self.logger.info(f"Transferred and merged {filename} to {target_file}")
                        source_file.unlink()
                    else:
                        self.logger.warning(f"Source file does not exist: {source_file}")

        except Exception as e:
            self.logger.error(f"Error transferring and merging setup files: {str(e)}")

    def restore_setup_files(self, repo: str, repo_name: str):
        """Restore configuration files from swap directory to corresponding repository directory"""
        try:
            base_dir = self.base_path / "swap" / repo_name
            swap_dir = self.base_path / "swap"

            base_dir.mkdir(parents=True, exist_ok=True)

            files_to_restore = [
                "recommended_python_version.json",
                "setup_files_list.json"
            ]

            for filename in files_to_restore:
                source_file = swap_dir / filename
                target_file = base_dir / filename

                if source_file.exists():
                    with source_file.open("r", encoding="utf-8") as f:
                        merged_data = json.load(f)
                    if repo.replace("/", "_") in merged_data:
                        repo_data = merged_data[repo.replace("/", "_")]
                        with target_file.open("w", encoding="utf-8") as f:
                            json.dump(repo_data, f, indent=2, ensure_ascii=False)
                        self.logger.info(f"Restored {filename} to {target_file}")
                    else:
                        self.logger.warning(f"Data for repository {repo} not found in {filename}")
                else:
                    self.logger.warning(f"Merged file does not exist: {source_file}")

        except Exception as e:
            self.logger.error(f"Error restoring setup files: {str(e)}")

    def save_test_logs(self, repo_name: str, pre_logs: str, post_logs: str):
        """Save test logs to logs/test_logs.json (simplified version)"""
        logs_file = self.base_path / "logs" / "test_logs.json"
        logs_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            existing_logs = {}
            if logs_file.exists():
                with logs_file.open("r", encoding="utf-8") as f:
                    existing_logs = json.load(f)

            existing_logs[repo_name] = {
                "pre_logs": pre_logs,
                "post_logs": post_logs
            }

            with logs_file.open("w", encoding="utf-8") as f:
                json.dump(existing_logs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to save test logs: {e}")
        
    def _init_directory(self):
        """Initialize directory if it does not exist"""
        swap_dir = self.base_path / "swap"
        swap_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_trae_agent_installed(self):
        """Ensure trae-agent is installed in swap directory, skip if directory is not empty"""
        trae_agent_dir = self.base_path / "swap" / "trae-agent"
        installer = TraeAgentInstaller()
        installer.install(trae_agent_dir)
