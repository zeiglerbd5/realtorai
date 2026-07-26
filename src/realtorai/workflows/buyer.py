"""Buyer-side workflow: signed buyer agreement -> room with filed paperwork.

Buyer clients get a Transaction Room but no MLS activity:

  1. Verify the extracted record against the paperwork (Opus review pass)
  2. Render the Master Information Document (internal)
  3. Create the DocuSign Transaction Room (buy side)
  4. Add the "Buyer Agreement" task list
  5. Attach + auto-fill the Exclusive Buyer Representation Agreement and
     Brokerage Relationship forms; file the signed copies into the room
"""

import structlog

from realtorai.schemas.transaction import TransactionRecord
from realtorai.storage.transaction_store import (
    TransactionEnvelope,
    load_transaction,
    slug_for,
)
from realtorai.workflows import common
from realtorai.workflows.engine import Step, WorkflowContext, run_workflow
from realtorai.workflows.intake import PaperworkDocument

logger = structlog.get_logger()

BUYER_WORKFLOW = "buyer"

BUYER_STEPS: list[tuple[Step, object]] = [
    (
        Step(key="verify_extraction", title="Verify paperwork extraction (Opus)"),
        common.verify_extraction,
    ),
    (
        Step(key="master_doc", title="Generate Master Information Document"),
        common.render_master_doc,
    ),
    (
        Step(key="create_room", title="Create DocuSign Transaction Room (buy side)"),
        lambda ctx: common.create_room_step(ctx, transaction_side_id="buy"),
    ),
    (
        Step(key="task_list", title="Add “Buyer Agreement” task list"),
        lambda ctx: common.add_task_list_step(ctx, template_name="Buyer Agreement"),
    ),
    (
        Step(key="agency_forms", title="Attach + auto-fill buyer agreement forms"),
        lambda ctx: common.attach_forms_step(
            ctx,
            form_names=[
                "Exclusive Buyer Representation Agreement",
                "Brokerage Relationship Form",
            ],
        ),
    ),
    (
        Step(key="file_paperwork", title="File signed paperwork to room"),
        common.upload_paperwork_step,
    ),
]


async def start_buyer_workflow(
    record: TransactionRecord,
    *,
    documents: list[PaperworkDocument] | None = None,
    paperwork_files: list[tuple[str, bytes]] | None = None,
    client_id: int | None = None,
    client_name: str | None = None,
) -> TransactionEnvelope:
    """Start (or resume) the buyer workflow for a record."""
    record.representation_side = record.representation_side or "Buyer"
    fallback = (record.buyer_1.name or client_name or "buyer").lower().replace(" ", "-")
    slug = slug_for(record, fallback=f"buyer-{fallback}")
    envelope = load_transaction(slug) or TransactionEnvelope(slug=slug, record=record)
    envelope.client_id = client_id or envelope.client_id
    envelope.client_name = client_name or envelope.client_name or record.buyer_1.name

    ctx = WorkflowContext(envelope, documents=documents, paperwork_files=paperwork_files)
    await run_workflow(BUYER_WORKFLOW, BUYER_STEPS, ctx)
    return envelope
