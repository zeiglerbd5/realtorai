"""Steps shared between the listing and buyer workflows."""

import json
from pathlib import Path

import structlog

from realtorai.documents.master_info import write_master_info_document
from realtorai.inference.claude_engine import get_claude_engine
from realtorai.integrations.docusign import rooms
from realtorai.integrations.docusign.field_mapper import to_room_field_data
from realtorai.storage.transaction_store import artifacts_dir
from realtorai.workflows.engine import StepResult, StepStatus, WorkflowContext
from realtorai.workflows.intake import verify_transaction_record

logger = structlog.get_logger()

OFFLINE_NOTE = "skipped — no ANTHROPIC_API_KEY configured (offline mode)"


# ---------------------------------------------------------------------------
# Paperwork verification (REVIEW tier)
# ---------------------------------------------------------------------------


async def verify_extraction(ctx: WorkflowContext) -> StepResult:
    """Second-model audit of the extracted record against source paperwork."""
    engine = get_claude_engine()
    if not engine.available:
        return StepResult(status=StepStatus.SKIPPED, detail=OFFLINE_NOTE)
    if not ctx.documents:
        return StepResult(status=StepStatus.SKIPPED, detail="no source documents to verify against")

    report = await verify_transaction_record(ctx.record, ctx.documents)

    out_dir = artifacts_dir(ctx.envelope.slug)
    report_path = out_dir / "verification_report.json"
    report_path.write_text(report.model_dump_json(indent=2))
    ctx.add_artifact("Verification Report", str(report_path), kind="report")

    criticals = [i for i in report.issues if i.severity == "critical"]
    if not report.safe_to_proceed or criticals:
        # BLOCKED halts the workflow: no room, no forms, no MLS draft on data
        # that failed the audit. Re-runs (and re-verifies) on resume.
        return StepResult(
            status=StepStatus.BLOCKED,
            detail=f"{len(criticals)} critical issue(s) — human review required; "
            "downstream steps held",
        )
    return StepResult(detail=f"verified — {len(report.issues)} minor issue(s) noted")


# ---------------------------------------------------------------------------
# Master information document
# ---------------------------------------------------------------------------


async def render_master_doc(ctx: WorkflowContext) -> StepResult:
    """Write the internal Master Information Document (never filed to the room)."""
    out_dir = artifacts_dir(ctx.envelope.slug)
    verification_notes = _load_verification_notes(ctx)
    path = write_master_info_document(
        ctx.record, out_dir, verification_notes=verification_notes
    )
    ctx.add_artifact("Master Information Document", str(path), kind="document")
    return StepResult(detail=path.name)


def _load_verification_notes(ctx: WorkflowContext) -> list[str] | None:
    report_path = artifacts_dir(ctx.envelope.slug) / "verification_report.json"
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text())
        return [
            f"[{i['severity']}] {i['field']}: {i['issue']}" for i in data.get("issues", [])
        ] or None
    except Exception:
        return None


def load_deed_findings(ctx: WorkflowContext) -> list[dict] | None:
    report_path = artifacts_dir(ctx.envelope.slug) / "deed_review.json"
    if not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text()).get("findings") or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Room setup
# ---------------------------------------------------------------------------


async def _agent_role_id() -> int:
    roles = await rooms.get_roles()
    for role in roles:
        if role.get("isDefaultForAgent") or role.get("name") == "Agent":
            return role["roleId"]
    return roles[0]["roleId"] if roles else 2


async def _default_office_id() -> int | None:
    offices = await rooms.get_offices()
    return offices[0]["officeId"] if offices else None


async def create_room_step(ctx: WorkflowContext, *, transaction_side_id: str) -> StepResult:
    """Create the DocuSign Transaction Room and write the record's field data."""
    record = ctx.record
    if record.docusign_room_id is not None:
        return StepResult(detail=f"room {record.docusign_room_id} already exists")

    name = record.street_address and f"{record.street_address}, {record.city or ''}".rstrip(", ")
    if not name:
        name = f"{ctx.envelope.client_name or 'New Client'} — Buyer Representation"

    room = await rooms.create_room(
        name=name,
        role_id=await _agent_role_id(),
        transaction_side_id=transaction_side_id,
        office_id=await _default_office_id(),
        field_data=to_room_field_data(record),
    )
    if not room:
        raise RuntimeError("Room creation failed — see logs")

    record.docusign_room_id = room["roomId"]
    return StepResult(detail=f"room {room['roomId']} — “{room['name']}”")


