"""Pending items action routes."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from realtorai.storage.database import get_database

router = APIRouter()


@router.post("/{item_id}/resolve")
async def resolve_pending_item(item_id: int) -> dict:
    """Mark a pending item as resolved/received."""
    db = await get_database()
    await db.resolve_pending_item(item_id, status="received")
    return {"success": True, "status": "received"}


@router.post("/{item_id}/approve")
async def approve_pending_item(item_id: int) -> dict:
    """Approve a pending item (for agent approval items)."""
    db = await get_database()
    await db.resolve_pending_item(item_id, status="approved")
    return {"success": True, "status": "approved"}


@router.post("/{item_id}/reject")
async def reject_pending_item(item_id: int) -> dict:
    """Reject a pending item."""
    db = await get_database()
    await db.resolve_pending_item(item_id, status="rejected")
    return {"success": True, "status": "rejected"}
