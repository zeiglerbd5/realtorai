"""Listing-side workflow: signed listing paperwork -> room + MLS draft.

Mirrors the intake process for a new listing client:

  1. Verify the extracted record against the paperwork (Opus review pass)
  2. Render the Master Information Document (internal — never filed to DTR)
  3. Create the DocuSign Transaction Room (list side, field data auto-filled)
  4. Add the "New Listing" task list from the Actions menu
  5. Attach + auto-fill the Exclusive Right to Sell and Brokerage Relationship
     forms; file the signed copies into the room
  6. Start the property disclosures (waits on the client — does not block)
  7. Create the draft MLS listing in Maine Listings (agent publishes in Flexmls)
  8. Pull tax map / tax card / flood map reference sheets into the room
  9. Review the deed for restrictions and rights of way (Opus)
 10. Re-render the master doc enriched with deed findings + supporting docs
"""

import zlib

import structlog

from realtorai.documents.master_info import write_master_info_document
from realtorai.inference.claude_engine import get_claude_engine
from realtorai.inference.model_router import LLMTask
from realtorai.integrations.public_records import build_supporting_documents, write_pull_sheets
from realtorai.integrations.spark.mls_feeder import get_mls_feeder, update_mls_feeder
from realtorai.integrations.spark.record_bridge import record_to_feeder_updates
from realtorai.integrations.spark.submission import create_draft_listing
from realtorai.schemas.transaction import TransactionRecord
from realtorai.storage.transaction_store import (
    TransactionEnvelope,
    artifacts_dir,
    load_transaction,
    slug_for,
)
from realtorai.workflows import common
from realtorai.workflows.deed_review import render_deed_review_markdown, review_deed
from realtorai.workflows.engine import (
    Step,
    StepResult,
    StepStatus,
    WorkflowContext,
    run_workflow,
)
from realtorai.workflows.intake import PaperworkDocument

logger = structlog.get_logger()

LISTING_WORKFLOW = "listing"


def _client_identity(ctx: WorkflowContext) -> tuple[int, str]:
    """Stable (client_id, name) for feeder storage when no DB client exists."""
    if ctx.envelope.client_id and ctx.envelope.client_name:
        return ctx.envelope.client_id, ctx.envelope.client_name
    name = (
        ctx.envelope.client_name
        or ctx.record.seller_1.name
        or ctx.envelope.slug
    )
    client_id = ctx.envelope.client_id or (zlib.crc32(ctx.envelope.slug.encode()) % 900000 + 100000)
    return client_id, name


# ---------------------------------------------------------------------------
# Listing-specific steps
# ---------------------------------------------------------------------------


async def start_disclosures(ctx: WorkflowContext) -> StepResult:
    """Attach the property disclosure (and lead paint if pre-1978) for the client.

    Marked WAITING — the client completes these on their own time. The engine
    keeps going (tax maps, MLS draft, deed review run in the meantime).
    """
    forms = ["Seller's Property Disclosure"]
    year_built = ctx.record.year_built
    if year_built is not None and year_built < 1978:
        forms.append("Lead Based Paint Hazard Disclosure")

    result = await common.attach_forms_step(ctx, form_names=forms)
    return StepResult(
        status=StepStatus.WAITING,
        detail=f"sent to client, awaiting completion — {result.detail}",
    )


def _fallback_remarks(record: TransactionRecord) -> str:
    """Deterministic public-remarks draft for offline mode."""
    bits = []
    if record.bedrooms is not None and record.bathrooms is not None:
        bits.append(f"{record.bedrooms} bed / {record.bathrooms} bath")
    if record.transaction_type:
        bits.append(record.transaction_type.lower())
    where = ", ".join(p for p in (record.street_address, record.city) if p)
    line = " ".join(bits) if bits else "property"
    out = f"{line.capitalize()} at {where}." if where else f"{line.capitalize()}."
    if record.square_footage is not None:
        out += f" {record.square_footage:,.0f} sq ft."
    if record.lot_size_acres is not None:
        out += f" {record.lot_size_acres} acre lot."
    out += " Draft description — agent to review before publishing."
    return out


