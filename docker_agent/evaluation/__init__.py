"""
Evaluation module - Agent evaluation functionality

This module provides tools for evaluating multiple agents on test specifications.
"""

from .evaluator import AgentEvaluator
from .results import EvaluationResultManager

__all__ = [
    "AgentEvaluator",
    "EvaluationResultManager",
]
