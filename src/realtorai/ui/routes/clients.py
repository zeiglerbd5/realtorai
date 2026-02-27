"""Client and pending items API routes."""

from pathlib import Path

import markdown
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from realtorai.storage.database import get_database
from realtorai.storage.client_files import (
    read_client_file,
    write_client_file,
    append_note,
)
from realtorai.integrations.matterport.downloader import (
    get_client_matterport_dir,
    get_tour_info,
)
from realtorai.integrations.spark.mls_feeder import (
    get_mls_feeder,
    get_feeder_completeness,
    update_mls_feeder,
    create_mls_feeder,
)
from realtorai.transactions import (
    get_transaction,
    create_transaction,
    update_transaction,
    get_transaction_progress,
    set_milestone,
    mark_document_received,
)

router = APIRouter()

# Templates
UI_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=UI_DIR / "templates")


class ClientCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    transaction_type: str | None = None
    property_address: str | None = None
    price: float | None = None


class ClientUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    transaction_type: str | None = None
    property_address: str | None = None
    price: float | None = None
    status: str | None = None
    room_id: int | None = None


class NoteCreate(BaseModel):
    content: str
    source: str = "agent"


class FileUpdate(BaseModel):
    content: str


def render_markdown(content: str) -> str:
    """Convert markdown to HTML."""
    return markdown.markdown(
        content,
        extensions=["tables", "fenced_code", "nl2br"],
    )


# =============================================================================
# Client endpoints
# =============================================================================


@router.get("", response_class=HTMLResponse)
async def list_clients_page(request: Request, status: str | None = None) -> HTMLResponse:
    """List all clients (HTML page)."""
    db = await get_database()
    clients = await db.get_clients(status=status, limit=100)

    return templates.TemplateResponse(
        "clients_list.html",
        {
            "request": request,
            "clients": clients,
            "status_filter": status,
        },
    )


@router.get("/api", response_model=list[dict])
async def list_clients_api(status: str | None = None, limit: int = 100) -> list[dict]:
    """List all clients (JSON API)."""
    db = await get_database()
    return await db.get_clients(status=status, limit=limit)


@router.post("", response_model=None)
async def create_client(request: Request, client: ClientCreate):
    """Create a new client."""
    db = await get_database()
    client_id = await db.create_client(**client.model_dump())

    # If HTMX request, redirect to client detail page
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content="",
            status_code=200,
            headers={"HX-Redirect": f"/clients/{client_id}"}
        )

    return await db.get_client(client_id)


@router.get("/{client_id}", response_class=HTMLResponse)
async def get_client_detail(request: Request, client_id: int) -> HTMLResponse:
    """Get client detail page (HTML)."""
    db = await get_database()

    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Read markdown file
    content_raw = read_client_file(client_id, client["name"]) or ""
    content_html = render_markdown(content_raw)

    # Get pending items
    pending_items = await db.get_pending_items(client_id=client_id, status="waiting")

    # Get Matterport tour info if available
    matterport_info = get_tour_info(client_id, client["name"])
    matterport_images = []
    if matterport_info:
        stills_dir = get_client_matterport_dir(client_id, client["name"]) / "stills"
        if stills_dir.exists():
            matterport_images = sorted([
                f"/clients/{client_id}/matterport/stills/{f.name}"
                for f in stills_dir.iterdir()
                if f.suffix.lower() in ('.jpg', '.jpeg', '.png')
            ])

    # Get MLS feeder status if available
    mls_feeder = get_mls_feeder(client_id, client["name"])
    mls_completeness = None
    if mls_feeder:
        mls_completeness = get_feeder_completeness(mls_feeder)

    # Get transaction tracker if available
    transaction = get_transaction(client_id, client["name"])
    transaction_progress = None
    if transaction:
        transaction_progress = get_transaction_progress(transaction)

    return templates.TemplateResponse(
        "client_detail.html",
        {
            "request": request,
            "client": client,
            "content_raw": content_raw,
            "content_html": content_html,
            "pending_items": pending_items,
            "matterport": matterport_info,
            "matterport_images": matterport_images,
            "mls_feeder": mls_feeder,
            "mls_completeness": mls_completeness,
            "transaction": transaction,
            "transaction_progress": transaction_progress,
        },
    )


