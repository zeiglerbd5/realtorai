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


@router.post("", response_model=dict)
async def create_client(client: ClientCreate) -> dict:
    """Create a new client."""
    db = await get_database()
    client_id = await db.create_client(**client.model_dump())
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
