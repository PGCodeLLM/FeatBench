"""
Agent Evaluator - Reuses existing modules

This module provides agent evaluation functionality by reusing existing
docker_agent modules for better maintainability and consistency.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional
import random

from tqdm import tqdm

from docker_agent.core.base_runner import BaseRunner
from docker_agent.container.container_operator import ContainerOperator
from docker_agent.agents.manager import AgentManager
from docker_agent.parsing.patch_analyzer import PatchAnalyzer
from docker_agent.evaluation.results import EvaluationResultManager
from docker_agent.config.config import AGENTS, EVALUATION_RESULTS_DIR, MAX_SPECS_PER_REPO, MAX_EVAL_WORKERS, EXP_ID
from docker_agent.core.types import Spec


class AgentEvaluator(BaseRunner):
    """Agent evaluator"""

    def __init__(self):
        """Initialize Agent Evaluator"""
        super().__init__()

        self.result_manager = EvaluationResultManager(EVALUATION_RESULTS_DIR / f"{EXP_ID}.json")
        self.patch_analyzer = PatchAnalyzer()
        self.shared_data_lock = threading.Lock()
        self._executor = None  # Set during evaluate/reevaluate for signal-handler shutdown

    def _on_signal(self):
        """Shut down the executor so no new workers start, then clean up containers."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        super()._on_signal()

    def _setup_instance_logger(self, instance_id: str, log_dir: Path):
        """Set up a per-instance file logger so each instance's harness logs go to its own directory."""
        logger_name = f"instance.{instance_id}"
        instance_logger = logging.getLogger(logger_name)
        if not instance_logger.handlers:
            instance_logger.setLevel(logging.DEBUG)
            instance_logger.propagate = False
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_dir / "harness.log", encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            instance_logger.addHandler(fh)

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
        all_results, evaluated_keys = self.result_manager.load_existing_results()
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
        passed_count = 0
        failed_count = 0
        with ThreadPoolExecutor(max_workers=MAX_EVAL_WORKERS) as executor:
            self._executor = executor
            future_to_spec = {
                executor.submit(self._eval_spec, agents, spec): spec
                for agents, spec in all_specs
            }

            with tqdm(total=total_evaluations, desc="Evaluating", unit="inst") as pbar:
                for future in as_completed(future_to_spec):
                    spec = future_to_spec[future]
                    try:
                        results = future.result()
                        if results:
                            all_results.extend(results)
                            self.result_manager.save_evaluation_results(all_results)
                            for r in results:
                                if r.get("success"):
                                    passed_count += 1
                                else:
                                    failed_count += 1
                    except Exception as e:
                        self.logger.error(f"Error in worker thread for {spec.instance_id}: {e}")
                        failed_count += 1

                    pbar.set_postfix({"pass": passed_count, "fail": failed_count})
                    pbar.update(1)

            self._executor = None

        self.logger.info(f"Evaluation completed: {passed_count} passed, {failed_count} failed")

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
        # Load cached results from the experiment identified by EXP_ID
        cached_results, _ = self.result_manager.load_existing_results()
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
        passed_count = 0
        failed_count = 0
        with ThreadPoolExecutor(max_workers=MAX_EVAL_WORKERS) as executor:
            self._executor = executor
            future_to_key = {
                executor.submit(self._reeval_spec, spec, agent_name, model_name, patch_content): (agent_name, spec.instance_id)
                for spec, agent_name, model_name, patch_content in work_items
            }

            with tqdm(total=len(work_items), desc="Re-evaluating", unit="inst") as pbar:
                for future in as_completed(future_to_key):
                    key = future_to_key[future]
                    try:
                        result = future.result()
                        if result:
                            with self.shared_data_lock:
                                all_results[result_index[key]] = result
                            self.result_manager.save_evaluation_results(all_results)
                            if result.get("success"):
                                passed_count += 1
                            else:
                                failed_count += 1
                    except Exception as e:
                        self.logger.error(f"Error in worker thread for {key}: {e}")
                        failed_count += 1

                    pbar.set_postfix({"pass": passed_count, "fail": failed_count})
                    pbar.update(1)

            self._executor = None

        self.logger.info(f"Re-evaluation completed: {passed_count} passed, {failed_count} failed")

    def _reeval_spec(self, spec: Spec, agent_name: str, model_name: str, patch_content: str) -> Optional[dict]:
        """Re-evaluate a single spec with a cached patch."""
        if self.cleanup_in_progress:
            return None
        container = None
        try:
            container = self.docker_manager.create_container(spec)

            with self.shared_data_lock:
                self.active_containers.append(container)

            instance_log_dir = self.base_path / "logs" / EXP_ID / spec.instance_id
            self._setup_instance_logger(spec.instance_id, instance_log_dir)

            operator = ContainerOperator(spec.repo, container, log_dir=instance_log_dir)
            manager = AgentManager(container, AGENTS[0], log_dir=instance_log_dir)  # agent config unused for reevaluate

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
        if self.cleanup_in_progress:
            return None
        container = None
        results = []
        try:
            container = self.docker_manager.create_container(spec)

            # Track container before any operations (not after cleanup)
            with self.shared_data_lock:
                self.active_containers.append(container)

            instance_log_dir = self.base_path / "logs" / EXP_ID / spec.instance_id
            self._setup_instance_logger(spec.instance_id, instance_log_dir)

            operator = ContainerOperator(spec.repo, container, log_dir=instance_log_dir)
            agent_managers = [AgentManager(container, agent_config, log_dir=instance_log_dir) for agent_config in agents_to_evaluate]

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

