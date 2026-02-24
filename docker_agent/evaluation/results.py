"""
Evaluation results management

This module handles saving and processing evaluation results.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any

from docker_agent.config.config import EXP_SUFFIX


class EvaluationResultManager:
    """Manages evaluation results"""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.logger = logging.getLogger(__name__)

    def save_evaluation_results(self, results: List[Dict[str, Any]], filename: str):
        """
        Save evaluation results

        Args:
            results: List of evaluation results
            filename: Output filename
        """
        results_file = self.base_path / "results" / filename
        new_filename = f"{results_file.stem}_{EXP_SUFFIX}{results_file.suffix}"
        results_file = results_file.parent / new_filename

        results_file.parent.mkdir(parents=True, exist_ok=True)

        with results_file.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Saved {len(results)} new results to {results_file}")

    def load_existing_results(self, filename: str) -> tuple:
        """
        Load existing evaluation results for cache/resumption.

        Args:
            filename: Results filename (same convention as save_evaluation_results)

        Returns:
            Tuple of (results_list, evaluated_keys) where evaluated_keys is a set
            of (agent_name, instance_id) tuples that have already been evaluated.
        """
        results_file = self.base_path / "results" / filename
        new_filename = f"{results_file.stem}_{EXP_SUFFIX}{results_file.suffix}"
        results_file = results_file.parent / new_filename

        if not results_file.exists():
            return [], set()

        try:
            with results_file.open("r", encoding="utf-8") as f:
                results = json.load(f)
            evaluated_keys = {(r["agent"], r["instance_id"]) for r in results}
            self.logger.info(
                f"Loaded {len(results)} cached results "
                f"({len(evaluated_keys)} unique agent/instance pairs) from {results_file}"
            )
            return results, evaluated_keys
        except Exception as e:
            self.logger.warning(f"Failed to load existing results from {results_file}: {e}")
            return [], set()