async def create_mls_draft(ctx: WorkflowContext) -> StepResult:
    """Populate the MLS feeder from the record and create the draft listing."""
    record = ctx.record
    if record.representation_side and record.representation_side != "Listing":
        return StepResult(status=StepStatus.SKIPPED, detail="not a listing-side transaction")

    client_id, client_name = _client_identity(ctx)
    ctx.envelope.client_id, ctx.envelope.client_name = client_id, client_name

    update_mls_feeder(client_id, client_name, record_to_feeder_updates(record), source="workflow")

    # Public remarks: Claude draft when available, deterministic fallback offline
    feeder = get_mls_feeder(client_id, client_name) or {}
    if not (feeder.get("marketing") or {}).get("public_remarks"):
        engine = get_claude_engine()
        if engine.available:
            remarks = await engine.generate(
                "Write MLS public remarks (<= 900 characters, no fair-housing "
                "violations, no phone numbers) for this listing:\n\n"
                + record.model_dump_json(exclude_none=True, indent=2),
                task=LLMTask.DRAFT,
                max_tokens=2000,
            )
        else:
            remarks = _fallback_remarks(record)
        update_mls_feeder(
            client_id,
            client_name,
            {"marketing": {"public_remarks": remarks.strip()}},
            source="workflow",
        )

    result = await create_draft_listing(client_id, client_name, record=record)
    ctx.envelope.mls_listing_key = result["listing_key"]
    record.mls_number = str(result["listing_id"])

    from realtorai.schemas.mls_required import readiness

    filled, total, missing = readiness(record)
    detail = (
        f"draft MLS #{result['listing_id']} created — {filled}/{total} required "
        "fields ready"
    )
    if missing:
        preview = ", ".join(missing[:4]) + ("…" if len(missing) > 4 else "")
        detail += f"; TBD before save: {preview}"
    return StepResult(detail=detail)


def _one_line_address(record: TransactionRecord) -> str:
    state = (record.state or "").removeprefix("US-")
    return ", ".join(
        p
        for p in (
            record.street_address,
            record.city,
            f"{state} {record.zip}".strip() if (state or record.zip) else None,
        )
        if p
    )


async def pull_supporting_docs(ctx: WorkflowContext) -> StepResult:
    """Tax map / tax card / flood map — live pulls where wired, pull sheets otherwise.

    Flood is fully automated via FEMA NFHL (keyless government APIs); tax map
    and tax card still emit pull sheets until their fetchers land. Any live
    failure falls back to the pull sheet, so this step cannot fail offline.
    """
    from realtorai.config.settings import get_settings

    out_dir = artifacts_dir(ctx.envelope.slug) / "public_records"
    documents = build_supporting_documents(ctx.record)
    notes: list[str] = []

    enriched: list[str] = []
    if get_settings().public_records_live and ctx.record.street_address:
        from realtorai.integrations.fema_flood import fetch_flood_determination
        from realtorai.integrations.maine_parcels import fetch_tax_map
        from realtorai.workflows import enrichment

        try:
            determination, map_path, md_path = await fetch_flood_determination(
                _one_line_address(ctx.record), out_dir
            )
            documents = [d for d in documents if d.kind != "flood_map"]
            await common.upload_artifact(ctx, "Flood Map (pinned)", map_path, kind="map")
            await common.upload_artifact(ctx, "Flood Determination", md_path, kind="report")
            notes.append(f"flood: {determination.summary}")
            enriched += enrichment.enrich_from_flood(ctx.record, determination)
        except Exception as e:
            logger.warning("flood_live_fetch_failed", error=str(e))
            notes.append("flood: live fetch failed, pull sheet kept")

        try:
            parcel, tax_map_path, tax_md_path = await fetch_tax_map(
                ctx.record.street_address,
                ctx.record.town or ctx.record.city or "",
                out_dir,
                record_map_lot=ctx.record.map_lot or ctx.record.parcel_id,
            )
            documents = [d for d in documents if d.kind != "tax_map"]
            await common.upload_artifact(ctx, "Tax Map (pinned)", tax_map_path, kind="map")
            await common.upload_artifact(ctx, "Tax Map Details", tax_md_path, kind="report")
            notes.append(f"tax map: {parcel.summary}")
            enriched += enrichment.enrich_from_parcel(ctx.record, parcel)
        except Exception as e:
            logger.warning("tax_map_live_fetch_failed", error=str(e))
            notes.append("tax map: live fetch failed, pull sheet kept")

        from realtorai.integrations.vgsi_tax_card import fetch_tax_card

        try:
            card, card_html_path, card_md_path = await fetch_tax_card(
                ctx.record.street_address,
                ctx.record.town or ctx.record.city or "",
                out_dir,
                record_assessed=ctx.record.assessed_value,
                record_map_lot=ctx.record.map_lot or ctx.record.parcel_id,
                record_deed_book=ctx.record.deed_book,
                record_deed_page=ctx.record.deed_page,
                record_year_built=ctx.record.year_built,
            )
            documents = [d for d in documents if d.kind != "tax_card"]
            await common.upload_artifact(ctx, "Tax Card (VGSI)", card_html_path, kind="document")
            await common.upload_artifact(ctx, "Tax Card Report", card_md_path, kind="report")
            notes.append(f"tax card: {card.summary}")
            enriched += enrichment.enrich_from_tax_card(ctx.record, card)
        except Exception as e:
            logger.warning("tax_card_live_fetch_failed", error=str(e))
            notes.append("tax card: live fetch failed, pull sheet kept")

    if enriched:
        notes.append(f"record auto-filled: {', '.join(sorted(set(enriched)))}")

    documents = write_pull_sheets(documents, ctx.record, out_dir)
    uploaded = 0
    for doc in documents:
        if doc.artifact_path:
            from pathlib import Path

            ok = await common.upload_artifact(
                ctx, doc.name, Path(doc.artifact_path), kind="map"
            )
            uploaded += 1 if ok else 0

    detail = f"{len(documents)} pull sheets, {uploaded} filed to room"
    if notes:
        detail += "; " + "; ".join(notes)
    return StepResult(detail=detail)


