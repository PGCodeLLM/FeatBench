"""
Data transformer - main orchestrator for data transformation

This module contains the main DataTransformer class that orchestrates
the entire data transformation pipeline.
"""

import logging
from typing import List, Dict, Any
from .data_processor import DataProcessor
from .file_manager import FileManager
from .types import ProcessedItem


class DataTransformer:
    """Main data transformation orchestrator"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.data_processor = DataProcessor()
        self.file_manager = FileManager()

    def transform(
        self,
        input_path: str,
        output_path: str,
        deduplicate: bool = True
    ) -> List[ProcessedItem]:
        """
        Transform raw data from input_path to processed data at output_path

        Args:
            input_path: Path to input JSON file
            output_path: Path to output JSON file
            deduplicate: Whether to deduplicate items by instance_id

        Returns:
            List of processed items

        Raises:
            FileNotFoundError: If input file doesn't exist
            Exception: If transformation fails
        """
        self.logger.info("Starting data transformation pipeline")
        self.logger.info(f"Input: {input_path}")
        self.logger.info(f"Output: {output_path}")
        self.logger.info(f"Deduplication: {deduplicate}")

        try:
            # Step 1: Read raw data
            raw_data = self.file_manager.read_raw_data(input_path)

            # Step 2: Process all entries
            all_processed = self._process_all_entries(raw_data)

            # Step 3: Deduplicate if requested
            if deduplicate:
                all_processed = self.file_manager.deduplicate_items(all_processed)

            # Step 4: Write processed data
            self.file_manager.write_processed_data(all_processed, output_path)

            self.logger.info("Data transformation completed successfully")
            return all_processed

        except Exception as e:
            self.logger.error(f"Data transformation failed: {e}")
            raise

    def _process_all_entries(self, raw_data: Dict[str, Any]) -> List[ProcessedItem]:
        """
        Process all entries in raw data

        Args:
            raw_data: Raw data dictionary

        Returns:
            List of all processed items
        """
        self.logger.info(f"Processing entries from raw data")

        all_processed = []
        entries = raw_data.get("results", [])

        for i, entry in enumerate(entries):
            self.logger.debug(f"Processing entry {i+1}/{len(entries)}")
            processed = self.data_processor.process_entry(entry)
            all_processed.extend(processed)

        self.logger.info(f"Processed {len(all_processed)} total items from {len(entries)} entries")
        return all_processed
