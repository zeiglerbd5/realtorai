"""
Tests for Pydantic schemas.
"""

import pytest
from datetime import datetime, timezone


class TestCommonSchemas:
    """Tests for common schemas."""

    def test_confidence_enum(self):
        """Test confidence enum values."""
        from realtorai.schemas.common import Confidence

        assert Confidence.HIGH == "high"
        assert Confidence.MEDIUM == "medium"
        assert Confidence.LOW == "low"

    def test_contact_reference(self):
        """Test contact reference schema."""
        from realtorai.schemas.common import ContactReference

        contact = ContactReference(
            email="client@example.com",
            name="John Doe",
            role="client",
            is_known=True,
        )

        assert contact.email == "client@example.com"
        assert contact.name == "John Doe"
        assert contact.role == "client"
        assert contact.is_known is True

    def test_contact_reference_minimal(self):
        """Test contact reference with minimal data."""
        from realtorai.schemas.common import ContactReference

        contact = ContactReference(email="test@example.com")

        assert contact.email == "test@example.com"
        assert contact.name is None
        assert contact.role is None
        assert contact.is_known is False

    def test_reasoning_step(self):
        """Test reasoning step schema."""
        from realtorai.schemas.common import ReasoningStep

        step = ReasoningStep(
            step=1,
            thought="Analyzing the email content",
            observation="Found a showing request",
        )

        assert step.step == 1
        assert step.thought == "Analyzing the email content"

    def test_chain_of_reasoning(self):
        """Test chain of reasoning schema."""
        from realtorai.schemas.common import ChainOfReasoning, ReasoningStep, Confidence

        chain = ChainOfReasoning(
            steps=[
                ReasoningStep(step=1, thought="Email is about scheduling"),
                ReasoningStep(step=2, thought="Client wants a showing"),
            ],
            conclusion="Schedule a showing",
            confidence=Confidence.HIGH,
        )

        assert len(chain.steps) == 2
        assert chain.conclusion == "Schedule a showing"
        assert chain.confidence == Confidence.HIGH
        assert "Schedule a showing" in chain.summary


class TestEmailSchemas:
    """Tests for email-related schemas."""

    def test_email_priority_enum(self):
        """Test email priority enum."""
        from realtorai.schemas.email import EmailPriority

        assert EmailPriority.CRITICAL == "critical"
        assert EmailPriority.HIGH == "high"
        assert EmailPriority.NORMAL == "normal"
        assert EmailPriority.LOW == "low"

    def test_email_intent_enum(self):
        """Test email intent enum."""
        from realtorai.schemas.email import EmailIntent

        assert EmailIntent.QUESTION == "question"
        assert EmailIntent.SCHEDULING == "scheduling"
        assert EmailIntent.NEGOTIATION == "negotiation"

    def test_email_classification(self):
        """Test email classification schema."""
        from realtorai.schemas.email import (
            EmailClassification,
            EmailPriority,
            EmailIntent,
        )
        from realtorai.schemas.common import ContactReference, Confidence

        classification = EmailClassification(
            sender=ContactReference(email="client@example.com", name="Sarah"),
            intent=EmailIntent.SCHEDULING,
            priority=EmailPriority.HIGH,
            requires_response=True,
            subject_summary="Wants to schedule a showing",
            key_points=["Interested in property", "Available this weekend"],
            confidence=Confidence.HIGH,
        )

        assert classification.sender.email == "client@example.com"
        assert classification.intent == EmailIntent.SCHEDULING
        assert classification.priority == EmailPriority.HIGH
        assert classification.requires_response is True
        assert len(classification.key_points) == 2

    def test_draft_response(self):
        """Test draft response schema."""
        from realtorai.schemas.email import DraftResponse

        draft = DraftResponse(
            subject="Re: Showing Request",
            body="Hi Sarah, I'd be happy to schedule a showing...",
        )

        assert draft.subject == "Re: Showing Request"
        assert draft.is_reply is True
        assert draft.include_signature is True
        assert draft.suggested_attachments == []


class TestTaskSchemas:
    """Tests for task-related schemas."""

    def test_task_type_enum(self):
        """Test task type enum."""
        from realtorai.schemas.tasks import TaskType

        assert TaskType.EMAIL_RESPONSE == "email_response"
        assert TaskType.CALENDAR_EVENT == "calendar_event"
        assert TaskType.FOLLOWUP_REMINDER == "followup_reminder"

    def test_approval_status_enum(self):
        """Test approval status enum."""
        from realtorai.schemas.tasks import ApprovalStatus

        assert ApprovalStatus.PENDING == "pending"
        assert ApprovalStatus.APPROVED == "approved"
        assert ApprovalStatus.REJECTED == "rejected"

    def test_task_creation(self):
        """Test task model creation."""
        from realtorai.schemas.tasks import Task, TaskType, ApprovalStatus

        task = Task(
            id="task-123",
            task_type=TaskType.EMAIL_RESPONSE,
            title="Reply to inquiry",
            summary="Client inquiry about property",
        )

        assert task.id == "task-123"
        assert task.task_type == TaskType.EMAIL_RESPONSE
        assert task.status == ApprovalStatus.PENDING
        assert task.confidence is None
        assert task.proposal_data == {}

    def test_task_with_proposal_data(self):
        """Test task with proposal data."""
        from realtorai.schemas.tasks import Task, TaskType

        task = Task(
            id="task-456",
            task_type=TaskType.CALENDAR_EVENT,
            title="Schedule showing",
            summary="Schedule property showing",
            confidence="high",
            proposal_data={
                "property": "123 Main St",
                "suggested_times": ["2024-01-20 10:00", "2024-01-20 14:00"],
            },
        )

        assert task.confidence == "high"
        assert "property" in task.proposal_data
        assert len(task.proposal_data["suggested_times"]) == 2

    def test_approval_action(self):
        """Test approval action schema."""
        from realtorai.schemas.tasks import ApprovalAction, ApprovalStatus

        action = ApprovalAction(
            status=ApprovalStatus.EDITED,
            edited_content={"subject": "Updated subject"},
            agent_notes="Fixed the subject line",
        )

        assert action.status == ApprovalStatus.EDITED
        assert action.edited_content["subject"] == "Updated subject"
        assert action.rejection_reason is None

    def test_feedback_record(self):
        """Test feedback record for RL training."""
        from realtorai.schemas.tasks import FeedbackRecord, TaskType, ApprovalStatus

        record = FeedbackRecord(
            task_id="task-123",
            task_type=TaskType.EMAIL_RESPONSE,
            original_proposal={"subject": "Hello", "body": "Test"},
            action=ApprovalStatus.EDITED,
            edited_proposal={"subject": "Hello!", "body": "Test updated"},
        )

        assert record.task_id == "task-123"
        assert record.action == ApprovalStatus.EDITED
        assert record.signal_strength == "normal"
