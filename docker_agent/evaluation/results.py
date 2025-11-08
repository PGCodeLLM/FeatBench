"""
Evaluation results management

This module handles saving and processing evaluation results.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any


class EvaluationResultManager:
    """Manages evaluation results"""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.logger = logging.getLogger(__name__)

    def save_evaluation_results(self, results: List[Dict[str, Any]], filename: str):
        """
        Save evaluation results (append mode)

        Args:
            results: List of evaluation results
            filename: Output filename
        """
        results_file = self.base_path / "results" / filename
        results_file.parent.mkdir(parents=True, exist_ok=True)

        existing_results = []
        if results_file.exists():
            with results_file.open("r", encoding="utf-8") as f:
                try:
                    existing_results = json.load(f)
                except Exception:
                    existing_results = []

        all_results = existing_results + results

        with results_file.open("w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Saved {len(results)} new results to {results_file}")