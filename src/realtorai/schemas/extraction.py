"""Extraction proposal schemas for approval queue."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExtractionType(str, Enum):
    """Types of data extraction."""

    MLS = "mls"
    TRANSACTION = "transaction"


class FieldChange(BaseModel):
    """A single field change in an extraction proposal."""

    field_path: str = Field(description="Dot-notated path, e.g., 'dates.closing_date'")
    current_value: Any = Field(default=None, description="Current value (null if new)")
    proposed_value: Any = Field(description="Extracted value to apply")
    source_snippet: str = Field(default="", description="Email text supporting this")


class PendingItemMatch(BaseModel):
    """A pending item that will be resolved by an extraction."""

    id: int
    description: str
    waiting_on: str
    item_type: str


class ExtractionProposal(BaseModel):
    """Proposal to apply extracted data to a tracker.

    Created from email/document extraction. Queued for agent review
    showing diff between current and proposed values.
    """

    extraction_type: ExtractionType
    client_id: int
    client_name: str

    # Source info for citation
    source_email_subject: str | None = None
    source_email_from: str | None = None
    source_snippet: str = Field(default="", description="Relevant email excerpt")

    # The diff
    changes: list[FieldChange] = Field(default_factory=list)

    # Full extraction for applying
    raw_extraction: dict[str, Any] = Field(default_factory=dict)

    # Confidence
    confidence: str = Field(default="medium")

    # Transaction-specific
    milestones_to_set: list[str] = Field(default_factory=list)
    documents_to_mark: list[str] = Field(default_factory=list)

    # Pending items that will be resolved by this extraction
    pending_items_to_resolve: list[PendingItemMatch] = Field(default_factory=list)

    def get_summary(self) -> str:
        """Generate a summary string for queue display."""
        if not self.changes:
            return "No changes detected"

        field_names = [c.field_path for c in self.changes[:3]]
        summary = ", ".join(field_names)
        if len(self.changes) > 3:
            summary += f", +{len(self.changes) - 3} more"
        return summary

    def get_title(self) -> str:
        """Generate a title for the task."""
        type_label = "MLS Update" if self.extraction_type == ExtractionType.MLS else "Transaction Update"
        return f"{type_label}: {self.client_name}"
