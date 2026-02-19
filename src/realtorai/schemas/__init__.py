"""Pydantic schemas for structured LLM outputs and data models."""

from realtorai.schemas.common import Confidence, ReasoningStep
from realtorai.schemas.email import (
    DraftResponse,
    EmailClassification,
    EmailIntent,
    EmailPriority,
    EmailProposal,
)
from realtorai.schemas.tasks import ApprovalAction, ApprovalStatus, Task, TaskType

__all__ = [
    # Common
    "Confidence",
    "ReasoningStep",
    # Email
    "EmailClassification",
    "EmailIntent",
    "EmailPriority",
    "DraftResponse",
    "EmailProposal",
    # Tasks
    "Task",
    "TaskType",
    "ApprovalAction",
    "ApprovalStatus",
]
