"""
Type definitions for data transformation module

This module contains all type definitions and dataclasses used
in the data transformation pipeline.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class BaseCommit:
    """Base commit information"""
    sha: str
    date: str


@dataclass
class FileChange:
    """File change information"""
    filename: str


@dataclass
class PRAnalysis:
    """PR analysis information"""
    pr_number: str
    base_commit: BaseCommit
    detailed_description: str
    file_changes: List[Dict]
    test_files: List[str]
    non_test_files: List[str]


@dataclass
class EnhancedNewFeature:
    """Enhanced new feature information"""
    pr_analyses: List[PRAnalysis]


@dataclass
class RawEntry:
    """Raw entry from data collection stage"""
    repository: str
    release: str
    enhanced_new_features: List[EnhancedNewFeature]


@dataclass
class ProcessedItem:
    """Processed and transformed item"""
    repo: str
    instance_id: str
    base_commit: str
    patch: List[Dict]
    test_patch: List[Dict]
    problem_statement: str
    hints_text: str
    created_at: str
    version: str
    org: str
    number: int
    PASS_TO_PASS: str
    FAIL_TO_PASS: str
    test_files: List[str]