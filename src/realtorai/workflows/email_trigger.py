"""Email-driven workflow kickoff.

The intended flow: the realtor signs a new client, then emails the bot —
"here's the new client's paperwork" — with the signed agreements attached.
This module classifies that email, extracts the transaction record from the
attachments, and starts the matching workflow.

Wired for use from the email daemon (`EmailAgent` can call
`handle_new_client_email` when triage sees a paperwork handoff) and from the
demo scripts.
"""

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


def _heuristic_classification(subject: str, body: str) -> IntakeClassification:
    """Keyword fallback when the Claude API is not configured."""
    haystack = f"{subject}\n{body}".lower()
    if any(h in haystack for h in _LISTING_HINTS):
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
