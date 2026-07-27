"""Closing workflow: settlement statement -> reviewed, filed, deal closed.

The final phase change on an existing transaction. The settlement (closing)
statement from the closing company is the authoritative source for final
numbers, and the office rule is that the TEAM reviews it before closing —
so this workflow's review step goes WAITING (human review) whenever the
statement disagrees with the record instead of silently accepting either:

  1. Extract settlement terms (Sonnet, focused schema)
  2. Verify against the statement (Opus; critical issues BLOCK)
  3. Deterministic statement review — final price vs contract, negotiated
     concessions present, commission total sanity (WAITING on discrepancy)
  4. Add the Closing task list to the room
  5. File the settlement statement / closing docs
  6. Re-fill the Transaction Worksheet with final numbers
  7. Move the MLS listing to Closed (listing side)
  8. Close the room (roomStatus Closed + closedDate)
  9. Resolve open deadline items, mark the client closed
 10. Refresh the master information document
"""

from datetime import date
from decimal import Decimal

import structlog
from pydantic import BaseModel, Field

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.inference.model_router import LLMTask
from realtorai.integrations.docusign import rooms
from realtorai.schemas.transaction import TransactionRecord
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

CLOSING_WORKFLOW = "closing"


# ---------------------------------------------------------------------------
# Settlement-terms extraction (STANDARD tier)
# ---------------------------------------------------------------------------


class ClosingTerms(BaseModel):
    """What the settlement / closing statement actually says."""

    final_sale_price: Decimal | None = Field(
        default=None, description="Contract sales price on the statement"
    )
    closing_date: date | None = None
    seller_concession_on_statement: Decimal | None = Field(
        default=None,
        description="Seller credit/concession amount as it appears, if any",
    )
    total_commission: Decimal | None = Field(
        default=None, description="Total real estate commission on the statement"
    )
    comments: str | None = Field(
        default=None,
        description="Anything off: unexpected fees, missing credits, prorations",
    )


EXTRACT_CLOSING_SYSTEM = """You are a meticulous Maine real-estate transaction \
coordinator reading a settlement (closing) statement / Closing Disclosure.

Rules:
- Only extract what the statement actually shows; leave unknown fields null.
- seller_concession_on_statement is the seller credit to the buyer as listed —
  null if no such line appears.
- Note anything unusual (unexpected fees, missing negotiated credits, odd
  prorations) in comments."""


async def extract_closing_terms(ctx: WorkflowContext) -> StepResult:
    """Extract statement terms; stash them for the review step."""
    prebuilt = getattr(ctx, "closing_terms", None)
    if prebuilt is not None:
        terms = ClosingTerms.model_validate(prebuilt)
    elif not ctx.documents:
        return StepResult(
            status=StepStatus.BLOCKED,
            detail="no settlement statement attached — attach it and resume",
        )
    elif get_claude_engine().available:
        engine = get_claude_engine()
        terms = await engine.generate_structured(
            "Extract the settlement terms from this closing statement.\n\n"
            + _documents_block(ctx.documents),
            ClosingTerms,
            task=LLMTask.EXTRACT,
            system_prompt=EXTRACT_CLOSING_SYSTEM,
        )
    else:
        return StepResult(status=StepStatus.SKIPPED, detail=common.OFFLINE_NOTE)

    ctx.extracted_closing_terms = terms
    # Persist for the review step across resumes
    from realtorai.storage.transaction_store import artifacts_dir

    terms_path = artifacts_dir(ctx.envelope.slug) / "closing_statement_terms.json"
    terms_path.write_text(terms.model_dump_json(indent=2))
    ctx.add_artifact("Closing Statement Terms", str(terms_path), kind="report")
    applied = []
    if terms.final_sale_price is not None:
        ctx.record.final_sale_price = terms.final_sale_price
        applied.append("final_sale_price")
    if terms.closing_date is not None:
        ctx.record.closing_date = terms.closing_date
        applied.append("closing_date")
    if terms.comments:
        ctx.record.comments = (
            f"{ctx.record.comments}\n[Closing] {terms.comments}"
            if ctx.record.comments
            else f"[Closing] {terms.comments}"
        )
        applied.append("comments")
    return StepResult(detail=f"statement read — set {', '.join(applied) or 'nothing'}")


def review_statement_against_record(
    record: TransactionRecord, terms: ClosingTerms
) -> list[str]:
    """Deterministic cross-checks; returns human-readable discrepancies."""
    issues: list[str] = []
    if (
        terms.final_sale_price is not None
        and record.contract_amount is not None
        and terms.final_sale_price != record.contract_amount
    ):
        issues.append(
            f"statement price ${terms.final_sale_price} != contract "
            f"${record.contract_amount} (amendment? confirm)"
        )
    if record.seller_concession_amount:
        if terms.seller_concession_on_statement is None:
            issues.append(
                f"negotiated concession ${record.seller_concession_amount} "
                "does NOT appear on the statement"
            )
        elif terms.seller_concession_on_statement != record.seller_concession_amount:
            issues.append(
                f"concession on statement ${terms.seller_concession_on_statement} "
                f"!= negotiated ${record.seller_concession_amount}"
            )
    if (
        terms.total_commission is not None
        and terms.final_sale_price is not None
        and terms.total_commission > terms.final_sale_price * Decimal("0.10")
    ):
        issues.append(
            f"total commission ${terms.total_commission} exceeds 10% of the "
            "sale price — check the statement"
        )
    return issues


