"""
Evaluation results management

This module handles saving and processing evaluation results.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple, Set


class EvaluationResultManager:
    """Manages evaluation results for a single experiment run."""

    def __init__(self, results_file: Path):
        """
        Args:
            results_file: Full path to the JSON file holding this run's results.
        """
        self.results_file = results_file
        self.logger = logging.getLogger(__name__)

    def save_evaluation_results(self, results: List[Dict[str, Any]]) -> None:
        """Persist results to this run's results file."""
        self.results_file.parent.mkdir(parents=True, exist_ok=True)

        with self.results_file.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Saved {len(results)} new results to {self.results_file}")

    def load_existing_results(self) -> Tuple[List[Dict[str, Any]], Set[Tuple[str, str]]]:
        """
        Load existing evaluation results for cache/resumption.

        Returns:
            Tuple of (results_list, evaluated_keys) where evaluated_keys is a set
            of (agent_name, instance_id) tuples that have already been evaluated.
        """
        if not self.results_file.exists():
            return [], set()

        try:
            with self.results_file.open("r", encoding="utf-8") as f:
                results = json.load(f)
            evaluated_keys = {(r["agent"], r["instance_id"]) for r in results}
            self.logger.info(
                f"Loaded {len(results)} cached results "
                f"({len(evaluated_keys)} unique agent/instance pairs) from {self.results_file}"
            )
            return results, evaluated_keys
        except Exception as e:
            self.logger.warning(f"Failed to load existing results from {self.results_file}: {e}")
            return [], set()
