"""Under-contract workflow: accepted P&S -> UC task list + TW + deadlines.

Runs against an EXISTING transaction (the listing or buyer intake created
it); going under contract is a phase change, not a new deal. The signed
Purchase & Sale Agreement is the authoritative source for contract terms:

  1. Extract contract terms from the P&S (Sonnet, focused schema — never
     a full-record re-extraction, so listing-phase data can't be clobbered)
  2. Verify the merged record against the P&S (Opus; critical issues BLOCK)
  3. Add the side-appropriate "Under Contract" task list to the room
  4. Add the Earnest Money Deposit task list (buyer side, when the deposit
     is held at our agency)
  5. File the signed contract paperwork to the room
  6. Fill the Transaction Worksheet (the office's UC reference sheet)
  7. Move the MLS listing to Pending (listing side)
  8. Create deadline pending-items (EMD, inspection, financing, closing) —
     these surface on the dashboard's Waiting On panel with due dates
  9. Refresh the master information document
"""

from datetime import date
from decimal import Decimal

import structlog
from pydantic import BaseModel, Field

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.inference.model_router import LLMTask
from realtorai.schemas.transaction import Party, TransactionRecord
from realtorai.storage.transaction_store import (
    TransactionEnvelope,
    load_transaction,
)
from realtorai.workflows import common
from realtorai.workflows.engine import (
    Step,
    StepResult,
    StepStatus,
    WorkflowContext,
    run_workflow,
)
from realtorai.workflows.intake import PaperworkDocument, _documents_block

logger = structlog.get_logger()

UC_WORKFLOW = "under_contract"


# ---------------------------------------------------------------------------
# Contract-terms extraction (STANDARD tier) — focused schema, explicit merge
# ---------------------------------------------------------------------------


class ContractTerms(BaseModel):
    """Terms of an accepted Purchase & Sale Agreement."""

    contract_amount: Decimal | None = Field(default=None, description="Purchase price")
    binding_date: date | None = Field(
        default=None, description="Effective/binding date (last party signature)"
    )
    closing_date: date | None = None
    emd_amount: Decimal | None = None
    emd_due_date: date | None = None
    entity_holding_emd: str | None = None
    inspection_deadline: date | None = None
    financing_commitment_deadline: date | None = None
    appraisal_deadline: date | None = None
    financing_type: str | None = Field(
        default=None, description="e.g. Conventional, FHA, VA, Cash"
    )
    seller_concession_amount: Decimal | None = None
    buyer_names: list[str] = Field(default_factory=list)
    comments: str | None = Field(
        default=None,
        description="Material terms that don't fit a field (personal property, "
        "fuel proration, kick-out, repairs)",
    )


EXTRACT_CONTRACT_SYSTEM = """You are a meticulous Maine real-estate transaction \
coordinator extracting the terms of an accepted Purchase & Sale Agreement.

Rules:
- Only extract what the documents actually state; leave unknown fields null.
- binding_date is the date of the LAST party signature (mutual acceptance).
- Deadlines expressed as "within N days" count from the binding date — resolve
  them to calendar dates only when the binding date is stated; otherwise note
  the relative deadline in comments.
- Capture who holds the earnest money verbatim."""

# Fields the P&S authoritatively sets on the record (overwrite, not fill-if-None
# — the accepted contract supersedes estimates from the listing phase).
_CONTRACT_FIELDS = (
    "contract_amount",
    "binding_date",
    "closing_date",
    "emd_amount",
    "emd_due_date",
    "entity_holding_emd",
    "inspection_deadline",
    "financing_commitment_deadline",
    "appraisal_deadline",
    "financing_type",
    "seller_concession_amount",
)


