"""Transaction workflow routes — DTR rooms, MLS drafts, workflow timelines."""

from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from realtorai.config.settings import get_settings
from realtorai.integrations.docusign import rooms
from realtorai.storage.transaction_store import list_transactions, load_transaction

logger = structlog.get_logger()

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

from fastapi.templating import Jinja2Templates  # noqa: E402

templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def transactions_list(request: Request) -> HTMLResponse:
    """All transactions with workflow status."""
    settings = get_settings()
    envelopes = list_transactions()
    items = []
    for envelope in envelopes:
        workflow = envelope.workflow or {}
        steps = workflow.get("steps", [])
        items.append(
            {
                "slug": envelope.slug,
                "title": envelope.record.street_address
                or envelope.client_name
                or envelope.slug,
                "city": envelope.record.city,
                "side": envelope.record.representation_side,
                "status": workflow.get("status", "not started"),
                "steps_done": sum(1 for s in steps if s["status"] in ("done", "skipped")),
                "steps_total": len(steps),
                "room_id": envelope.record.docusign_room_id,
                "mls_listing_key": envelope.mls_listing_key,
                "updated_at": envelope.updated_at,
            }
        )
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "transactions": items,
            "docusign_backend": settings.docusign_backend,
            "mls_backend": settings.mls_backend,
        },
    )


@router.get("/{slug}", response_class=HTMLResponse)
async def transaction_detail(request: Request, slug: str) -> HTMLResponse:
    """One transaction: workflow timeline, room contents, MLS status, artifacts."""
    envelope = load_transaction(slug)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    room_id = envelope.record.docusign_room_id
    room = None
    task_lists: list = []
    forms: list = []
    documents: list = []
    if room_id is not None:
        room = await rooms.get_room(room_id)
        if room:
            task_lists = await rooms.get_room_task_lists(room_id)
            forms = await rooms.get_room_forms(room_id)
            documents = await rooms.get_room_documents(room_id)

    mls_status = None
    if envelope.mls_listing_key:
        from realtorai.integrations.spark.submission import get_listing_status

        mls_status = await get_listing_status(envelope.mls_listing_key)

    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "transaction_detail.html",
        {
            "envelope": envelope,
            "record": envelope.record,
            "workflow": envelope.workflow or {},
            "room": room,
            "task_lists": task_lists,
            "forms": forms,
            "documents": documents,
            "mls_status": mls_status,
            "docusign_backend": settings.docusign_backend,
        },
    )


@router.post("/demo/listing")
async def run_listing_demo() -> RedirectResponse:
    """Kick off the reference listing workflow (22 Penobscot St fixture)."""
    from realtorai.fixtures import build_22_penobscot
    from realtorai.workflows.listing import start_listing_workflow

    envelope = await start_listing_workflow(build_22_penobscot(), client_name="Brett Zeigler")
    return RedirectResponse(url=f"/transactions/{envelope.slug}", status_code=303)


@router.post("/{slug}/resume")
async def resume_workflow(slug: str) -> RedirectResponse:
    """Re-run a workflow: retries failed steps, re-checks waiting steps."""
    envelope = load_transaction(slug)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    workflow_name = (envelope.workflow or {}).get("name")
    if workflow_name == "buyer":
        from realtorai.workflows.buyer import start_buyer_workflow

        await start_buyer_workflow(envelope.record)
    else:
        from realtorai.workflows.listing import start_listing_workflow

        await start_listing_workflow(envelope.record)
    return RedirectResponse(url=f"/transactions/{slug}", status_code=303)
