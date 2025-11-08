"""
File manager for reading and writing data files

This module handles all file I/O operations for the data transformation pipeline.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any
from .types import ProcessedItem
from docker_agent.core.exceptions import FileOperationError


class FileManager:
    """Manages file reading and writing operations"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def read_raw_data(self, input_path: str) -> Dict[str, Any]:
        """
        Read raw data from input JSON file

        Args:
            input_path: Path to input JSON file

        Returns:
            Parsed JSON data

        Raises:
            FileNotFoundError: If input file doesn't exist
            json.JSONDecodeError: If file contains invalid JSON
        """
        input_file = Path(input_path)
        if not input_file.exists():
            raise FileOperationError(f"Input file not found: {input_path}", file_path=input_path)

        self.logger.info(f"Reading raw data from {input_path}")

        try:
            with open(input_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.logger.info(f"Successfully read {len(data.get('results', []))} raw entries")
            return data
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in {input_path}: {e}")
            raise

    def write_processed_data(self, data: List[ProcessedItem], output_path: str):
        """
        Write processed data to output JSON file

        Args:
            data: List of processed items
            output_path: Path to output JSON file
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Writing {len(data)} processed items to {output_path}")

        # Convert dataclasses to dictionaries
        output_data = [
            {
                "repo": item.repo,
                "instance_id": item.instance_id,
                "base_commit": item.base_commit,
                "patch": item.patch,
                "test_patch": item.test_patch,
                "problem_statement": item.problem_statement,
                "hints_text": item.hints_text,
                "created_at": item.created_at,
                "version": item.version,
                "org": item.org,
                "number": item.number,
                "PASS_TO_PASS": item.PASS_TO_PASS,
                "FAIL_TO_PASS": item.FAIL_TO_PASS,
                "test_files": item.test_files
            }
            for item in data
        ]

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Successfully wrote {len(data)} items to {output_path}")

    def deduplicate_items(self, items: List[ProcessedItem]) -> List[ProcessedItem]:
        """
        Deduplicate items by instance_id, keeping the last one

        Args:
            items: List of processed items

        Returns:
            Deduplicated list of items
        """
        self.logger.info(f"Deduplicating {len(items)} items by instance_id")

        dedup_map = {item.instance_id: item for item in items}
        deduped = list(dedup_map.values())

        removed_count = len(items) - len(deduped)
        if removed_count > 0:
            self.logger.info(f"Removed {removed_count} duplicate items")

        self.logger.info(f"After deduplication: {len(deduped)} items remain")
        return deduped