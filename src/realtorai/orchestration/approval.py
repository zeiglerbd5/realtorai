"""Approval loop for agent review of proposed actions."""

from datetime import UTC, datetime
from typing import Any

import structlog

from realtorai.orchestration.feedback import FeedbackLogger
from realtorai.schemas.tasks import ApprovalAction, ApprovalStatus, Task, TaskType
from realtorai.storage.database import get_database

logger = structlog.get_logger()


class ApprovalLoop:
    """Handles the propose → review → approve/edit/reject → execute cycle."""

    def __init__(self) -> None:
        self.feedback_logger = FeedbackLogger()

    async def approve(self, task: Task) -> bool:
        """Approve a task as-is and execute it.

        Returns True if execution succeeded. The task is claimed atomically
        (pending -> executing) first, so a concurrent or repeated approval
        cannot execute the same work twice.
        """
        logger.info("task_approved", task_id=task.id, task_type=task.task_type.value)

        # Record approval action
        action = ApprovalAction(
            status=ApprovalStatus.APPROVED,
            timestamp=datetime.now(UTC).replace(tzinfo=None),
        )

        db = await get_database()
        if not await db.claim_task(task.id, action.model_dump(mode="json")):
            logger.warning("task_already_claimed", task_id=task.id)
            return False

        # Execute the action
        try:
            await self._execute(task)

            # Mark as completed
            await db.update_task_status(
                task.id,
                ApprovalStatus.APPROVED.value,
                action.model_dump(mode="json"),
            )

            # Log feedback for RL
            await self.feedback_logger.log_approval(task)

            return True

        except Exception as e:
            logger.exception("task_execution_failed", task_id=task.id, error=str(e))

            # Mark as failed
            failed_action = ApprovalAction(
                status=ApprovalStatus.FAILED,
                agent_notes=str(e),
                timestamp=datetime.now(UTC).replace(tzinfo=None),
            )
            await db.update_task_status(
                task.id,
                ApprovalStatus.FAILED.value,
                failed_action.model_dump(mode="json"),
            )

            return False

    async def approve_with_edits(
        self, task: Task, edited_content: dict[str, Any]
    ) -> bool:
        """Approve a task after editing and execute it.

        Returns True if execution succeeded.
        """
        logger.info(
            "task_approved_with_edits",
            task_id=task.id,
            task_type=task.task_type.value,
        )

        # Record approval action with edits
        action = ApprovalAction(
            status=ApprovalStatus.EDITED,
            edited_content=edited_content,
            timestamp=datetime.now(UTC).replace(tzinfo=None),
        )

        # Update the task's proposal data with edits
        updated_task = task.model_copy()
        updated_task.proposal_data = {**task.proposal_data, **edited_content}

        db = await get_database()
        if not await db.claim_task(task.id, action.model_dump(mode="json")):
            logger.warning("task_already_claimed", task_id=task.id)
            return False

        # Execute with edited content
        try:
            await self._execute(updated_task)

            # Mark as completed
            await db.update_task_status(
                task.id,
                ApprovalStatus.EDITED.value,
                action.model_dump(mode="json"),
            )

            # Log feedback for RL (edits are valuable training signal)
            await self.feedback_logger.log_edit(task, edited_content)

            return True

        except Exception as e:
            logger.exception("task_execution_failed", task_id=task.id, error=str(e))

            failed_action = ApprovalAction(
                status=ApprovalStatus.FAILED,
                edited_content=edited_content,
                agent_notes=str(e),
                timestamp=datetime.now(UTC).replace(tzinfo=None),
            )
            await db.update_task_status(
                task.id,
                ApprovalStatus.FAILED.value,
                failed_action.model_dump(mode="json"),
            )

            return False

    async def reject(self, task: Task, reason: str | None = None) -> None:
        """Reject a task without executing."""
        logger.info(
            "task_rejected",
            task_id=task.id,
            task_type=task.task_type.value,
            reason=reason,
        )

        action = ApprovalAction(
            status=ApprovalStatus.REJECTED,
            rejection_reason=reason,
            timestamp=datetime.now(UTC).replace(tzinfo=None),
        )

        db = await get_database()
        await db.update_task_status(
            task.id,
            ApprovalStatus.REJECTED.value,
            action.model_dump(mode="json"),
        )

        # Log feedback for RL (rejections are strong negative signal)
        await self.feedback_logger.log_rejection(task, reason)

    async def _execute(self, task: Task) -> None:
        """Execute a task based on its type."""
        if task.task_type == TaskType.EMAIL_RESPONSE:
            await self._execute_email_response(task)
        elif task.task_type == TaskType.CALENDAR_EVENT:
            await self._execute_calendar_event(task)
        elif task.task_type in (TaskType.EXTRACTION_MLS, TaskType.EXTRACTION_TRANSACTION):
            await self._execute_extraction(task)
        elif task.task_type == TaskType.DOCUMENT_RECEIVED:
            await self._execute_document_received(task)
        elif task.task_type == TaskType.WORKFLOW_KICKOFF:
            await self._execute_workflow_kickoff(task)
        else:
            logger.warning("unknown_task_type", task_type=task.task_type.value)

    async def _execute_workflow_kickoff(self, task: Task) -> None:
        """Run the planned work a human just approved — one workflow per plan item.

        Loads the saved intake bundle (email + attachments), extracts the
        transaction record per plan item (Claude, unless a prebuilt record was
        supplied in the proposal — demo/offline path), runs each workflow,
        then writes execution results + a narration message back onto the
        task's thread so the operator sees what the machinery did.
        """
        from pathlib import Path

        from realtorai.inference.claude_engine import get_claude_engine
        from realtorai.schemas.mls_required import readiness
        from realtorai.schemas.transaction import TransactionRecord
        from realtorai.workflows.buyer import start_buyer_workflow
        from realtorai.workflows.intake import extract_transaction_record, load_paperwork
        from realtorai.workflows.listing import start_listing_workflow

        proposal = task.proposal_data
        intake_dir = Path(proposal.get("intake_dir", ""))
        planned = proposal.get("planned_actions") or [
            {
                "side": proposal.get("side"),
                "client_name": proposal.get("client_name"),
                "property_address": None,
                "note": None,
            }
        ]
        if not intake_dir.exists() or any(
            s.get("side") not in ("listing", "buyer") for s in planned
        ):
            raise ValueError(f"Invalid workflow kickoff proposal: {planned}, dir={intake_dir}")

        attachment_paths = [
            p for p in sorted(intake_dir.iterdir()) if p.name != "email.json"
        ]
        documents = load_paperwork(attachment_paths)
        paperwork_files = [(p.name, p.read_bytes()) for p in attachment_paths]
        engine_available = get_claude_engine().available

        results: list[dict] = []
        for item in planned:
            side = item["side"]
            prebuilt = item.get("record") or proposal.get("record")
            if prebuilt:
                record = TransactionRecord.model_validate(prebuilt)
            elif engine_available:
                focus_bits = [
                    proposal.get("operator_instructions"),
                    item.get("note"),
                ]
                if item.get("client_name") or item.get("property_address"):
                    focus_bits.append(
                        "This record is specifically for "
                        f"{item.get('client_name') or 'the client'} at "
                        f"{item.get('property_address') or 'their property'} — "
                        "ignore other clients/properties mentioned in the documents."
                    )
                record = await extract_transaction_record(
                    documents,
                    side_hint="Listing" if side == "listing" else "Buyer",
                    operator_notes="\n".join(b for b in focus_bits if b) or None,
                )
            else:
                raise ValueError(
                    "Cannot extract the transaction record offline — configure "
                    "ANTHROPIC_API_KEY or supply a prebuilt record in the proposal"
                )

            start = start_listing_workflow if side == "listing" else start_buyer_workflow
            envelope = await start(
                record,
                documents=documents,
                paperwork_files=paperwork_files,
                client_name=item.get("client_name") or proposal.get("client_name"),
            )

            steps = (envelope.workflow or {}).get("steps", [])
            waiting = [
                s.get("title") or s.get("key") or "?"
                for s in steps
                if s.get("status") == "waiting"
            ]
            blocked = [
                f"{s.get('title') or s.get('key')}: {s.get('detail') or 'blocked'}"
                for s in steps
                if s.get("status") == "blocked"
            ]
            ready, total, _ = readiness(envelope.record)
            results.append(
                {
                    "slug": envelope.slug,
                    "side": side,
                    "client_name": item.get("client_name"),
                    "workflow_status": (envelope.workflow or {}).get("status"),
                    "waiting_on": waiting,
                    "blocked_on": blocked,
                    "mls_ready": f"{ready}/{total}" if side == "listing" else None,
                }
            )
            logger.info(
                "workflow_kickoff_executed",
                task_id=task.id,
                side=side,
                slug=envelope.slug,
                status=(envelope.workflow or {}).get("status"),
            )

        # Narrate the run back into the task's thread
        lines = [f"Done — ran {len(results)} workflow{'s' if len(results) != 1 else ''}:"]
        for r in results:
            bits = [f"{r['side']} — {r['client_name'] or r['slug']}: {r['workflow_status']}"]
            if r["blocked_on"]:
                bits.append(f"BLOCKED — {'; '.join(r['blocked_on'])}")
            if r["mls_ready"]:
                bits.append(f"MLS {r['mls_ready']} required fields ready")
            if r["waiting_on"]:
                bits.append(f"waiting on {', '.join(r['waiting_on'])}")
            lines.append("• " + "; ".join(bits))
        updated = dict(proposal)
        updated["execution_results"] = results
        conversation = list(updated.get("conversation", []))
        conversation.append({"role": "agent", "text": "\n".join(lines)})
        updated["conversation"] = conversation
        db = await get_database()
        await db.update_task_data(task.id, updated, details=task.details)

    async def _execute_email_response(self, task: Task) -> None:
        """Execute an email response task."""
        from realtorai.integrations.graph.email import send_email

        proposal = task.proposal_data
        draft = proposal.get("draft_response", {})

        if not draft:
            raise ValueError("No draft response in task")

        reply_to_id = task.related_email_id

        await send_email(
            to=task.details.get("sender_email", ""),
            subject=draft.get("subject", ""),
            body=draft.get("body", ""),
            reply_to_id=reply_to_id,
        )

        logger.info("email_sent", task_id=task.id, to=task.details.get("sender_email"))

    async def _execute_calendar_event(self, task: Task) -> None:
        """Execute a calendar event task."""
        # TODO: Implement calendar event creation
        logger.warning("calendar_event_not_implemented", task_id=task.id)

    async def _execute_extraction(self, task: Task) -> None:
        """Execute an extraction task (MLS or Transaction)."""
        from realtorai.inference.extraction import (
            MLSExtraction,
            TransactionExtraction,
            apply_mls_extraction,
            apply_transaction_extraction,
        )
        from realtorai.transactions import mark_document_received, set_milestone

        proposal = task.proposal_data
        details = task.details
        extraction_type = proposal.get("extraction_type")
        raw_extraction = proposal.get("raw_extraction", {})
        client_id = details.get("client_id")
        client_name = details.get("client_name")

        if not client_id or not client_name:
            raise ValueError("Missing client_id or client_name in task details")

        if extraction_type == "mls":
            # Apply MLS extraction
            mls_extraction = MLSExtraction(**raw_extraction)
            result = await apply_mls_extraction(
                client_id=client_id,
                name=client_name,
                extraction=mls_extraction,
                source="approval_queue",
            )
            logger.info(
                "mls_extraction_applied",
                task_id=task.id,
                client_id=client_id,
                result=result,
            )

        elif extraction_type == "transaction":
            # Apply transaction extraction
            tx_extraction = TransactionExtraction(**raw_extraction)
            result = await apply_transaction_extraction(
                client_id=client_id,
                name=client_name,
                extraction=tx_extraction,
                source="approval_queue",
            )

            # Set additional milestones from proposal
            milestones = proposal.get("milestones_to_set", [])
            for milestone in milestones:
                set_milestone(client_id, client_name, milestone)

            # Mark additional documents from proposal
            documents = proposal.get("documents_to_mark", [])
            for doc in documents:
                mark_document_received(client_id, client_name, doc)

            logger.info(
                "transaction_extraction_applied",
                task_id=task.id,
                client_id=client_id,
                result=result,
                milestones=milestones,
                documents=documents,
            )

        else:
            raise ValueError(f"Unknown extraction type: {extraction_type}")

        # Resolve matching pending items
        pending_item_ids = proposal.get("pending_items_to_resolve", [])
        if pending_item_ids:
            db = await get_database()
            for item_id in pending_item_ids:
                await db.resolve_pending_item(item_id, status="received")
            logger.info(
                "pending_items_resolved",
                task_id=task.id,
                client_id=client_id,
                resolved_ids=pending_item_ids,
            )

    async def _execute_document_received(self, task: Task) -> None:
        """Execute a document received task.

        Marks the associated pending item as received/resolved.
        If this is a buyer/listing agency agreement, converts lead to client.
        """
        proposal = task.proposal_data
        details = task.details

        pending_item_id = proposal.get("pending_item_id")
        new_status = proposal.get("new_status", "received")
        client_id = details.get("client_id")
        pending_item_desc = details.get("pending_item_description", "").lower()

        if not pending_item_id:
            raise ValueError("No pending_item_id in task proposal")

        db = await get_database()
        await db.resolve_pending_item(pending_item_id, status=new_status)

        # Check if this was an agency agreement - if so, convert lead to client
        is_agency_agreement = any(term in pending_item_desc for term in [
            "buyer agency", "agency agreement", "listing agreement",
            "client agreement", "representation agreement",
        ])

        if is_agency_agreement and client_id:
            # Get the client/lead to check their status
            client = await db.get_client(client_id)
            if client and client.get("status") == "lead":
                # Convert lead to active client
                await db.convert_lead_to_client(client_id)
                # Add standard client pending items (pre-approval, etc.)
                tx_type = client.get("transaction_type", "buy")
                await db.add_standard_client_pending_items(client_id, tx_type)

                logger.info(
                    "lead_converted_on_agreement",
                    task_id=task.id,
                    client_id=client_id,
                    client_name=client.get("name"),
                )

        logger.info(
            "document_received_executed",
            task_id=task.id,
            client_id=client_id,
            pending_item_id=pending_item_id,
            pending_item_desc=details.get("pending_item_description"),
            new_status=new_status,
        )


# Default instance
approval_loop = ApprovalLoop()
