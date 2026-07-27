"""Closing workflow: the final phase change — reviewed, filed, closed out.

Offline throughout — closing terms are injected (the demo path) and the
mock Rooms/MLS backends serve the side effects.
"""

from pathlib import Path

import pytest

from realtorai.fixtures import build_22_penobscot
from realtorai.integrations.docusign import rooms
from realtorai.integrations.spark.mock import get_mock_mls
from realtorai.orchestration.queue import task_queue
from realtorai.storage.database import get_database
from realtorai.storage.transaction_store import load_transaction
from realtorai.workflows.closing import start_closing_workflow
from realtorai.workflows.email_trigger import propose_new_client_workflow
from realtorai.workflows.listing import start_listing_workflow
from realtorai.workflows.under_contract import start_under_contract_workflow

UC_TERMS = {
    "contract_amount": "310000",
    "closing_date": "2026-09-15",
    "emd_amount": "5000",
    "emd_due_date": "2026-08-06",
    "inspection_deadline": "2026-08-15",
    "seller_concession_amount": "5000",
}

CLEAN_CLOSING = {
    "final_sale_price": "310000",
    "closing_date": "2026-09-15",
    "seller_concession_on_statement": "5000",
    "total_commission": "18600",
}


async def _deal_under_contract() -> str:
    envelope = await start_listing_workflow(build_22_penobscot())
    await start_under_contract_workflow(envelope.slug, contract_terms=UC_TERMS)
    return envelope.slug


@pytest.mark.asyncio
async def test_clean_closing_closes_everything(offline_env: Path) -> None:
    slug = await _deal_under_contract()

    envelope = await start_closing_workflow(slug, closing_terms=CLEAN_CLOSING)

    record = envelope.record
    assert str(record.final_sale_price) == "310000"
    assert record.listing_status == "Closed"

    # review passed — no discrepancy hold
    steps = {s["key"]: s for s in envelope.workflow["steps"]}
    assert steps["statement_review"]["status"] == "done"

    # room closed with the closing date; Closing task list on it
    room = await rooms.get_room(record.docusign_room_id)
    assert room["roomStatus"] == "Closed"
    assert room["closedDate"] == "2026-09-15"
    names = [t["name"] for t in await rooms.get_room_task_lists(record.docusign_room_id)]
    assert "Closing" in names

    # MLS closed in the mock
    listing = get_mock_mls().get_listing(envelope.mls_listing_key)
    assert listing["StandardStatus"] == "Closed"

    # deadlines resolved, client closed
    db = await get_database()
    assert await db.get_pending_items(client_id=envelope.client_id) == []
    client = await db.get_client(envelope.client_id)
    assert client["status"] == "closed"

    # all three phases in history/current
    assert envelope.workflow["name"] == "closing"
    assert [w["name"] for w in envelope.workflow_history] == ["listing", "under_contract"]


@pytest.mark.asyncio
async def test_missing_concession_holds_for_team_review(offline_env: Path) -> None:
    slug = await _deal_under_contract()

    terms = {**CLEAN_CLOSING, "seller_concession_on_statement": None}
    envelope = await start_closing_workflow(slug, closing_terms=terms)

    steps = {s["key"]: s for s in envelope.workflow["steps"]}
    review = steps["statement_review"]
    assert review["status"] == "waiting"
    assert "does NOT appear" in review["detail"]
    # waiting doesn't halt: closing prep continues while the team reviews
    assert steps["closing_task_list"]["status"] == "done"
    assert envelope.workflow["status"] == "waiting"


@pytest.mark.asyncio
async def test_price_mismatch_flagged(offline_env: Path) -> None:
    slug = await _deal_under_contract()

    terms = {**CLEAN_CLOSING, "final_sale_price": "305000"}
    envelope = await start_closing_workflow(slug, closing_terms=terms)

    review = next(
        s for s in envelope.workflow["steps"] if s["key"] == "statement_review"
    )
    assert review["status"] == "waiting"
    assert "305000" in review["detail"] and "310000" in review["detail"]


@pytest.mark.asyncio
async def test_closing_blocks_without_statement(offline_env: Path) -> None:
    slug = await _deal_under_contract()
    envelope = await start_closing_workflow(slug)  # no docs, no terms

    assert envelope.workflow["status"] == "blocked"
    room = await rooms.get_room(envelope.record.docusign_room_id)
    assert room["roomStatus"] == "Active"  # nothing downstream ran


@pytest.mark.asyncio
async def test_closing_email_proposes_phase(offline_env: Path) -> None:
    slug = await _deal_under_contract()

    task_id = await propose_new_client_workflow(
        "Settlement Statement — 22 Penobscot Street",
        "Attached is the settlement statement for 22 Penobscot Street for "
        "your review ahead of the September 15 closing.",
        [],
        source="test",
    )
    assert task_id is not None
    task = await task_queue.get_task(task_id)
    planned = task.proposal_data["planned_actions"]
    assert planned[0]["kind"] == "closing"

    planned[0]["transaction_slug"] = slug
    planned[0]["closing_terms"] = CLEAN_CLOSING
    db = await get_database()
    await db.update_task_data(task_id, {**task.proposal_data, "planned_actions": planned})
    task = await task_queue.get_task(task_id)

    from realtorai.orchestration.approval import ApprovalLoop

    ok = await ApprovalLoop().approve(task)
    assert ok
    envelope = load_transaction(slug)
    assert envelope.workflow["name"] == "closing"
    assert envelope.record.listing_status == "Closed"
