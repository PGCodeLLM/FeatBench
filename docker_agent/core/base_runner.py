"""Base runner class - Common functionality for DockerAgentRunner and AgentEvaluator"""

import logging
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

from docker_agent.config.config import LOG_FILE, LOGGING_LEVEL, LOGGING_FORMAT, ANALYSIS_FILE, AGENTS
from docker_agent.container.docker_env_manager import DockerEnvironmentManager
from docker_agent.orchestration.signal_handler import SignalHandler
from docker_agent.orchestration.cleanup_manager import CleanupManager
from docker_agent.core.types import Spec
from datetime import datetime


class BaseRunner:
    """Base runner class with common functionality"""

    def __init__(self):
        """
        Initialize base runner

        Args:
            config_path: (Ignored) Deprecated parameter
        """
        self.base_path = Path(__file__).parent.parent  # Go up to the root directory
        self.docker_manager = DockerEnvironmentManager()

        self.active_containers = []
        self.cleanup_in_progress = False

        self._setup_logging()

        self.signal_handler = SignalHandler(self._on_signal)
        self.signal_handler.register()

        self.logger = logging.getLogger(__name__)
    
    def _make_log_file_path(self) -> Path:
        """Generate log file path with timestamp and model name"""
        log_file_path = Path(LOG_FILE)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        model_name = AGENTS[0].model.replace('/', '_').replace('\\', '_').replace(':', '_')
        new_filename = f"{log_file_path.stem}_{timestamp}_{model_name}{log_file_path.suffix}"
        return log_file_path.parent / new_filename

    def _setup_logging(self):
        """Configure logging"""
        log_file = self._make_log_file_path()
        log_dir = log_file.parent
        log_dir.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, LOGGING_LEVEL),
            format=LOGGING_FORMAT,
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )

    def _on_signal(self):
        """
        Handle signal - cleanup containers
        This method can be overridden by subclasses if needed
        """
        if self.cleanup_in_progress:
            return

        self.cleanup_in_progress = True
        cleanup_manager = CleanupManager(self.docker_manager)
        cleanup_manager.cleanup_all(self.active_containers)
        self.cleanup_in_progress = False

    def _load_specs(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load and group specs by repository

        Returns:
            Dictionary mapping repository names to list of specs
        """
        with ANALYSIS_FILE.open("r", encoding="utf-8") as f:
            specs = json.load(f)

        specs_by_repo = defaultdict(list)
        for spec in specs:
            repo = spec["repo"]
            specs_by_repo[repo].append(spec)

        return specs_by_repo

    def _dict_to_spec(self, spec_dict: Dict[str, Any], repo_name: Optional[str] = None) -> Spec:
        """
        Convert spec dictionary to Spec object

        Args:
            spec_dict: Dictionary containing spec data
            repo_name: Repository name (extracted from repo if not provided)

        Returns:
            Spec object
        """
        if repo_name is None:
            repo_name = spec_dict["repo"].split('/')[-1]

        return Spec(
            instance_id=spec_dict["instance_id"],
            repo=spec_dict["repo"],
            repo_name=repo_name,
            base_commit=spec_dict["base_commit"],
            number=str(spec_dict["number"]),
            problem_statement=spec_dict.get("problem_statement"),
            patch=spec_dict.get("patch"),
            test_patch=spec_dict.get("test_patch"),
            test_files=spec_dict.get("test_files"),
            created_at=spec_dict.get("created_at"),
            PASS_TO_PASS=spec_dict.get("PASS_TO_PASS"),
            FAIL_TO_PASS=spec_dict.get("FAIL_TO_PASS"),
            processed=spec_dict.get("processed", False)
        )