@router.get("/{client_id}/json", response_model=dict)
async def get_client_json(client_id: int) -> dict:
    """Get client data as JSON."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.patch("/{client_id}", response_model=dict)
async def update_client(client_id: int, updates: ClientUpdate) -> dict:
    """Update a client."""
    db = await get_database()

    # Only include non-None values
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    if update_data:
        await db.update_client(client_id, **update_data)

    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.post("/{client_id}/archive")
async def archive_client(client_id: int) -> HTMLResponse:
    """Archive a client (soft delete)."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    await db.update_client(client_id, status="archived")

    return HTMLResponse(
        content="",
        status_code=200,
        headers={"HX-Redirect": "/clients"}
    )


@router.get("/{client_id}/notes", response_model=list[dict])
async def get_client_notes(client_id: int, limit: int = 50) -> list[dict]:
    """Get notes for a client."""
    db = await get_database()
    return await db.get_client_notes(client_id, limit=limit)


@router.post("/{client_id}/notes", response_model=dict)
async def add_client_note(client_id: int, note: NoteCreate) -> dict:
    """Add a note to a client."""
    db = await get_database()
    note_id = await db.add_client_note(
        client_id=client_id,
        content=note.content,
        source=note.source,
    )
    notes = await db.get_client_notes(client_id, limit=1)
    return notes[0] if notes else {"id": note_id}


@router.get("/{client_id}/file")
async def get_client_file(client_id: int) -> dict:
    """Get client's markdown file content."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    content = read_client_file(client_id, client["name"])
    if content is None:
        raise HTTPException(status_code=404, detail="Client file not found")

    return {
        "content": content,
        "file_path": client["file_path"],
    }


@router.put("/{client_id}/file")
async def update_client_file(client_id: int, update: FileUpdate) -> dict:
    """Update client's markdown file content."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    success = write_client_file(client_id, client["name"], update.content)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to write file")

    # Return rendered HTML for live update
    return {
        "success": True,
        "html": render_markdown(update.content),
    }


@router.get("/search/{query}", response_model=list[dict])
async def search_clients(query: str, limit: int = 20) -> list[dict]:
    """Search clients by name, email, or address."""
    db = await get_database()
    return await db.search_clients(query, limit=limit)


# =============================================================================
# Matterport endpoints
# =============================================================================


@router.get("/{client_id}/matterport")
async def get_client_matterport(client_id: int) -> dict:
    """Get Matterport tour info for a client."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    tour_info = get_tour_info(client_id, client["name"])
    if not tour_info:
        return {"has_tour": False}

    # Get image list
    stills_dir = get_client_matterport_dir(client_id, client["name"]) / "stills"
    images = []
    if stills_dir.exists():
        images = sorted([f.name for f in stills_dir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png')])

    return {
        "has_tour": True,
        "tour_info": tour_info,
        "images": images,
        "image_count": len(images),
    }


@router.get("/{client_id}/matterport/stills/{filename}")
async def get_matterport_still(client_id: int, filename: str):
    """Serve a Matterport still image."""
    from fastapi.responses import FileResponse

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    stills_dir = get_client_matterport_dir(client_id, client["name"]) / "stills"
    file_path = stills_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(file_path)


class MatterportDownload(BaseModel):
    model_id: str
    max_images: int = 40


class MLSFeederUpdate(BaseModel):
    address: dict | None = None
    property: dict | None = None
    listing: dict | None = None
    marketing: dict | None = None
    financial: dict | None = None
    features: dict | None = None
    media: dict | None = None


@router.post("/{client_id}/matterport/download")
async def download_matterport_tour(client_id: int, request: MatterportDownload) -> dict:
    """Download a Matterport tour for a client."""
    from realtorai.integrations.matterport import matterport_auth, download_tour_assets

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if not await matterport_auth.is_connected():
        raise HTTPException(status_code=503, detail="Matterport not connected")

    result = await download_tour_assets(
        client_id=client_id,
        client_name=client["name"],
        model_id=request.model_id,
        max_images=request.max_images,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


# =============================================================================
# MLS Feeder endpoints
# =============================================================================


@router.get("/{client_id}/mls-feeder")
async def get_client_mls_feeder(client_id: int) -> dict:
    """Get MLS feeder data for a client."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    feeder = get_mls_feeder(client_id, client["name"])
    if not feeder:
        return {"has_feeder": False}

    return {
        "has_feeder": True,
        "feeder": feeder,
        "completeness": get_feeder_completeness(feeder),
    }