async def add_task_list_step(ctx: WorkflowContext, *, template_name: str) -> StepResult:
    """Add a task list from the Actions menu templates by name."""
    room_id = _require_room(ctx)

    existing = await rooms.get_room_task_lists(room_id)
    for task_list in existing:
        if task_list.get("name") == template_name:
            return StepResult(detail=f"“{template_name}” already on room")

    templates = await rooms.get_task_list_templates()
    template = next((t for t in templates if t.get("name") == template_name), None)
    if template is None:
        raise RuntimeError(f"Task list template “{template_name}” not found")

    task_list = await rooms.add_task_list_to_room(room_id, template["taskListTemplateId"])
    if not task_list:
        raise RuntimeError("Task list creation failed")
    return StepResult(
        detail=f"“{template_name}” added ({len(task_list.get('tasks', []))} tasks)"
    )


def _require_room(ctx: WorkflowContext) -> int:
    room_id = ctx.record.docusign_room_id
    if room_id is None:
        raise RuntimeError("No room on record — create_room step must run first")
    return room_id


# ---------------------------------------------------------------------------
# Forms & paperwork filing
# ---------------------------------------------------------------------------


async def find_form_id(name_fragment: str) -> str | None:
    """Locate a library form by (case-insensitive) name fragment."""
    for library in await rooms.get_form_libraries():
        forms = await rooms.get_form_library_forms(library["formsLibraryId"])
        for form in forms:
            if name_fragment.lower() in form.get("name", "").lower():
                return form.get("libraryFormId")
    return None


async def attach_forms_step(ctx: WorkflowContext, *, form_names: list[str]) -> StepResult:
    """Add library forms to the room; they auto-fill from the room field data.

    Field data was written at room creation (and can be re-synced any time via
    update_room_field_data), so "fill out the template from the master
    information document" is exactly this: field data in, form attached.
    """
    room_id = _require_room(ctx)

    # Keep room field data current with the record before attaching
    await rooms.update_room_field_data(room_id, to_room_field_data(ctx.record))

    existing = {f.get("name") for f in await rooms.get_room_forms(room_id)}
    details = []
    for name in form_names:
        form_id = await find_form_id(name)
        if form_id is None:
            details.append(f"{name}: NOT FOUND in form libraries")
            continue
        already = next((n for n in existing if name.lower() in (n or "").lower()), None)
        if already:
            details.append(f"{already}: already attached")
            continue
        instance = await rooms.add_form_to_room(room_id, form_id)
        if instance:
            details.append(
                f"{instance['name']}: {instance.get('prefilledFieldCount', '?')}"
                f"/{instance.get('expectedFieldCount', '?')} fields auto-filled"
            )
    return StepResult(detail="; ".join(details))


async def upload_paperwork_step(ctx: WorkflowContext) -> StepResult:
    """File the signed intake paperwork into the room."""
    if not ctx.paperwork_files:
        return StepResult(status=StepStatus.SKIPPED, detail="no signed paperwork files provided")
    room_id = _require_room(ctx)

    existing = {d.get("name") for d in await rooms.get_room_documents(room_id)}
    uploaded = 0
    for file_name, content in ctx.paperwork_files:
        if file_name in existing:
            continue
        doc = await rooms.upload_document_to_room(room_id, file_name, content)
        if doc:
            uploaded += 1
    return StepResult(detail=f"{uploaded} document(s) filed to room {room_id}")


async def upload_artifact(ctx: WorkflowContext, name: str, path: Path, kind: str) -> bool:
    """Upload a generated artifact file into the room."""
    room_id = _require_room(ctx)
    doc = await rooms.upload_document_to_room(room_id, path.name, path.read_bytes())
    ctx.add_artifact(name, str(path), kind=kind, uploaded=doc is not None)
    return doc is not None


# ---------------------------------------------------------------------------
# Transaction Worksheet
# ---------------------------------------------------------------------------


async def generate_tw_step(ctx: WorkflowContext) -> StepResult:
    """Fill the Transaction Worksheet from the record (deterministic pypdf).

    UNDER-CONTRACT phase, not intake: the TW is the agency office staff's
    reference sheet and joins the room with the "Under Contract" task list
    once a deal goes under contract. It's generated output — a convenience
    snapshot of the record — never a source of truth. This step belongs to
    the future under-contract workflow; until then, fill on demand with
    `scripts/fill_tw.py <slug>`.
    """
    from realtorai.config.settings import get_settings
    from realtorai.documents.tw_filler import fill_transaction_worksheet, tw_field_values

    template = get_settings().tw_template_path
    if not template.exists():
        return StepResult(
            status=StepStatus.SKIPPED,
            detail=f"TW template not found at {template} (internal form — not in repo)",
        )

    out_path = artifacts_dir(ctx.envelope.slug) / "Transaction Worksheet - prefilled.pdf"
    fill_transaction_worksheet(ctx.record, template, out_path)
    filled = sum(1 for v in tw_field_values(ctx.record).values() if v not in ("", "/Off"))
    await upload_artifact(ctx, "Transaction Worksheet (prefilled)", out_path, kind="document")
    return StepResult(detail=f"{filled} fields filled from record — filed to room")