def apply_contract_terms(record: TransactionRecord, terms: ContractTerms) -> list[str]:
    """Merge accepted-contract terms into the record. Returns fields set."""
    applied: list[str] = []
    for field in _CONTRACT_FIELDS:
        value = getattr(terms, field)
        if value is not None:
            setattr(record, field, value)
            applied.append(field)
    for i, name in enumerate(terms.buyer_names[:2], start=1):
        slot = f"buyer_{i}"
        existing = getattr(record, slot)
        if existing is None or existing.name is None:
            setattr(record, slot, Party(name=name))
            applied.append(slot)
    if terms.comments:
        record.comments = (
            f"{record.comments}\n[P&S] {terms.comments}"
            if record.comments
            else f"[P&S] {terms.comments}"
        )
        applied.append("comments")
    if record.representation_side != "Buyer" and record.listing_status is not None:
        record.listing_status = "Pending"
        applied.append("listing_status")
    return applied


async def extract_contract_terms(ctx: WorkflowContext) -> StepResult:
    """Extract P&S terms and merge them into the existing record."""
    prebuilt = getattr(ctx, "contract_terms", None)
    if prebuilt is not None:
        terms = ContractTerms.model_validate(prebuilt)
    elif not ctx.documents:
        return StepResult(
            status=StepStatus.BLOCKED,
            detail="no P&S documents attached — attach the signed contract and resume",
        )
    elif get_claude_engine().available:
        engine = get_claude_engine()
        terms = await engine.generate_structured(
            "Extract the contract terms from this accepted Purchase & Sale "
            "Agreement and related documents.\n\n" + _documents_block(ctx.documents),
            ContractTerms,
            task=LLMTask.EXTRACT,
            system_prompt=EXTRACT_CONTRACT_SYSTEM,
        )
    else:
        return StepResult(status=StepStatus.SKIPPED, detail=common.OFFLINE_NOTE)

    applied = apply_contract_terms(ctx.record, terms)
    return StepResult(detail=f"{len(applied)} fields set from P&S: {', '.join(applied)}")


# ---------------------------------------------------------------------------
# Phase steps
# ---------------------------------------------------------------------------


async def uc_task_list(ctx: WorkflowContext) -> StepResult:
    side = "Buyer" if ctx.record.representation_side == "Buyer" else "Listing"
    return await common.add_task_list_step(
        ctx, template_name=f"Under Contract — {side} Side"
    )


async def emd_task_list(ctx: WorkflowContext) -> StepResult:
    """EMD task list — buyer side, when the deposit is held at our agency."""
    if ctx.record.representation_side != "Buyer":
        return StepResult(
            status=StepStatus.SKIPPED,
            detail="listing side — other agency holds the deposit; tracked via deadline",
        )
    held_by = (ctx.record.entity_holding_emd or "").lower()
    if not held_by:
        return StepResult(
            status=StepStatus.WAITING,
            detail="EMD holder not yet known — clears once the P&S terms name one",
        )
    if "agency" not in held_by and "era" not in held_by:
        return StepResult(
            status=StepStatus.SKIPPED, detail=f"deposit held by {ctx.record.entity_holding_emd}"
        )
    return await common.add_task_list_step(ctx, template_name="Earnest Money Deposit")


async def mls_to_pending(ctx: WorkflowContext) -> StepResult:
    """Move the MLS listing to Pending (listing side)."""
    if ctx.record.representation_side == "Buyer":
        return StepResult(status=StepStatus.SKIPPED, detail="buyer side — no MLS listing")
    if not ctx.envelope.mls_listing_key:
        return StepResult(
            status=StepStatus.SKIPPED, detail="no MLS listing on this transaction"
        )
    from realtorai.integrations.spark.submission import update_listing_status

    ok, detail = update_listing_status(ctx.envelope.mls_listing_key, "Pending")
    if not ok:
        return StepResult(status=StepStatus.WAITING, detail=detail)
    ctx.record.listing_status = "Pending"
    return StepResult(detail=detail)