@router.patch("/{client_id}/mls-feeder")
async def update_client_mls_feeder(client_id: int, updates: MLSFeederUpdate) -> dict:
    """Update MLS feeder data for a client."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Check if feeder exists, create if not
    feeder = get_mls_feeder(client_id, client["name"])
    if not feeder:
        feeder = create_mls_feeder(client_id, client["name"])

    # Build update dict from non-None fields
    update_data = {}
    for field in ["address", "property", "listing", "marketing", "financial", "features", "media"]:
        value = getattr(updates, field, None)
        if value is not None:
            # Filter out None values within the nested dict
            filtered = {k: v for k, v in value.items() if v is not None}
            if filtered:
                update_data[field] = filtered

    if update_data:
        feeder = update_mls_feeder(
            client_id=client_id,
            name=client["name"],
            updates=update_data,
            source="agent",
        )

    return {
        "success": True,
        "feeder": feeder,
        "completeness": get_feeder_completeness(feeder),
    }


@router.post("/{client_id}/mls-feeder/create")
async def create_client_mls_feeder(client_id: int) -> dict:
    """Create a new MLS feeder for a client."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    existing = get_mls_feeder(client_id, client["name"])
    if existing:
        return {"created": False, "message": "Feeder already exists", "feeder": existing}

    feeder = create_mls_feeder(client_id, client["name"])
    return {
        "created": True,
        "feeder": feeder,
        "completeness": get_feeder_completeness(feeder),
    }


@router.post("/{client_id}/mls-feeder/validate")
async def validate_mls_feeder(client_id: int) -> dict:
    """Validate MLS feeder before submission."""
    from realtorai.integrations.spark.submission import validate_feeder_for_submission

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    is_valid, errors = await validate_feeder_for_submission(client_id, client["name"])

    return {
        "valid": is_valid,
        "errors": errors,
    }


@router.post("/{client_id}/mls-feeder/submit")
async def submit_mls_listing(client_id: int) -> dict:
    """Submit MLS feeder to FlexMLS as a draft listing.

    Creates the listing and uploads photos. Agent must review
    and publish in FlexMLS interface.
    """
    from realtorai.integrations.spark import (
        spark_auth,
        submit_listing_with_photos,
        ListingSubmissionError,
    )

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Check Spark API connection
    if not await spark_auth.is_connected():
        raise HTTPException(
            status_code=503,
            detail="Spark API not connected. Configure credentials and authenticate.",
        )

    try:
        result = await submit_listing_with_photos(client_id, client["name"])
        return result

    except ListingSubmissionError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "errors": e.errors,
            },
        )


@router.get("/{client_id}/mls-feeder/status")
async def get_mls_listing_status(client_id: int) -> dict:
    """Check status of submitted MLS listing."""
    from realtorai.integrations.spark import spark_auth, get_listing_status

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    feeder = get_mls_feeder(client_id, client["name"])
    if not feeder:
        return {"submitted": False, "message": "No MLS feeder found"}

    listing_id = feeder.get("mls_listing_id")
    if not listing_id:
        return {"submitted": False, "message": "Listing not submitted yet"}

    if not await spark_auth.is_connected():
        return {
            "submitted": True,
            "listing_id": listing_id,
            "status": "unknown",
            "message": "Cannot check status - Spark API not connected",
        }

    status = await get_listing_status(listing_id)
    return {
        "submitted": True,
        "listing_id": listing_id,
        "status": status,
    }


# =============================================================================
# Buyer Alert endpoints
# =============================================================================


class BuyerCriteriaUpdate(BaseModel):
    cities: list[str] | None = None
    postal_codes: list[str] | None = None
    counties: list[str] | None = None
    min_price: int | None = None
    max_price: int | None = None
    property_types: list[str] | None = None
    min_beds: int | None = None
    max_beds: int | None = None
    min_baths: int | None = None
    min_sqft: int | None = None
    max_sqft: int | None = None
    min_year_built: int | None = None
    garage_required: bool = False
    pool_required: bool = False
    custom_filter: str | None = None


@router.get("/{client_id}/buyer-criteria")
async def get_client_buyer_criteria(client_id: int) -> dict:
    """Get buyer search criteria for a client."""
    from realtorai.integrations.spark.buyer_alerts import get_buyer_criteria

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    criteria = get_buyer_criteria(client_id, client["name"])
    if not criteria:
        return {"has_criteria": False}

    return {
        "has_criteria": True,
        "criteria": criteria.to_dict(),
        "summary": criteria.summary(),
        "sparkql": criteria.to_sparkql(),
    }


