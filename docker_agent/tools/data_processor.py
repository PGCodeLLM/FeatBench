"""
Data processor for processing raw entries

This module contains the logic for processing individual raw entries
from the data collection stage and converting them to the target format.
"""

import logging
from typing import List, Dict, Optional
from .types import RawEntry, ProcessedItem


class DataProcessor:
    """Processes raw data entries into target format"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def process_entry(self, entry: Dict) -> List[ProcessedItem]:
        """
        Process a single raw entry, extract and convert to target format list

        Args:
            entry: Raw entry from data collection stage

        Returns:
            List of processed items
        """
        processed = []
        repo = entry.get("repository")
        version = entry.get("release")

        if not repo:
            self.logger.warning("Entry missing repository, skipping")
            return processed

        # Process each enhanced_new_features
        for feature in entry.get("enhanced_new_features", []):
            feature_items = self._process_feature(feature, repo, version)
            processed.extend(feature_items)

        return processed

    def _process_feature(
        self,
        feature: Dict,
        repo: str,
        version: str
    ) -> List[ProcessedItem]:
        """
        Process a single enhanced new feature

        Args:
            feature: Feature data
            repo: Repository name
            version: Release version

        Returns:
            List of processed items
        """
        processed = []

        # Process each pr_analyses
        for pr in feature.get("pr_analyses", []):
            pr_item = self._process_pr(pr, repo, version)
            if pr_item:
                processed.append(pr_item)

        return processed

    def _process_pr(
        self,
        pr: Dict,
        repo: str,
        version: str
    ) -> Optional[ProcessedItem]:
        """
        Process a single PR analysis

        Args:
            pr: PR analysis data
            repo: Repository name
            version: Release version

        Returns:
            Processed item or None if invalid
        """
        # Extract basic information
        pr_number = pr.get("pr_number")
        if not pr_number:
            self.logger.warning("PR missing pr_number, skipping")
            return None

        base_commit = pr.get("base_commit", {}).get("sha", "")
        if not base_commit:
            self.logger.warning(f"PR {pr_number} missing base_commit, skipping")
            return None

        created_at = pr.get("base_commit", {}).get("date", "")
        detailed_desc = pr.get("detailed_description", "")

        # Extract organization name (first part of repo)
        org = repo.split("/")[0] if "/" in repo else repo

        # Generate instance_id
        instance_id = f"{repo.replace('/', '__')}-{pr_number}"

        # Get all file change records
        all_file_changes = pr.get("file_changes", [])

        # Get test_files list and extract corresponding changes
        test_file_names = pr.get("test_files", [])
        test_changes = [
            fc for fc in all_file_changes
            if fc.get("filename") in test_file_names
        ]

        # Get non_test_files list and extract corresponding changes
        non_test_changes = [
            fc for fc in all_file_changes
            if fc.get("filename") not in test_file_names
        ]

        # Build target format dictionary
        processed_item = ProcessedItem(
            repo=repo,
            instance_id=instance_id,
            base_commit=base_commit,
            patch=non_test_changes,
            test_patch=test_changes,
            problem_statement=detailed_desc,
            hints_text="",
            created_at=created_at,
            version=version,
            org=org,
            number=int(pr_number) if pr_number else 0,
            PASS_TO_PASS="",
            FAIL_TO_PASS="",
            test_files=test_file_names
        )

        return processed_item