#: (record field, description, waiting_on) for the deadline board
_DEADLINES = (
    ("emd_due_date", "Earnest money deposit due", "client"),
    ("inspection_deadline", "Inspection deadline", "client"),
    ("financing_commitment_deadline", "Financing commitment deadline", "lender"),
    ("appraisal_deadline", "Appraisal deadline", "lender"),
    ("closing_date", "Closing", "title"),
)


async def track_deadlines(ctx: WorkflowContext) -> StepResult:
    """Create dated pending items so deadlines surface on the dashboard.

    Pending-item queries JOIN on the clients table, so the transaction needs
    a real client row — created here (status under_contract) if the envelope
    doesn't have one yet.
    """
    from realtorai.storage.database import get_database

    db = await get_database()
    client_id = ctx.envelope.client_id
    if client_id is None or await db.get_client(client_id) is None:
        client_id = await db.create_client(
            name=ctx.envelope.client_name
            or ctx.record.seller_1.name
            or ctx.envelope.slug,
            transaction_type="sell" if ctx.record.representation_side != "Buyer" else "buy",
            property_address=ctx.record.street_address,
            status="under_contract",
            room_id=ctx.record.docusign_room_id,
        )
        ctx.envelope.client_id = client_id
    existing = {
        item["description"]
        for item in await db.get_pending_items(client_id=client_id)
    }
    created = []
    for field, description, waiting_on in _DEADLINES:
        value = getattr(ctx.record, field)
        if value is None or description in existing:
            continue
        await db.create_pending_item(
            client_id=client_id,
            item_type="info",
            description=description,
            waiting_on=waiting_on,
            due_date=value.isoformat(),
        )
        created.append(f"{description} {value.isoformat()}")
    if not created:
        return StepResult(detail="no new dated deadlines (already tracked or unset)")
    return StepResult(detail="; ".join(created))


UC_STEPS: list[tuple[Step, object]] = [
    (
        Step(key="contract_terms", title="Extract contract terms from P&S (Sonnet)"),
        extract_contract_terms,
    ),
    (
        Step(key="verify_contract", title="Verify contract terms (Opus)"),
        common.verify_extraction,
    ),
    (Step(key="uc_task_list", title="Add Under Contract task list"), uc_task_list),
    (Step(key="emd_task_list", title="Add Earnest Money Deposit task list"), emd_task_list),
    (
        Step(key="file_contract", title="File signed contract to room"),
        common.upload_paperwork_step,
    ),
    (
        Step(key="transaction_worksheet", title="Fill Transaction Worksheet"),
        common.generate_tw_step,
    ),
    (Step(key="mls_pending", title="Move MLS listing to Pending"), mls_to_pending),
    (Step(key="deadlines", title="Track contract deadlines"), track_deadlines),
    (
        Step(key="refresh_master_doc", title="Update master information document"),
        common.render_master_doc,
    ),
]


async def start_under_contract_workflow(
    slug: str,
    *,
    documents: list[PaperworkDocument] | None = None,
    paperwork_files: list[tuple[str, bytes]] | None = None,
    contract_terms: dict | None = None,
) -> TransactionEnvelope:
    """Start (or resume) the under-contract phase on an existing transaction.

    `contract_terms` supplies prebuilt terms (demo/offline path); normally
    the extract step reads them from the attached P&S documents.
    """
    envelope = load_transaction(slug)
    if envelope is None:
        raise ValueError(f"No transaction '{slug}' — under contract is a phase "
                         "change on an existing deal")

    # A phase change archives the prior phase's timeline instead of losing it
    if envelope.workflow and envelope.workflow.get("name") != UC_WORKFLOW:
        envelope.workflow_history.append(envelope.workflow)
        envelope.workflow = None

    ctx = WorkflowContext(envelope, documents=documents, paperwork_files=paperwork_files)
    ctx.contract_terms = contract_terms
    await run_workflow(UC_WORKFLOW, UC_STEPS, ctx)
    logger.info(
        "under_contract_workflow_ran",
        slug=slug,
        status=(envelope.workflow or {}).get("status"),
    )
    return envelope