@router.put("/{client_id}/buyer-criteria")
async def set_client_buyer_criteria(client_id: int, updates: BuyerCriteriaUpdate) -> dict:
    """Set or update buyer search criteria for a client."""
    from realtorai.integrations.spark.buyer_alerts import (
        update_buyer_criteria,
        BuyerCriteria,
    )

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Build update dict from non-None fields
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}

    criteria = update_buyer_criteria(client_id, client["name"], update_data)

    return {
        "success": True,
        "criteria": criteria.to_dict(),
        "summary": criteria.summary(),
        "sparkql": criteria.to_sparkql(),
    }


@router.post("/{client_id}/buyer-criteria/scan")
async def scan_for_buyer_matches(client_id: int) -> dict:
    """Manually trigger a scan for new listings matching buyer criteria."""
    from realtorai.integrations.spark import spark_auth, run_manual_scan

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if not await spark_auth.is_connected():
        raise HTTPException(
            status_code=503,
            detail="Spark API not connected",
        )

    matches = await run_manual_scan(client_id, client["name"])

    return {
        "matches_found": len(matches),
        "listings": [
            {
                "listing_key": l.get("ListingKey"),
                "address": l.get("UnparsedAddress"),
                "city": l.get("City"),
                "price": l.get("ListPrice"),
                "beds": l.get("BedroomsTotal"),
                "baths": l.get("BathroomsTotalInteger"),
            }
            for l in matches
        ],
    }


# =============================================================================
# Transaction Tracker endpoints
# =============================================================================


class TransactionCreate(BaseModel):
    representation: str = "seller"  # "buyer" or "seller"


class TransactionUpdate(BaseModel):
    property: dict | None = None
    dates: dict | None = None
    financial: dict | None = None
    documents: dict | None = None
    contacts: dict | None = None
    milestones: dict | None = None
    seller: dict | None = None
    buyer: dict | None = None


class MilestoneUpdate(BaseModel):
    milestone: str
    completed: bool = True
    date: str | None = None


class DocumentUpdate(BaseModel):
    document: str
    received: bool = True
    date: str | None = None


@router.get("/{client_id}/transaction")
async def get_client_transaction(client_id: int) -> dict:
    """Get transaction tracker for a client."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    transaction = get_transaction(client_id, client["name"])
    if not transaction:
        return {"has_transaction": False}

    return {
        "has_transaction": True,
        "transaction": transaction,
        "progress": get_transaction_progress(transaction),
    }


@router.post("/{client_id}/transaction")
async def create_client_transaction(client_id: int, data: TransactionCreate) -> dict:
    """Create a new transaction tracker for a client."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    existing = get_transaction(client_id, client["name"])
    if existing:
        return {
            "created": False,
            "message": "Transaction already exists",
            "transaction": existing,
            "progress": get_transaction_progress(existing),
        }

    transaction = create_transaction(client_id, client["name"], data.representation)
    return {
        "created": True,
        "transaction": transaction,
        "progress": get_transaction_progress(transaction),
    }


@router.patch("/{client_id}/transaction")
async def update_client_transaction(client_id: int, updates: TransactionUpdate) -> dict:
    """Update transaction tracker data."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Build update dict from non-None fields
    update_data = {}
    for field in ["property", "dates", "financial", "documents", "contacts", "milestones", "seller", "buyer"]:
        value = getattr(updates, field, None)
        if value is not None:
            update_data[field] = value

    if not update_data:
        transaction = get_transaction(client_id, client["name"])
    else:
        transaction = update_transaction(client_id, client["name"], update_data, source="agent")

    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {
        "success": True,
        "transaction": transaction,
        "progress": get_transaction_progress(transaction),
    }


@router.post("/{client_id}/transaction/milestone")
async def update_transaction_milestone(client_id: int, data: MilestoneUpdate) -> dict:
    """Mark a transaction milestone as completed."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    transaction = set_milestone(
        client_id=client_id,
        name=client["name"],
        milestone=data.milestone,
        completed=data.completed,
        date=data.date,
    )

    return {
        "success": True,
        "transaction": transaction,
        "progress": get_transaction_progress(transaction),
    }


