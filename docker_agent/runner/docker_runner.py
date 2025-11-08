"""Docker Agent runner - main entry point"""

import json
from typing import Dict, List, Any

from docker_agent.core.base_runner import BaseRunner
from docker_agent.execution.file_manager import FileManager
from docker_agent.execution.spec_processor import SpecProcessor
from docker_agent.execution.agent_executor import AgentExecutor, AgentTaskType
from docker_agent.core.types import Spec, Container
from docker_agent.config.config import ANALYSIS_FILE, MAX_SPECS_PER_REPO


class DockerAgentRunner(BaseRunner):
    """Docker Agent runner class"""

    def __init__(self, test_only: bool = False):
        """
        Initialize Docker Agent Runner

        Args:
            test_only: If True, only process test specs
        """
        super().__init__()
        self.test_only = test_only

    def _save_specs(self, spec: Spec, specs_by_repo: Dict[str, List[Dict[str, Any]]]):
        """Save specs to file, updating the specific spec"""
        for repo_specs in specs_by_repo.values():
            for spec_dict in repo_specs:
                if spec_dict["instance_id"] == spec.instance_id:
                    spec_dict["processed"] = spec.processed
                    spec_dict["PASS_TO_PASS"] = spec.PASS_TO_PASS
                    spec_dict["FAIL_TO_PASS"] = spec.FAIL_TO_PASS
                    break

        updated_specs = []
        for all_repo_specs in specs_by_repo.values():
            updated_specs.extend(all_repo_specs)

        with ANALYSIS_FILE.open("w", encoding="utf-8") as f:
            json.dump(updated_specs, f, indent=2, ensure_ascii=False)

    def _setup_repo_environment(self, container: Container, spec: Spec):
        """Set up repository environment"""
        self.logger.info(f"Second stage: Configure environment for repository {spec.repo}")

        docker_executor = AgentExecutor(self.base_path, use_docker=True)
        local_executor = AgentExecutor(self.base_path, use_docker=False)
        file_manager = FileManager(self.base_path, docker_executor, local_executor)

        file_manager.restore_setup_files(spec.repo, spec.repo_name)

        docker_executor.call_trae_agent(
            spec.repo_name,
            spec.instance_id, AgentTaskType.ENV_SETUP,
            [file for file in spec.test_files if file.endswith(".py")],
            spec.created_at,
            container
        )

    def run(self):
        """Main run method"""
        self.signal_handler.register()

        specs_by_repo = self._load_specs()

        docker_executor = AgentExecutor(self.base_path, use_docker=True)
        local_executor = AgentExecutor(self.base_path, use_docker=False)
        file_manager = FileManager(self.base_path, docker_executor, local_executor)

        spec_processor = SpecProcessor(self.base_path)

        for repo, repo_specs in list(specs_by_repo.items()):
            for spec_dict in repo_specs[:MAX_SPECS_PER_REPO]:
                if not self.test_only:
                    if spec_dict.get("processed", False):
                        self.logger.info(f"Skipping processed spec: {spec_dict['instance_id']}")
                        continue
                else:
                    if spec_dict.get("FAIL_TO_PASS", None) is not None and spec_dict.get("PASS_TO_PASS", None) is not None:
                        continue
                spec = self._dict_to_spec(spec_dict)

                try:
                    if not self.test_only:
                        file_manager.prepare_setup_files(spec)
                        container = self.docker_manager.create_container(spec)
                        try:
                            self._setup_repo_environment(container, spec)

                            try:
                                self.docker_manager.cache_manager.save_container_as_image(container)
                                self.logger.info(f"Saved configured image for repository {repo.lower()}#{spec.number}")
                            except Exception as save_err:
                                self.logger.error(f"Failed to save image for repository {repo.lower()}#{spec.number}: {str(save_err)}")

                        except Exception as setup_err:
                            self.logger.error(f"Error configuring environment for repository {repo.lower()}#{spec.number}: {str(setup_err)}")
                            continue
                    else:
                        container = self.docker_manager.create_container(spec)

                    try:
                        spec_processor.process(container, spec)

                        self._save_specs(spec, specs_by_repo)
                        self.logger.info(f"Saved results for {spec.instance_id}")

                    except Exception as inst_err:
                        self.logger.error(f"Error processing {spec.instance_id}: {str(inst_err)}")

                except Exception as repo_err:
                    self.logger.error(f"Error processing repository {repo}: {str(repo_err)}")
                finally:
                    if container is not None and not self.cleanup_in_progress:
                        self.docker_manager.cleanup_container(container, force_remove=True)
                        self.active_containers.append(container)

        self.logger.info("All processing completed")
