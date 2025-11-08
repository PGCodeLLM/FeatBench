import logging
from datetime import datetime
from pathlib import Path
import os
import shlex
from typing import Optional, List
from docker_agent.core.types import Container, AgentTaskType
from docker_agent.config.config import (
    SETUP_FILES_NAME, RECOMMENDED_PYTHON_VERSION, DEFAULT_PYTHON_VERSION,
    PROMPTS, TRAE_TIMESTAMP_FORMAT
)
from docker_agent.utils.command_executor import LocalCommandExecutor, DockerCommandExecutor
from docker_agent.core.exceptions import ConfigurationError, AgentExecutionError

class AgentExecutor:
    """Agent executor class"""

    def __init__(self, base_path: Path, use_docker: bool = True):
        self.bash_path = base_path
        self.use_docker = use_docker
        self.logger = logging.getLogger(__name__)
        self.executor = None  # Will be initialized when needed

    def _get_executor(self, container: Optional[Container] = None):
        """Get appropriate command executor"""
        if self.use_docker:
            if container is None:
                raise ConfigurationError("Container parameter must be provided when using Docker mode")
            return DockerCommandExecutor(container)
        else:
            return LocalCommandExecutor()

    def _generate_file_list_prompt(self, repo_name: str) -> str:
        """Generate prompt for listing environment configuration files"""
        template = PROMPTS.file_list.template

        return template.format(
            repo_name=repo_name,
            setup_files=SETUP_FILES_NAME,
            version_file=RECOMMENDED_PYTHON_VERSION,
            default_version=DEFAULT_PYTHON_VERSION
        )

    def _generate_env_setup_prompt(self, repo_name: str, test_files: List[str], created_time: Optional[str] = None) -> str:
        """Generate prompt for configuring environment"""
        template = PROMPTS.env_setup.template

        # Add created_time variable passing, convert to YYYY-MM-DD format
        formatted_created_time = ""
        if created_time:
            try:
                dt = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
                formatted_created_time = dt.strftime("%Y-%m-%d")
            except Exception:
                formatted_created_time = created_time

        return template.format(
            repo_name=repo_name,
            setup_files=SETUP_FILES_NAME,
            version_file=RECOMMENDED_PYTHON_VERSION,
            created_time=formatted_created_time,
            test_files=' '.join(test_files) if test_files else "None"
        )

    def _build_trae_command(self, prompt: str, repo_name: str, trajectory_file: str) -> str:
        """Build trae-cli command"""
        escaped_prompt = shlex.quote(prompt)
        if self.use_docker:
            working_dir = Path("/workdir/swap") / repo_name
            config_file = "/workdir/swap/trae-agent/trae_config.yaml"
        else:
            working_dir = self.bash_path / "swap" / repo_name
            config_file = str(self.bash_path / "swap" / "trae-agent" / "trae_config.yaml")

        return (f".venv/bin/python3.12 -m trae_agent.cli run "
                f"{escaped_prompt} "
                f"--config-file {config_file} "
                f"--working-dir {working_dir} "
                f"--trajectory-file {trajectory_file}")

    def _execute_trae_command(self, command: str, 
                             container: Optional[Container] = None) -> tuple[int, str]:
        """Execute trae command and return exit code and output"""
        executor = self._get_executor(container)
        
        if self.use_docker:
            workdir = "/workdir/trae-agent"
        else:
            workdir = str(self.bash_path / "swap" / "trae-agent")
        
        self.logger.info(f"Executing trae-agent command: {'in container' if self.use_docker else 'locally'}")
        
        try:
            exit_code, output = executor.execute(command, workdir, stream=True)
            return exit_code, output
        except Exception as e:
            self.logger.error(f"Command execution failed: {str(e)}")
            raise AgentExecutionError(f"Command execution failed: {str(e)}")

    def _generate_trajectory_filename(self, repo_name: str, repo_id: str, task_type: AgentTaskType) -> str:
        """Generate trajectory filename"""
        timestamp = datetime.now().strftime(TRAE_TIMESTAMP_FORMAT)

        if self.use_docker:
            trajectory_path = Path("/workdir/swap/trajectory") / repo_name
        else:
            trajectory_path = self.bash_path / "swap" / "trajectory" / repo_name
            os.makedirs(trajectory_path, exist_ok=True)

        return trajectory_path / f"{repo_id}_{timestamp}_{task_type.value}_trajectory.json"

    def call_trae_agent(self, repo_name: str, repo_id: str, 
                       task_type: AgentTaskType, test_files: Optional[List[str]] = None, created_time: str = None,
                       container: Optional[Container] = None) -> str:
        """Main coordination function for executing trae-agent command in container or locally"""
        
        if self.use_docker and container is None:
            raise ConfigurationError("Container parameter must be provided when using Docker mode")
        
        if task_type == AgentTaskType.FILE_LIST:
            prompt = self._generate_file_list_prompt(repo_name)
        elif task_type == AgentTaskType.ENV_SETUP:
            prompt = self._generate_env_setup_prompt(repo_name, test_files, created_time)
        else:
            raise ConfigurationError(f"Unsupported task type: {task_type}")
        
        trajectory_file = self._generate_trajectory_filename(repo_name, repo_id, task_type)
        command = self._build_trae_command(prompt, repo_name, trajectory_file)
        exit_code, output_str = self._execute_trae_command(command, container)
        self.logger.info(f"trae-agent execution completed, return code: {exit_code}")
        
        if exit_code is not None and exit_code != 0:
            raise AgentExecutionError(f"trae-agent command failed, return code: {exit_code}\nOutput: {output_str}")
        
        self.logger.info("trae-agent execution successful")
        return output_str