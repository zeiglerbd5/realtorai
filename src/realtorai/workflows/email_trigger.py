"""Email-driven workflow kickoff — ALWAYS through the approval queue.

The intended flow: the realtor signs a new client and the paperwork lands in
the monitored inbox (signed-envelope notifications, "here's the new client's
paperwork" handoffs). This module classifies the email and creates a
WORKFLOW_KICKOFF task in the approval queue. NOTHING runs until a human
approves the task in the UI — approval triggers extraction and the matching
workflow (see orchestration/approval.py).

`propose_new_client_workflow` is the production entry point (propose → human
approves → execute). `handle_new_client_email` runs immediately and exists
for demos/tests only.
"""

import json
import uuid
from pathlib import Path

import structlog

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.storage.transaction_store import TransactionEnvelope
from realtorai.workflows.buyer import start_buyer_workflow
from realtorai.workflows.intake import (
    IntakeClassification,
    classify_intake_email,
    extract_transaction_record,
    paperwork_from_bytes,
)
from realtorai.workflows.listing import start_listing_workflow

logger = structlog.get_logger()

_LISTING_HINTS = ("exclusive right to sell", "listing agreement", "new listing")
_BUYER_HINTS = ("buyer representation", "buyer rep", "buyer agreement", "new buyer")
_UC_HINTS = ("purchase and sale", "purchase & sale", "under contract", "accepted offer")
_CLOSING_HINTS = (
    "settlement statement", "closing statement", "closing disclosure",
    "clear to close", "alta statement",
)


def _heuristic_classification(subject: str, body: str) -> IntakeClassification:
    """Keyword fallback when the Claude API is not configured."""
    haystack = f"{subject}\n{body}".lower()
    if any(h in haystack for h in _CLOSING_HINTS):
        intent = "closing"
    elif any(h in haystack for h in _UC_HINTS):
        intent = "under_contract"
    elif any(h in haystack for h in _LISTING_HINTS):
        intent = "new_listing_client"
    elif any(h in haystack for h in _BUYER_HINTS):
        intent = "new_buyer_client"
    else:
        intent = "other"
    return IntakeClassification(
        intent=intent,
        confidence="low",
        reasoning="keyword heuristic (offline mode)",
    )


def _match_transaction(property_address: str | None) -> str | None:
    """Find an existing transaction whose street address matches (casefold)."""
    if not property_address:
        return None
    from realtorai.storage.transaction_store import list_transactions

    needle = property_address.lower()
    for env in list_transactions():
        street = (env.record.street_address or "").lower()
        if street and (street in needle or needle in street):
            return env.slug
    return None


def _opening_question(
    classification: IntakeClassification, side: str, attachment_names: list[str]
) -> str:
    """The copilot's opening ask in the task's conversation thread."""
    subject_bits = []
    if classification.property_address:
        subject_bits.append(classification.property_address)
    if classification.client_name:
        subject_bits.append(f"for {classification.client_name}")
    what = " ".join(subject_bits) or "a new client"

    if side == "listing":
        ask = (
            f"This looks like a new listing — {what}. Want me to start the listing "
            "workflow: DTR room + task list, deed / tax card / tax map / flood "
            "pulls, and an MLS draft?"
        )
    else:
        ask = (
            f"This looks like a new buyer client — {what}. Want me to start the "
            "buyer workflow: DTR room + buyer-agreement task list?"
        )
    if not attachment_names:
        ask += (
            " No paperwork came attached — if you have the signed agreement, "
            "include its file path in your reply and I'll work from it."
        )
    return ask


async def propose_new_client_workflow(
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
    *,
    source: str = "email",
) -> str | None:
    """Classify a possible new-client email and QUEUE the workflow for approval.

    Saves the email + attachments under data/intake/<id>/ and creates a
    WORKFLOW_KICKOFF task. Returns the task ID, or None when the email isn't
    a new-client handoff. The workflow itself runs only on human approval.
    """
    from realtorai.config.settings import get_settings
    from realtorai.orchestration.queue import task_queue
    from realtorai.schemas.tasks import TaskType

    engine = get_claude_engine()
    attachment_names = [name for name, _ in attachments]

    if engine.available:
        classification = await classify_intake_email(subject, body, attachment_names)
    else:
        classification = _heuristic_classification(subject, body)

    logger.info(
        "intake_email_classified",
        intent=classification.intent,
        confidence=classification.confidence,
        source=source,
    )
    if classification.intent == "other":
        return None
    if classification.intent in ("under_contract", "closing"):
        return await _propose_phase_change(
            classification, subject, body, attachments, source=source
        )

    # Persist the intake bundle for the post-approval execution step
    intake_id = f"intake_{uuid.uuid4().hex[:10]}"
    intake_dir = get_settings().data_dir / "intake" / intake_id
    intake_dir.mkdir(parents=True, exist_ok=True)
    (intake_dir / "email.json").write_text(
        json.dumps({"subject": subject, "body": body, "source": source}, indent=2)
    )
    for name, content in attachments:
        (intake_dir / Path(name).name).write_bytes(content)

    side = "listing" if classification.intent == "new_listing_client" else "buyer"
    question = _opening_question(classification, side, attachment_names)
    task_id = await task_queue.add_custom_task(
        task_type=TaskType.WORKFLOW_KICKOFF,
        title=f"New {side} client detected — start intake workflow?",
        summary=subject[:80],
        details={
            "intent": classification.intent,
            "client_name": classification.client_name,
            "property_address": classification.property_address,
            "attachments": [Path(n).name for n in attachment_names],
            "classifier_reasoning": classification.reasoning,
            "source": source,
        },
        proposal_data={
            "action": "run_intake_workflow",
            "side": side,
            "intake_dir": str(intake_dir),
            "client_name": classification.client_name,
            "conversation": [{"role": "agent", "text": question}],
            "planned_actions": [
                {
                    "side": side,
                    "client_name": classification.client_name,
                    "property_address": classification.property_address,
                    "note": None,
                }
            ],
        },
        reasoning_summary=classification.reasoning,
        confidence=classification.confidence,
    )
    logger.info("workflow_kickoff_proposed", task_id=task_id, side=side, intake=intake_id)
    return task_id


