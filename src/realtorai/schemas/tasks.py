"""Task and approval queue schemas."""

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    """Types of tasks in the queue."""

    EMAIL_RESPONSE = "email_response"
    EMAIL_FORWARD = "email_forward"
    CALENDAR_EVENT = "calendar_event"
    DOCUMENT_SEND = "document_send"
    DOCUMENT_RECEIVED = "document_received"  # Client sent a document (signed agreement, etc.)
    LISTING_ALERT = "listing_alert"
    FOLLOWUP_REMINDER = "followup_reminder"
    TRANSACTION_UPDATE = "transaction_update"
    EXTRACTION_MLS = "extraction_mls"
    EXTRACTION_TRANSACTION = "extraction_transaction"
    WORKFLOW_KICKOFF = "workflow_kickoff"  # New-client intake detected; approve to run workflow
    CUSTOM = "custom"


class ApprovalStatus(str, Enum):
    """Status of a task in the approval queue."""

    PENDING = "pending"  # Awaiting agent review
    APPROVED = "approved"  # Approved and executed
    EDITED = "edited"  # Edited then approved
    REJECTED = "rejected"  # Rejected by agent
    EXPIRED = "expired"  # Became stale/irrelevant
    EXECUTING = "executing"  # Currently being executed
    FAILED = "failed"  # Execution failed


class ApprovalAction(BaseModel):
    """Action taken by agent on a pending task."""

    status: Annotated[ApprovalStatus, Field(description="New status")]
    edited_content: Annotated[
        dict[str, Any] | None,
        Field(default=None, description="Edited content if status is EDITED"),
    ]
    rejection_reason: Annotated[
        str | None,
        Field(default=None, description="Reason for rejection if status is REJECTED"),
    ]
    agent_notes: Annotated[
        str | None, Field(default=None, description="Optional notes from agent")
    ]
    timestamp: Annotated[
        datetime, Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    ]


class Task(BaseModel):
    """A task in the approval queue."""

    # Identity
    id: Annotated[str, Field(description="Unique task ID")]
    task_type: Annotated[TaskType, Field(description="Type of task")]
    created_at: Annotated[
        datetime, Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    ]

    # Status
    status: Annotated[ApprovalStatus, Field(default=ApprovalStatus.PENDING)]
    updated_at: Annotated[datetime | None, Field(default=None)]

    # Content
    title: Annotated[str, Field(description="Display title")]
    summary: Annotated[str, Field(description="Brief summary for queue view")]
    details: Annotated[dict[str, Any], Field(default_factory=dict, description="Full task details")]

    # Proposal data (type-specific)
    proposal_data: Annotated[
        dict[str, Any], Field(default_factory=dict, description="The proposed action data")
    ]

    # Reasoning
    reasoning_summary: Annotated[
        str | None, Field(default=None, description="Summary of reasoning chain")
    ]
    confidence: Annotated[str | None, Field(default=None, description="Confidence level")]

    # Relationships
    related_email_id: Annotated[
        str | None, Field(default=None, description="Related email if applicable")
    ]
    related_contact: Annotated[
        str | None, Field(default=None, description="Related contact email")
    ]
    related_transaction: Annotated[
        str | None, Field(default=None, description="Related transaction ID")
    ]

    # Approval tracking
    approval_action: Annotated[
        ApprovalAction | None, Field(default=None, description="Action taken if processed")
    ]


class FeedbackRecord(BaseModel):
    """Record of feedback for RL training.

    Captures the full context of an approval decision for later model refinement.
    """

    # Task reference
    task_id: Annotated[str, Field(description="Original task ID")]
    task_type: Annotated[TaskType, Field(description="Type of task")]
    timestamp: Annotated[
        datetime, Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    ]

    # What the model produced
    original_proposal: Annotated[dict[str, Any], Field(description="Original model output")]
    original_reasoning: Annotated[str | None, Field(default=None)]

    # What the agent did
    action: Annotated[ApprovalStatus, Field(description="Agent's action")]
    edited_proposal: Annotated[
        dict[str, Any] | None,
        Field(default=None, description="Edited version if applicable"),
    ]

    # The diff (for EDITED actions)
    diff: Annotated[
        dict[str, Any] | None, Field(default=None, description="Diff between original and edited")
    ]

    # Context that was provided
    context: Annotated[dict[str, Any], Field(default_factory=dict, description="Input context")]

    # Quality signal
    signal_strength: Annotated[
        str,
        Field(
            default="normal",
            description="How strong a training signal this is (strong/normal/weak)",
        ),
    ]
