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

    def evaluate(self, agent_names: Optional[List[str]] = None, instance_ids: Optional[List[str]] = None):
        """
        Main evaluation method

        Args:
            agent_names: List of agent names to evaluate
            instance_ids: List of instance IDs to evaluate. If None, evaluates all instances.
        """
        agents_to_evaluate = [a for a in AGENTS if agent_names is None or a.name in agent_names]
        if not agents_to_evaluate:
            self.logger.error("No agents to evaluate")
            return

        specs_by_repo = self._load_specs()

        if instance_ids is not None:
            instance_id_set = set(instance_ids)
            self.logger.info(f"Filtering to {len(instance_id_set)} specified instance IDs")

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
                if instance_ids is not None and spec.instance_id not in instance_id_set:
                    continue
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
        # We are not using repo locks anymore, but this is just in case there are any leftover lock files from previous runs that might interfere with the evaluation
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

    def reevaluate(self, agent_names: Optional[List[str]] = None, instance_ids: Optional[List[str]] = None):
        """
        Re-evaluate cached patches from a previous experiment run.

        Loads existing results (matched via --resume-timestamp), extracts the saved
        patch for each instance, spins up containers, applies the patch, and re-runs
        the F2P / P2P tests. The agent is never invoked.

        Args:
            agent_names: List of agent names to re-evaluate
            instance_ids: List of instance IDs to re-evaluate. If None, re-evaluates all.
        """
        # Load cached results from the experiment identified by EXP_SUFFIX
        cached_results, _ = self.result_manager.load_existing_results(EVALUATION_RESULTS_FILE)
        if not cached_results:
            self.logger.error("No cached results found for the given timestamp. Nothing to re-evaluate.")
            return

        # Build an index from (agent, instance_id) -> position in cached_results
        # so we can replace entries in-place as they complete.
        result_index: dict = {}
        reeval_keys: list = []
        for idx, r in enumerate(cached_results):
            key = (r.get("agent"), r.get("instance_id"))
            result_index[key] = idx
            patch = r.get("patch")
            matches_filters = (
                (not agent_names or key[0] in agent_names)
                and (not instance_ids or key[1] in instance_ids)
            )
            if patch and matches_filters:
                reeval_keys.append(key)

        if not reeval_keys:
            self.logger.error("No cached results with patches match the given filters.")
            return

        self.logger.info(
            f"Found {len(reeval_keys)} cached patches to re-evaluate, "
            f"{len(cached_results) - len(reeval_keys)} results kept unchanged"
        )

        # Load specs and build instance_id -> spec mapping
        specs_by_repo = self._load_specs()
        spec_lookup: dict = {}
        for _, repo_specs in specs_by_repo.items():
            for spec_dict in repo_specs[:MAX_SPECS_PER_REPO]:
                spec = self._dict_to_spec(spec_dict)
                spec_lookup[spec.instance_id] = spec

        # Build work items: (spec, agent_name, model_name, patch_content)
        work_items = []
        for agent_name, instance_id in reeval_keys:
            spec = spec_lookup.get(instance_id)
            if not spec:
                self.logger.warning(f"Spec not found for instance {instance_id}, skipping")
                continue
            cached = cached_results[result_index[(agent_name, instance_id)]]
            work_items.append((spec, agent_name, cached.get("model", ""), cached["patch"]))

        self.logger.info(f"Total re-evaluations to run: {len(work_items)}")
        self.logger.info(f"Using {MAX_EVAL_WORKERS} worker threads")

        random.shuffle(work_items)
        AgentManager.remove_all_locks()

        # Start with the full cached list; completed re-evals replace their entry in-place.
        all_results = list(cached_results)
        completed_count = 0
        with ThreadPoolExecutor(max_workers=MAX_EVAL_WORKERS) as executor:
            future_to_key = {
                executor.submit(self._reeval_spec, spec, agent_name, model_name, patch_content): (agent_name, spec.instance_id)
                for spec, agent_name, model_name, patch_content in work_items
            }

            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    result = future.result()
                    if result:
                        with self.shared_data_lock:
                            all_results[result_index[key]] = result
                        self.result_manager.save_evaluation_results(all_results, EVALUATION_RESULTS_FILE)

                    completed_count += 1
                    self.logger.info(f"Progress: {completed_count}/{len(work_items)} re-evaluations completed")
                except Exception as e:
                    self.logger.error(f"Error in worker thread for {key}: {e}")

        self.logger.info("Re-evaluation completed")

    def _reeval_spec(self, spec: Spec, agent_name: str, model_name: str, patch_content: str) -> Optional[dict]:
        """Re-evaluate a single spec with a cached patch."""
        container = None
        try:
            container = self.docker_manager.create_container(spec)

            with self.shared_data_lock:
                self.active_containers.append(container)

            operator = ContainerOperator(spec.repo, container)
            manager = AgentManager(container, AGENTS[0])  # agent config unused for reevaluate

            result = manager.reevaluate(spec, operator, patch_content, agent_name, model_name)
            return result

        except Exception as e:
            self.logger.error(f"Error re-evaluating {spec.instance_id}: {e}")
        finally:
            with self.cleanup_lock:
                should_cleanup = not self.cleanup_in_progress

            if container and should_cleanup:
                self.docker_manager.cleanup_container(container, force_remove=True)

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