async def _propose_phase_change(
    classification: IntakeClassification,
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
    *,
    source: str,
) -> str | None:
    """Queue a phase change (under contract / closing) on an existing deal."""
    from realtorai.config.settings import get_settings
    from realtorai.orchestration.queue import task_queue
    from realtorai.schemas.tasks import TaskType

    kind = classification.intent
    slug = _match_transaction(classification.property_address)

    intake_id = f"intake_{uuid.uuid4().hex[:10]}"
    intake_dir = get_settings().data_dir / "intake" / intake_id
    intake_dir.mkdir(parents=True, exist_ok=True)
    (intake_dir / "email.json").write_text(
        json.dumps({"subject": subject, "body": body, "source": source}, indent=2)
    )
    for name, content in attachments:
        (intake_dir / Path(name).name).write_bytes(content)

    where = classification.property_address or "the property"
    if kind == "closing":
        doc_name = "settlement statement"
        if slug:
            question = (
                f"{where} is heading to the closing table. Want me to run the "
                f"closing phase on {slug}: review the statement against the "
                "record, Closing task list, update the Transaction Worksheet, "
                "MLS to Closed, and close out the room?"
            )
        else:
            question = (
                f"This reads as a closing on {where}, but I can't match it to "
                "a transaction I'm tracking. Tell me which one (or reject if "
                "it's not ours)."
            )
        title = "Deal closing — run the closing phase?"
    else:
        doc_name = "P&S"
        if slug:
            question = (
                f"Looks like {where} just went under contract. Want me to run the "
                f"under-contract phase on {slug}: UC task list, file the P&S, "
                "Transaction Worksheet, MLS to Pending, and deadline tracking?"
            )
        else:
            question = (
                f"This reads as an accepted contract on {where}, but I can't match "
                "it to a transaction I'm tracking. Tell me which one (or reject if "
                "it's not ours)."
            )
        title = "Deal under contract — run the under-contract phase?"
    if not attachments:
        question += (
            f" No {doc_name} came attached — include its file path in your "
            "reply and I'll extract the terms from it."
        )

    task_id = await task_queue.add_custom_task(
        task_type=TaskType.WORKFLOW_KICKOFF,
        title=title,
        summary=subject[:80],
        details={
            "intent": classification.intent,
            "client_name": classification.client_name,
            "property_address": classification.property_address,
            "transaction_slug": slug,
            "attachments": [Path(n).name for n, _ in attachments],
            "classifier_reasoning": classification.reasoning,
            "source": source,
        },
        proposal_data={
            "action": "run_intake_workflow",
            "intake_dir": str(intake_dir),
            "client_name": classification.client_name,
            "conversation": [{"role": "agent", "text": question}],
            "planned_actions": [
                {
                    "kind": kind,
                    "transaction_slug": slug,
                    "side": None,
                    "client_name": classification.client_name,
                    "property_address": classification.property_address,
                    "note": None,
                }
            ],
        },
        reasoning_summary=classification.reasoning,
        confidence=classification.confidence,
    )
    logger.info("phase_change_proposed", task_id=task_id, kind=kind, slug=slug, intake=intake_id)
    return task_id


async def handle_new_client_email(
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
) -> TransactionEnvelope | None:
    """Classify a possible new-client email and kick off the right workflow.

    Returns the transaction envelope, or None when the email isn't a
    new-client handoff (or extraction isn't possible offline).
    """
    engine = get_claude_engine()
    attachment_names = [name for name, _ in attachments]

    if engine.available:
        classification = await classify_intake_email(subject, body, attachment_names)
    else:
        classification = _heuristic_classification(subject, body)

    logger.info(
        "intake_email_classified",
        intent=classification.intent,
        confidence=classification.confidence,
    )
    if classification.intent == "other":
        return None

    documents = [paperwork_from_bytes(name, content) for name, content in attachments]

    if not engine.available:
        logger.warning(
            "intake_extraction_unavailable",
            note="no ANTHROPIC_API_KEY — cannot extract a record from paperwork; "
            "start the workflow directly with a prepared TransactionRecord",
        )
        return None

    side_hint = "Listing" if classification.intent == "new_listing_client" else "Buyer"
    record = await extract_transaction_record(documents, side_hint=side_hint)

    if classification.intent == "new_listing_client":
        return await start_listing_workflow(
            record,
            documents=documents,
            paperwork_files=attachments,
            client_name=classification.client_name,
        )
    return await start_buyer_workflow(
        record,
        documents=documents,
        paperwork_files=attachments,
        client_name=classification.client_name,
    )