def _first_page(deed_page: str) -> str:
    """'156-157' -> '156' (registries index the first page of the range)."""
    import re as _re

    match = _re.match(r"\d+", deed_page or "")
    return match.group(0) if match else deed_page


async def fetch_deed_step(ctx: WorkflowContext) -> StepResult:
    """Pull the recorded deed from the county registry by book/page."""
    record = ctx.record
    if not (record.deed_book and record.deed_page):
        return StepResult(status=StepStatus.SKIPPED, detail="no deed book/page on record")
    from realtorai.config.settings import get_settings

    if not get_settings().public_records_live:
        return StepResult(status=StepStatus.SKIPPED, detail="public records live fetch disabled")

    from realtorai.integrations.registry import fetch_deed, registry_for

    if registry_for(record.county) is None:
        return StepResult(
            status=StepStatus.SKIPPED,
            detail=f"no registry adapter for {record.county or 'unknown'} County yet",
        )

    out_dir = artifacts_dir(ctx.envelope.slug) / "public_records"
    deed_record, pdf_path, md_path = await fetch_deed(
        record.county,
        record.deed_book,
        _first_page(record.deed_page),
        out_dir,
        expect_town=record.town or record.city,
        expect_owner=record.seller_1.name,
    )
    await common.upload_artifact(ctx, "Recorded Deed (registry copy)", pdf_path, kind="document")
    await common.upload_artifact(ctx, "Deed Index Report", md_path, kind="report")

    from realtorai.workflows import enrichment

    filled = enrichment.enrich_from_deed(ctx.record, deed_record)
    detail = deed_record.summary
    if filled:
        detail += f"; record auto-filled: {', '.join(filled)}"
    return StepResult(detail=detail)


def _fetched_deed_pdf(ctx: WorkflowContext) -> bytes | None:
    """The registry-pulled deed PDF, if the fetch step produced one."""
    records_dir = artifacts_dir(ctx.envelope.slug) / "public_records"
    pdfs = sorted(records_dir.glob("deed_bk*.pdf"))
    return pdfs[0].read_bytes() if pdfs else None


async def deed_review_step(ctx: WorkflowContext) -> StepResult:
    """Opus pass over the deed for restrictions / rights of way.

    Prefers the registry-pulled PDF (Claude reads the scan directly);
    falls back to deed text from the intake paperwork.
    """
    engine = get_claude_engine()
    if not engine.available:
        return StepResult(status=StepStatus.SKIPPED, detail=common.OFFLINE_NOTE)

    label = ctx.record.street_address or ctx.envelope.slug
    deed_pdf = _fetched_deed_pdf(ctx)
    if deed_pdf is not None:
        report = await review_deed(property_label=label, deed_pdf=deed_pdf)
    else:
        deed_doc = next((d for d in ctx.documents if "deed" in d.name.lower()), None)
        if deed_doc is None:
            return StepResult(status=StepStatus.SKIPPED, detail="no deed document available")
        report = await review_deed(deed_doc.text, property_label=label)

    out_dir = artifacts_dir(ctx.envelope.slug)
    json_path = out_dir / "deed_review.json"
    json_path.write_text(report.model_dump_json(indent=2))
    md_path = out_dir / "deed_review.md"
    md_path.write_text(render_deed_review_markdown(report, property_label=label))
    await common.upload_artifact(ctx, "Deed Review", md_path, kind="report")

    flagged = sum(1 for f in report.findings if f.severity != "info")
    return StepResult(
        detail=f"{len(report.findings)} finding(s), {flagged} flagged"
        + (" — OUT OF THE ORDINARY, review with agent" if report.out_of_ordinary else "")
    )


def _flood_note(ctx: WorkflowContext) -> str | None:
    """Summary line from a live flood determination, if one was fetched."""
    import json

    path = artifacts_dir(ctx.envelope.slug) / "public_records" / "flood_determination.json"
    if not path.exists():
        return None
    try:
        from realtorai.integrations.fema_flood import FloodDetermination

        return FloodDetermination.model_validate(json.loads(path.read_text())).summary
    except Exception:
        return None