@router.post("/{client_id}/transaction/document")
async def update_transaction_document(client_id: int, data: DocumentUpdate) -> dict:
    """Mark a document as received."""
    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    transaction = mark_document_received(
        client_id=client_id,
        name=client["name"],
        document=data.document,
        date=data.date,
    )

    return {
        "success": True,
        "transaction": transaction,
        "progress": get_transaction_progress(transaction),
    }


# =============================================================================
# LLM Extraction endpoints
# =============================================================================


class ExtractionRequest(BaseModel):
    """Request body for data extraction."""
    content: str
    content_type: str = "email"  # email, document, p_and_s, inspection_report, etc.
    subject: str | None = None
    sender: str | None = None


@router.post("/{client_id}/extract")
async def extract_data(client_id: int, request: ExtractionRequest) -> dict:
    """Extract structured data from pasted content using LLM.

    Extracts MLS feeder data (for sellers) and transaction tracker data
    (for both buyer/seller) from emails or documents.

    Args:
        client_id: Client to update
        request: Content to extract from

    Returns:
        Extraction results including what was updated
    """
    from realtorai.inference.extraction import (
        extract_from_email,
        extract_from_document,
    )

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Determine representation from transaction type
    representation = None
    tx_type = (client.get("transaction_type") or "").lower()
    if "buy" in tx_type:
        representation = "buyer"
    elif "sell" in tx_type:
        representation = "seller"

    # Route to appropriate extraction function
    if request.content_type == "email":
        result = await extract_from_email(
            client_id=client_id,
            name=client["name"],
            email_content=request.content,
            email_subject=request.subject,
            sender=request.sender,
            representation=representation,
        )
    else:
        result = await extract_from_document(
            client_id=client_id,
            name=client["name"],
            document_text=request.content,
            document_type=request.content_type,
            representation=representation,
        )

    return {
        "success": True,
        "client_id": client_id,
        "extraction": result,
    }


# =============================================================================
# Pending items endpoints
# =============================================================================


@router.get("/pending", response_model=list[dict])
async def list_pending_items(client_id: int | None = None) -> list[dict]:
    """List pending items (what system is waiting on)."""
    db = await get_database()
    return await db.get_pending_items(client_id=client_id, status="waiting")


@router.post("/{client_id}/pending", response_model=dict)
async def create_pending_item(
    client_id: int,
    item_type: str,
    description: str,
    waiting_on: str,
    due_date: str | None = None,
) -> dict:
    """Create a pending item for a client."""
    db = await get_database()
    item_id = await db.create_pending_item(
        client_id=client_id,
        item_type=item_type,
        description=description,
        waiting_on=waiting_on,
        due_date=due_date,
    )
    items = await db.get_pending_items(client_id=client_id)
    return next((i for i in items if i["id"] == item_id), {"id": item_id})


@router.post("/{client_id}/create-room")
async def create_docusign_room(client_id: int) -> dict:
    """Create a DocuSign Room for a client."""
    from realtorai.integrations.docusign import (
        docusign_auth,
        create_room,
        get_roles,
    )
    from realtorai.storage.client_files import update_client_header

    db = await get_database()
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if client["room_id"]:
        return {"room_id": client["room_id"], "message": "Room already exists"}

    # Check DocuSign connection
    if not await docusign_auth.is_connected():
        raise HTTPException(status_code=503, detail="DocuSign not connected")

    # Get first available role
    roles = await get_roles()
    if not roles:
        raise HTTPException(status_code=503, detail="No roles available")
    role_id = roles[0].get("roleId")

    # Determine transaction side
    tx_type = client["transaction_type"] or "buy"
    tx_side = "buy" if "buy" in tx_type.lower() else "sell"

    # Create room with required field data
    room_name = client["property_address"] or client["name"]

    # DocuSign requires address fields - use property_address or defaults
    # State must be in "US-XX" format
    field_data = {
        "address1": client["property_address"] or "TBD",
        "city": "Boston",  # Default - should be parsed from address
        "state": "US-MA",  # Default - should be parsed from address
        "postalCode": "02101",  # Default - should be parsed from address
    }

    room = await create_room(
        name=room_name,
        role_id=role_id,
        transaction_side_id=tx_side,
        field_data=field_data,
    )

    if not room:
        raise HTTPException(status_code=500, detail="Failed to create room")

    room_id = room.get("roomId")

    # Update database
    await db.update_client(client_id, room_id=room_id, status="active")

    # Update markdown file
    update_client_header(client_id, client["name"], room_id=room_id, status="active")

    return {"room_id": room_id, "message": "Room created"}