async def statement_review(ctx: WorkflowContext) -> StepResult:
    """The office rule: the team reviews the statement before closing."""
    terms = getattr(ctx, "extracted_closing_terms", None)
    if terms is None:
        # Resume path: reload the terms persisted by the extract step
        artifact = next(
            (a for a in ctx.envelope.artifacts if a.name == "Closing Statement Terms"),
            None,
        )
        if artifact is not None:
            from pathlib import Path

            terms = ClosingTerms.model_validate_json(Path(artifact.path).read_text())
    if terms is None:
        return StepResult(
            status=StepStatus.SKIPPED, detail="no extracted terms to review (offline)"
        )
    issues = review_statement_against_record(ctx.record, terms)
    if issues:
        return StepResult(
            status=StepStatus.WAITING,
            detail="team review needed: " + "; ".join(issues),
        )
    return StepResult(detail="statement matches the record — price and concessions check out")


# ---------------------------------------------------------------------------
# Phase steps
# ---------------------------------------------------------------------------


async def closing_task_list(ctx: WorkflowContext) -> StepResult:
    return await common.add_task_list_step(ctx, template_name="Closing")


async def mls_closed(ctx: WorkflowContext) -> StepResult:
    """Move the MLS listing to Closed (listing side)."""
    if ctx.record.representation_side == "Buyer":
        return StepResult(status=StepStatus.SKIPPED, detail="buyer side — no MLS listing")
    if not ctx.envelope.mls_listing_key:
        return StepResult(
            status=StepStatus.SKIPPED, detail="no MLS listing on this transaction"
        )
    from realtorai.integrations.spark.submission import update_listing_status

    ok, detail = update_listing_status(ctx.envelope.mls_listing_key, "Closed")
    if not ok:
        return StepResult(status=StepStatus.WAITING, detail=detail)
    ctx.record.listing_status = "Closed"
    return StepResult(detail=detail)


async def close_room_step(ctx: WorkflowContext) -> StepResult:
    room_id = ctx.record.docusign_room_id
    if room_id is None:
        return StepResult(status=StepStatus.SKIPPED, detail="no room on this transaction")
    closed = (ctx.record.closing_date or date.today()).isoformat()
    if not await rooms.close_room(room_id, closed_date=closed):
        raise RuntimeError("Room close failed — see logs")
    return StepResult(detail=f"room {room_id} closed ({closed})")


async def finalize_transaction(ctx: WorkflowContext) -> StepResult:
    """Resolve open deadline items and mark the client closed."""
    from realtorai.storage.database import get_database

    resolved = 0
    db = await get_database()
    if ctx.envelope.client_id is not None:
        for item in await db.get_pending_items(client_id=ctx.envelope.client_id):
            await db.resolve_pending_item(item["id"], status="received")
            resolved += 1
        if await db.get_client(ctx.envelope.client_id) is not None:
            await db.update_client(ctx.envelope.client_id, status="closed")
    if ctx.record.representation_side != "Buyer":
        ctx.record.listing_status = "Closed"
    return StepResult(detail=f"{resolved} open item(s) resolved; client marked closed")


CLOSING_STEPS: list[tuple[Step, object]] = [
    (
        Step(key="closing_terms", title="Extract settlement terms (Sonnet)"),
        extract_closing_terms,
    ),
    (
        Step(key="verify_statement", title="Verify against the statement (Opus)"),
        common.verify_extraction,
    ),
    (
        Step(key="statement_review", title="Review statement vs record (team rule)"),
        statement_review,
    ),
    (Step(key="closing_task_list", title="Add Closing task list"), closing_task_list),
    (
        Step(key="file_statement", title="File settlement statement to room"),
        common.upload_paperwork_step,
    ),
    (
        Step(key="transaction_worksheet", title="Update Transaction Worksheet"),
        common.generate_tw_step,
    ),
    (Step(key="mls_closed", title="Move MLS listing to Closed"), mls_closed),
    (Step(key="close_room", title="Close the room"), close_room_step),
    (
        Step(key="finalize", title="Resolve deadlines, mark client closed"),
        finalize_transaction,
    ),
    (
        Step(key="refresh_master_doc", title="Update master information document"),
        common.render_master_doc,
    ),
]


async def start_closing_workflow(
    slug: str,
    *,
    documents: list[PaperworkDocument] | None = None,
    paperwork_files: list[tuple[str, bytes]] | None = None,
    closing_terms: dict | None = None,
) -> TransactionEnvelope:
    """Start (or resume) the closing phase on an existing transaction."""
    envelope = load_transaction(slug)
    if envelope is None:
        raise ValueError(
            f"No transaction '{slug}' — closing is a phase change on an existing deal"
        )

    if envelope.workflow and envelope.workflow.get("name") != CLOSING_WORKFLOW:
        envelope.workflow_history.append(envelope.workflow)
        envelope.workflow = None

    ctx = WorkflowContext(envelope, documents=documents, paperwork_files=paperwork_files)
    ctx.closing_terms = closing_terms
    await run_workflow(CLOSING_WORKFLOW, CLOSING_STEPS, ctx)
    logger.info(
        "closing_workflow_ran",
        slug=slug,
        status=(envelope.workflow or {}).get("status"),
    )
    return envelope
