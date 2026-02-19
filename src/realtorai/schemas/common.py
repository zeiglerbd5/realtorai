"""Common schemas shared across modules."""

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    """Confidence level for LLM outputs."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReasoningStep(BaseModel):
    """A single step in a chain-of-reasoning output."""

    step: Annotated[int, Field(ge=1, description="Step number")]
    thought: Annotated[str, Field(description="What the model is thinking")]
    observation: Annotated[str | None, Field(default=None, description="What the model observed")]


class ChainOfReasoning(BaseModel):
    """Full chain-of-reasoning for an LLM decision."""

    steps: Annotated[list[ReasoningStep], Field(description="Reasoning steps")]
    conclusion: Annotated[str, Field(description="Final conclusion")]
    confidence: Annotated[Confidence, Field(description="Confidence in conclusion")]

    @property
    def summary(self) -> str:
        """Short summary of the reasoning chain."""
        if self.steps:
            return f"{self.steps[-1].thought} → {self.conclusion}"
        return self.conclusion


class ContactReference(BaseModel):
    """Reference to a known contact."""

    email: Annotated[str, Field(description="Email address")]
    name: Annotated[str | None, Field(default=None, description="Display name if known")]
    role: Annotated[
        str | None,
        Field(default=None, description="Role/relationship (client, agent, lender, etc.)"),
    ]
    is_known: Annotated[bool, Field(default=False, description="Whether contact is in database")]
