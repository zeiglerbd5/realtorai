"""Task queue for managing pending approvals."""

import uuid
from datetime import datetime
from typing import Any

import structlog

from realtorai.schemas.tasks import ApprovalStatus, Task, TaskType
from realtorai.storage.database import get_database

logger = structlog.get_logger()


class TaskQueue:
    """Manages the queue of tasks awaiting approval."""

    @staticmethod
    def generate_id() -> str:
        """Generate a unique task ID."""
        return f"task_{uuid.uuid4().hex[:12]}"

    async def add_email_task(
        self,
        email_id: str,
        sender_email: str,
        sender_name: str | None,
        subject: str,
        classification: dict[str, Any],
        draft_response: dict[str, Any] | None,
        reasoning_summary: str,
        confidence: str,
    ) -> str:
        """Add an email response task to the queue.

        Returns the task ID.
        """
        db = await get_database()

        task_id = self.generate_id()
        title = f"Reply to {sender_name or sender_email}"
        summary = f"{subject[:50]}..." if len(subject) > 50 else subject

        await db.create_task(
            task_id=task_id,
            task_type=TaskType.EMAIL_RESPONSE.value,
            title=title,
            summary=summary,
            details={
                "sender_email": sender_email,
                "sender_name": sender_name,
                "subject": subject,
                "classification": classification,
            },
            proposal_data={
                "draft_response": draft_response,
                "action": "send_reply",
            },
            reasoning_summary=reasoning_summary,
            confidence=confidence,
            related_email_id=email_id,
            related_contact=sender_email,
        )

        # Mark email as processed
        await db.mark_email_processed(email_id, None, task_id)

        logger.info("email_task_added", task_id=task_id, email_id=email_id)
        return task_id

    async def add_custom_task(
        self,
        task_type: TaskType,
        title: str,
        summary: str,
        details: dict[str, Any],
        proposal_data: dict[str, Any],
        reasoning_summary: str | None = None,
        confidence: str | None = None,
        related_contact: str | None = None,
        related_transaction: str | None = None,
    ) -> str:
        """Add a custom task to the queue.

        Returns the task ID.
        """
        db = await get_database()

        task_id = self.generate_id()

        await db.create_task(
            task_id=task_id,
            task_type=task_type.value,
            title=title,
            summary=summary,
            details=details,
            proposal_data=proposal_data,
            reasoning_summary=reasoning_summary,
            confidence=confidence,
            related_contact=related_contact,
            related_transaction=related_transaction,
        )

        logger.info("custom_task_added", task_id=task_id, task_type=task_type.value)
        return task_id

    async def get_pending(self, limit: int = 50) -> list[Task]:
        """Get pending tasks from the queue."""
        db = await get_database()
        rows = await db.get_pending_tasks(limit=limit)

        tasks = []
        for row in rows:
            tasks.append(
                Task(
                    id=row["id"],
                    task_type=TaskType(row["task_type"]),
                    status=ApprovalStatus(row["status"]),
                    title=row["title"],
                    summary=row["summary"],
                    details=row["details"],
                    proposal_data=row["proposal_data"],
                    reasoning_summary=row["reasoning_summary"],
                    confidence=row["confidence"],
                    related_email_id=row["related_email_id"],
                    related_contact=row["related_contact"],
                    related_transaction=row["related_transaction"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"])
                    if row["updated_at"]
                    else None,
                )
            )

        return tasks

    async def get_task(self, task_id: str) -> Task | None:
        """Get a specific task by ID."""
        db = await get_database()
        row = await db.get_task(task_id)

        if not row:
            return None

        return Task(
            id=row["id"],
            task_type=TaskType(row["task_type"]),
            status=ApprovalStatus(row["status"]),
            title=row["title"],
            summary=row["summary"],
            details=row["details"],
            proposal_data=row["proposal_data"],
            reasoning_summary=row["reasoning_summary"],
            confidence=row["confidence"],
            related_email_id=row["related_email_id"],
            related_contact=row["related_contact"],
            related_transaction=row["related_transaction"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
            if row["updated_at"]
            else None,
        )

    async def count_pending(self) -> int:
        """Get count of pending tasks."""
        tasks = await self.get_pending(limit=1000)
        return len(tasks)


# Default instance
task_queue = TaskQueue()
