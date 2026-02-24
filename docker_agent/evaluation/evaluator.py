"""
Agent Evaluator - Reuses existing modules

This module provides agent evaluation functionality by reusing existing
docker_agent modules for better maintainability and consistency.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
import random

from docker_agent.core.base_runner import BaseRunner
from docker_agent.container.container_operator import ContainerOperator
from docker_agent.agents.manager import AgentManager
from docker_agent.parsing.patch_analyzer import PatchAnalyzer
from docker_agent.evaluation.results import EvaluationResultManager
from docker_agent.config.config import AGENTS, EVALUATION_RESULTS_FILE, MAX_SPECS_PER_REPO, MAX_EVAL_WORKERS, LOG_FILE
from docker_agent.core.types import Spec


class AgentEvaluator(BaseRunner):
    """Agent evaluator"""

    def __init__(self):
        """Initialize Agent Evaluator"""
        super().__init__()

        self.result_manager = EvaluationResultManager(self.base_path)
        self.patch_analyzer = PatchAnalyzer()
        self.shared_data_lock = threading.Lock()

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

        # Load cached results so we can resume without re-running completed specs
        all_results, evaluated_keys = self.result_manager.load_existing_results(EVALUATION_RESULTS_FILE)
        if evaluated_keys:
            self.logger.info(f"Resuming evaluation: {len(evaluated_keys)} agent/instance pairs already cached")

        all_specs = []
        skipped_count = 0

        # Collect only unevaluated specs / agent combos
        for _, repo_specs in specs_by_repo.items():
            for spec_dict in repo_specs[:MAX_SPECS_PER_REPO]:
                spec = self._dict_to_spec(spec_dict)
                # Keep only agents that haven't evaluated this spec yet
                remaining_agents = [
                    a for a in agents_to_evaluate
                    if (a.name, spec.instance_id) not in evaluated_keys
                ]
                if remaining_agents:
                    all_specs.append((remaining_agents, spec))
                else:
                    skipped_count += 1

        if skipped_count:
            self.logger.info(f"Skipping {skipped_count} fully-evaluated specs")

        total_evaluations = len(all_specs)
        self.logger.info(f"Total evaluations to run: {total_evaluations}")
        self.logger.info(f"Using {MAX_EVAL_WORKERS} worker threads")

        # Shuffle specs to increase repo diversity during evaluation
        random.shuffle(all_specs)

        # Remove all lock files before starting evaluation
        AgentManager.remove_all_locks()
        
        # Process specs in parallel using ThreadPoolExecutor
        completed_count = 0
        with ThreadPoolExecutor(max_workers=MAX_EVAL_WORKERS) as executor:
            # Submit all tasks
            future_to_spec = {
                executor.submit(self._eval_spec, agents, spec): spec 
                for agents, spec in all_specs
            }
            
            # Process completed tasks
            for future in as_completed(future_to_spec):
                spec = future_to_spec[future]
                try:
                    results = future.result()
                    if results:
                        all_results.extend(results)
                        self.result_manager.save_evaluation_results(all_results, EVALUATION_RESULTS_FILE)
                    
                    completed_count += 1
                    self.logger.info(f"Progress: {completed_count}/{total_evaluations} evaluations completed")
                except Exception as e:
                    self.logger.error(f"Error in worker thread for {spec.instance_id}: {e}")

        self.logger.info("Evaluation completed")
    
    def _eval_spec(self, agents_to_evaluate: List[AGENTS], spec: Spec) -> Optional[List[dict]]:
        container = None
        results = []
        try:
            container = self.docker_manager.create_container(spec)
            
            # Track container before any operations (not after cleanup)
            with self.shared_data_lock:
                self.active_containers.append(container)
            
            operator = ContainerOperator(spec.repo, container)
            agent_managers = [AgentManager(container, agent_config) for agent_config in agents_to_evaluate]

            for agent_manager in agent_managers:
                self.logger.info(f"Starting evaluation of {agent_manager.agent_config.name} on {spec.instance_id}")

                result = agent_manager.evaluate(spec, operator)
                results.append(result)
        
            return results

        except Exception as e:
            self.logger.error(f"Error processing {spec.instance_id}: {e}")
        finally:
            # Check cleanup_in_progress with lock
            with self.cleanup_lock:
                should_cleanup = not self.cleanup_in_progress
            
            if container and should_cleanup:
                self.docker_manager.cleanup_container(container, force_remove=True)

    # def _eval_spec_wrapper(self, agents_to_evaluate: List[AGENTS], spec: Spec) -> Optional[List[dict]]:
    #     """Wrapper for _eval_spec that sets up per-thread logging"""
    #     thread_logger = self._setup_thread_logging(spec.instance_id)
        
    #     try:
    #         return self._eval_spec(agents_to_evaluate, spec, thread_logger)
    #     except Exception as e:
    #         thread_logger.error(f"Error in thread for {spec.instance_id}: {e}")
    #         raise
    
    # def _setup_thread_logging(self, instance_id: int) -> logging.Logger:
    #     """Setup per-thread logging"""
    #     thread_logger = logging.getLogger(f"evaluator.thread_{instance_id}")
        
    #     # Only add handler if not already added
    #     if not thread_logger.handlers:
    #         log_file = self.base_path / "logs" / f"evaluator_thread_{instance_id}.log"
    #         log_file.parent.mkdir(parents=True, exist_ok=True)
            
    #         handler = logging.FileHandler(log_file, encoding='utf-8')
    #         handler.setFormatter(logging.Formatter(
    #             '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    #         ))
    #         thread_logger.addHandler(handler)
    #         thread_logger.setLevel(logging.INFO)
    #         thread_logger.propagate = False  # Don't propagate to root logger
        
    #     return thread_logger
