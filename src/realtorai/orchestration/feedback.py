"""Feedback logging for RL training data collection."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from realtorai.config.settings import get_settings
from realtorai.schemas.tasks import ApprovalStatus, FeedbackRecord, Task

logger = structlog.get_logger()


class FeedbackLogger:
    """Logs feedback from approval actions for future RL training.

    Every approval, edit, and rejection is recorded with full context.
    This data will be used to refine the model during periodic training cycles.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def _get_log_path(self) -> Path:
        """Get the path for today's feedback log file."""
        today = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d")
        return self.settings.feedback_log_dir / f"feedback_{today}.jsonl"

    async def _write_record(self, record: FeedbackRecord) -> None:
        """Write a feedback record to the log file."""
        log_path = self._get_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, "a") as f:
            f.write(record.model_dump_json() + "\n")

        logger.debug("feedback_recorded", task_id=record.task_id, action=record.action.value)

    async def log_approval(self, task: Task) -> None:
        """Log an approved task (strong positive signal)."""
        record = FeedbackRecord(
            task_id=task.id,
            task_type=task.task_type,
            original_proposal=task.proposal_data,
            original_reasoning=task.reasoning_summary,
            action=ApprovalStatus.APPROVED,
            context=task.details,
            signal_strength="strong",
        )
        await self._write_record(record)

    async def log_edit(self, task: Task, edited_content: dict[str, Any]) -> None:
        """Log an edited task (most valuable training signal).

        The diff between original and edited captures exactly what the model
        got wrong and how the agent wanted it said.
        """
        # Compute diff between original and edited
        diff = self._compute_diff(task.proposal_data, edited_content)

        record = FeedbackRecord(
            task_id=task.id,
            task_type=task.task_type,
            original_proposal=task.proposal_data,
            original_reasoning=task.reasoning_summary,
            action=ApprovalStatus.EDITED,
            edited_proposal=edited_content,
            diff=diff,
            context=task.details,
            signal_strength="strong",  # Edits are the most valuable signal
        )
        await self._write_record(record)

    async def log_rejection(self, task: Task, reason: str | None) -> None:
        """Log a rejected task (strong negative signal)."""
        record = FeedbackRecord(
            task_id=task.id,
            task_type=task.task_type,
            original_proposal=task.proposal_data,
            original_reasoning=task.reasoning_summary,
            action=ApprovalStatus.REJECTED,
            context={**task.details, "rejection_reason": reason},
            signal_strength="strong",
        )
        await self._write_record(record)

    def _compute_diff(
        self, original: dict[str, Any], edited: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute a simple diff between original and edited proposals."""
        diff = {
            "added": {},
            "removed": {},
            "changed": {},
        }

        all_keys = set(original.keys()) | set(edited.keys())

        for key in all_keys:
            if key not in original:
                diff["added"][key] = edited[key]
            elif key not in edited:
                diff["removed"][key] = original[key]
            elif original[key] != edited[key]:
                diff["changed"][key] = {
                    "from": original[key],
                    "to": edited[key],
                }

        return diff

    async def get_recent_feedback(self, days: int = 7) -> list[FeedbackRecord]:
        """Load recent feedback records for analysis.

        Args:
            days: Number of days of history to load

        Returns:
            List of feedback records
        """
        records = []
        feedback_log_dir = self.settings.feedback_log_dir

        if not feedback_log_dir.exists():
            return records

        # Get files from recent days
        for i in range(days):
            date = datetime.now(UTC).replace(tzinfo=None).date()
            date_str = date.strftime("%Y-%m-%d")
            log_path = feedback_log_dir / f"feedback_{date_str}.jsonl"

            if log_path.exists():
                with open(log_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            records.append(FeedbackRecord.model_validate(data))

        return records

    async def get_stats(self, days: int = 7) -> dict[str, Any]:
        """Get statistics about recent feedback.

        Returns counts of approvals, edits, and rejections.
        """
        records = await self.get_recent_feedback(days)

        stats = {
            "total": len(records),
            "approved": 0,
            "edited": 0,
            "rejected": 0,
            "approval_rate": 0.0,
            "edit_rate": 0.0,
        }

        for record in records:
            if record.action == ApprovalStatus.APPROVED:
                stats["approved"] += 1
            elif record.action == ApprovalStatus.EDITED:
                stats["edited"] += 1
            elif record.action == ApprovalStatus.REJECTED:
                stats["rejected"] += 1

        if stats["total"] > 0:
            stats["approval_rate"] = (
                stats["approved"] + stats["edited"]
            ) / stats["total"]
            stats["edit_rate"] = stats["edited"] / stats["total"]

        return stats
