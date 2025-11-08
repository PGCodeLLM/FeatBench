"""
Shared types and enums for docker_agent

This module contains all shared type definitions, enums, and dataclasses
used across the docker_agent package.
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Optional
from docker_agent.parsing.pytest_parser import TestStatus
import docker.models.containers

class AgentTaskType(Enum):
    """Agent task type enumeration"""
    FILE_LIST = "file_list"
    ENV_SETUP = "env_setup"

@dataclass
class CodeChange:
    """Code change information"""
    name: str
    change_type: str  # 'added', 'modified', 'deleted'
    code_type: str    # 'class', 'function', 'method'

@dataclass
class Spec:
    """Represents an evaluation specification"""
    instance_id: str
    repo: str
    repo_name: str
    base_commit: str
    number: str
    problem_statement: Optional[str] = None
    patch: Optional[List[Dict]] = None
    test_patch: Optional[List[Dict]] = None
    test_files: Optional[List[str]] = None
    created_at: Optional[str] = None
    PASS_TO_PASS: Optional[str] = None
    FAIL_TO_PASS: Optional[str] = None
    processed: bool = False


# Type aliases
Container = docker.models.containers.Container
TestResults = Dict[str, TestStatus]