async def generate_mis_step(ctx: WorkflowContext) -> StepResult:
    """Fill the agency team Master Information Sheet (89-field fillable PDF).

    Runs LAST so it captures everything the workflow learned — including
    flood zone / SFHA / panel, assessment year, and deed facts auto-filled
    from the public-records pulls. Internal team reference; not filed to
    the room by default.
    """
    from realtorai.config.settings import get_settings
    from realtorai.documents.mis_filler import fill_master_information_sheet, mis_field_values

    template = get_settings().mis_template_path
    if not template.exists():
        return StepResult(
            status=StepStatus.SKIPPED,
            detail=f"MIS template not found at {template} (internal form — not in repo)",
        )
    out_path = artifacts_dir(ctx.envelope.slug) / "Master Information Sheet - prefilled.pdf"
    fill_master_information_sheet(ctx.record, template, out_path)
    ctx.add_artifact("Master Information Sheet (Agency)", str(out_path), kind="document")
    return StepResult(detail=f"{len(mis_field_values(ctx.record))} of 89 fields filled")


async def finalize_master_doc(ctx: WorkflowContext) -> StepResult:
    """Re-render the master doc enriched with everything the workflow learned."""
    out_dir = artifacts_dir(ctx.envelope.slug)
    supporting = [d.model_dump() for d in build_supporting_documents(ctx.record)]
    flood_note = _flood_note(ctx)
    if flood_note:
        for doc in supporting:
            if doc["kind"] == "flood_map":
                doc["name"] = f"Flood Determination — {flood_note}"
                doc["source_label"] = "FEMA NFHL (live)"
    path = write_master_info_document(
        ctx.record,
        out_dir,
        deed_findings=common.load_deed_findings(ctx),
        supporting_documents=supporting,
        verification_notes=common._load_verification_notes(ctx),
    )
    ctx.add_artifact("Master Information Document", str(path), kind="document")
    return StepResult(detail="master doc updated with deed + records findings")


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

LISTING_STEPS: list[tuple[Step, object]] = [
    (
        Step(key="verify_extraction", title="Verify paperwork extraction (Opus)"),
        common.verify_extraction,
    ),
    (
        Step(key="master_doc", title="Generate Master Information Document"),
        common.render_master_doc,
    ),
    (
        Step(key="create_room", title="Create DocuSign Transaction Room (list side)"),
        lambda ctx: common.create_room_step(ctx, transaction_side_id="sell"),
    ),
    (
        Step(key="task_list", title="Add “New Listing” task list"),
        lambda ctx: common.add_task_list_step(ctx, template_name="New Listing"),
    ),
    (
        Step(key="agency_forms", title="Attach + auto-fill listing agreement forms"),
        lambda ctx: common.attach_forms_step(
            ctx,
            form_names=[
                "Exclusive Right to Sell Listing Agreement",
                "Brokerage Relationship Form",
            ],
        ),
    ),
    (
        Step(key="file_paperwork", title="File signed paperwork to room"),
        common.upload_paperwork_step,
    ),
    (Step(key="disclosures", title="Start property disclosures"), start_disclosures),
    (Step(key="mls_draft", title="Create draft MLS listing"), create_mls_draft),
    (Step(key="public_records", title="Pull tax map / tax card / flood map"), pull_supporting_docs),
    (Step(key="fetch_deed", title="Pull recorded deed from county registry"), fetch_deed_step),
    (Step(key="deed_review", title="Review deed for restrictions & ROWs (Opus)"), deed_review_step),
    (Step(key="finalize_master_doc", title="Update master doc with findings"), finalize_master_doc),
    (
        Step(key="master_info_sheet", title="Fill Agency Master Information Sheet"),
        generate_mis_step,
    ),
]


async def start_listing_workflow(
    record: TransactionRecord,
    *,
    documents: list[PaperworkDocument] | None = None,
    paperwork_files: list[tuple[str, bytes]] | None = None,
    client_id: int | None = None,
    client_name: str | None = None,
) -> TransactionEnvelope:
    """Start (or resume) the listing workflow for a record."""
    record.representation_side = record.representation_side or "Listing"
    slug = slug_for(record)
    envelope = load_transaction(slug) or TransactionEnvelope(slug=slug, record=record)
    envelope.client_id = client_id or envelope.client_id
    envelope.client_name = client_name or envelope.client_name

    ctx = WorkflowContext(envelope, documents=documents, paperwork_files=paperwork_files)
    await run_workflow(LISTING_WORKFLOW, LISTING_STEPS, ctx)
    return envelope
