"""
Custom exceptions for docker_agent

This module defines all custom exception classes used throughout
the docker_agent package to provide better error handling and debugging.
"""

from typing import Optional

class FeatBenchError(Exception):
    """Base exception for all custom errors in FeatBench"""
    pass


class ContainerError(FeatBenchError):
    """Raised when container operations fail"""
    def __init__(self, message: str, container_id: Optional[str] = None):
        super().__init__(message)
        self.container_id = container_id


class ContainerCreationError(ContainerError):
    """Raised when container creation fails"""
    pass


class ContainerOperationError(ContainerError):
    """Raised when container operation fails"""
    pass


class CacheError(FeatBenchError):
    """Raised when cache operations fail"""
    pass


class AgentError(FeatBenchError):
    """Raised when agent operations fail"""
    def __init__(self, message: str, agent_name: Optional[str] = None):
        super().__init__(message)
        self.agent_name = agent_name


class AgentSetupError(AgentError):
    """Raised when agent setup fails"""
    pass


class AgentExecutionError(AgentError):
    """Raised when agent execution fails"""
    pass


class ConfigurationError(FeatBenchError):
    """Raised when configuration is invalid or missing"""
    pass


class SpecProcessingError(FeatBenchError):
    """Raised when spec processing fails"""
    def __init__(self, message: str, spec_id: Optional[str] = None):
        super().__init__(message)
        self.spec_id = spec_id


class PatchError(FeatBenchError):
    """Raised when patch operations fail"""
    def __init__(self, message: str, patch_file: Optional[str] = None):
        super().__init__(message)
        self.patch_file = patch_file


class TestExecutionError(FeatBenchError):
    """Raised when test execution fails"""
    pass


class TestAnalysisError(FeatBenchError):
    """Raised when test analysis fails"""
    pass


class FileOperationError(FeatBenchError):
    """Raised when file operations fail"""
    def __init__(self, message: str, file_path: Optional[str] = None):
        super().__init__(message)
        self.file_path = file_path


class CleanupError(FeatBenchError):
    """Raised when cleanup operations fail"""
    pass