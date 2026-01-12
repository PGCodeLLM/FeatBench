"""
Agent Evaluator - Reuses existing modules

This module provides agent evaluation functionality by reusing existing
docker_agent modules for better maintainability and consistency.
"""

from typing import List, Optional

from docker_agent.core.base_runner import BaseRunner
from docker_agent.container.container_operator import ContainerOperator
from docker_agent.agents.manager import AgentManager
from docker_agent.parsing.patch_analyzer import PatchAnalyzer
from docker_agent.evaluation.results import EvaluationResultManager
from docker_agent.config.config import AGENTS, EVALUATION_RESULTS_FILE, MAX_SPECS_PER_REPO


class AgentEvaluator(BaseRunner):
    """Agent evaluator"""

    def __init__(self):
        """Initialize Agent Evaluator"""
        super().__init__()

        self.result_manager = EvaluationResultManager(self.base_path)
        self.patch_analyzer = PatchAnalyzer()

    def evaluate(self, agent_names: Optional[List[str]] = None):
        """
        Main evaluation method

        Args:
            agent_names: List of agent names to evaluate
        """
        agents_to_evaluate = [a for a in AGENTS if agent_names is None or a.name in agent_names]
        if not agents_to_evaluate:
            self.logger.error("No agents to evaluate")
            return

        specs_by_repo = self._load_specs()
        total_evaluations = sum(len(repo_specs[:MAX_SPECS_PER_REPO]) for repo_specs in specs_by_repo.values())
        self.logger.info(f"Total evaluations to run: {total_evaluations}")

        all_results = []
        for _, repo_specs in specs_by_repo.items():
            for spec_dict in repo_specs[:MAX_SPECS_PER_REPO]:
                spec = self._dict_to_spec(spec_dict)
                
                container = None
                try:
                    container = self.docker_manager.create_container(spec)
                    operator = ContainerOperator(spec.repo, container)
                    agent_managers = [AgentManager(container, agent_config) for agent_config in agents_to_evaluate]

                    for agent_manager in agent_managers:
                        self.logger.info(f"Starting evaluation of {agent_manager.agent_config.name} on {spec.instance_id}")

                        result = agent_manager.evaluate(spec, operator)
                        all_results.append(result)

                    self.result_manager.save_evaluation_results(all_results, EVALUATION_RESULTS_FILE)

                except Exception as e:
                    self.logger.error(f"Error processing {spec.instance_id}: {e}")
                finally:
                    if container and not self.cleanup_in_progress:
                        self.docker_manager.cleanup_container(container, force_remove=True)
                        self.active_containers.append(container)

        self.logger.info("Evaluation completed")