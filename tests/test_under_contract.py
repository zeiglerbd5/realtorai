"""Under-contract workflow: phase change on an existing transaction.

Offline throughout — contract terms are injected (the demo path) instead of
extracted, and the mock Rooms/MLS backends serve the side effects.
"""

from pathlib import Path

import pytest

from realtorai.fixtures import build_22_penobscot
from realtorai.integrations.docusign import rooms
from realtorai.integrations.spark.mock import get_mock_mls
from realtorai.orchestration.approval import ApprovalLoop
from realtorai.orchestration.queue import task_queue
from realtorai.storage.database import get_database
from realtorai.storage.transaction_store import list_transactions, load_transaction
from realtorai.workflows.email_trigger import propose_new_client_workflow
from realtorai.workflows.listing import start_listing_workflow
from realtorai.workflows.under_contract import start_under_contract_workflow

TERMS = {
    "contract_amount": "310000",
    "binding_date": "2026-08-01",
    "closing_date": "2026-09-15",
    "emd_amount": "5000",
    "emd_due_date": "2026-08-06",
    "entity_holding_emd": "The Agency REALTORS",
    "inspection_deadline": "2026-08-15",
    "financing_commitment_deadline": "2026-09-01",
    "financing_type": "Conventional",
    "buyer_names": ["Jordan Field"],
    "comments": "Woodstove included; fuel prorated at closing.",
}


async def _listing_slug() -> str:
    envelope = await start_listing_workflow(build_22_penobscot())
    return envelope.slug


@pytest.mark.asyncio
async def test_uc_phase_on_existing_listing(offline_env: Path) -> None:
    slug = await _listing_slug()

    envelope = await start_under_contract_workflow(slug, contract_terms=TERMS)

    # contract terms merged into the record
    record = envelope.record
    assert str(record.contract_amount) == "310000"
    assert record.closing_date.isoformat() == "2026-09-15"
    assert record.buyer_1.name == "Jordan Field"
    assert record.listing_status == "Pending"
    assert "[P&S]" in record.comments

    # UC task list on the room; EMD skipped on the listing side
    task_lists = await rooms.get_room_task_lists(record.docusign_room_id)
    names = [t["name"] for t in task_lists]
    assert "Under Contract — Listing Side" in names
    assert "Earnest Money Deposit" not in names

    # MLS moved to pending in the mock
    listing = get_mock_mls().get_listing(envelope.mls_listing_key)
    assert listing["StandardStatus"] == "Pending"

    # deadlines surface as dated pending items (client row auto-created)
    db = await get_database()
    items = await db.get_pending_items(client_id=envelope.client_id)
    by_desc = {i["description"]: i for i in items}
    assert by_desc["Inspection deadline"]["due_date"] == "2026-08-15"
    assert by_desc["Closing"]["due_date"] == "2026-09-15"
    assert by_desc["Earnest money deposit due"]["due_date"] == "2026-08-06"

    # the listing phase's timeline is archived, not lost
    assert envelope.workflow["name"] == "under_contract"
    assert [w["name"] for w in envelope.workflow_history] == ["listing"]


@pytest.mark.asyncio
async def test_uc_requires_existing_transaction(offline_env: Path) -> None:
    with pytest.raises(ValueError, match="No transaction"):
        await start_under_contract_workflow("nowhere-street", contract_terms=TERMS)


@pytest.mark.asyncio
async def test_uc_blocks_without_contract_documents(offline_env: Path) -> None:
    slug = await _listing_slug()
    envelope = await start_under_contract_workflow(slug)  # no docs, no terms

    assert envelope.workflow["status"] == "blocked"
    # nothing downstream ran: no UC task list, MLS still draft
    names = [
        t["name"]
        for t in await rooms.get_room_task_lists(envelope.record.docusign_room_id)
    ]
    assert "Under Contract — Listing Side" not in names
    assert get_mock_mls().get_listing(envelope.mls_listing_key)["StandardStatus"] == "Draft"


@pytest.mark.asyncio
async def test_uc_email_proposes_and_approval_runs_phase(offline_env: Path) -> None:
    slug = await _listing_slug()
    before = len(list_transactions())

    task_id = await propose_new_client_workflow(
        "Completed: Purchase and Sale Agreement — 22 Penobscot Street",
        "All parties have signed the Purchase and Sale Agreement for "
        "22 Penobscot Street, Orono. We are under contract!",
        [],
        source="test",
    )
    assert task_id is not None
    task = await task_queue.get_task(task_id)
    planned = task.proposal_data["planned_actions"]
    assert planned[0]["kind"] == "under_contract"

    # offline heuristic can't extract the address — set the slug + terms the
    # way the copilot conversation would
    planned[0]["transaction_slug"] = slug
    planned[0]["contract_terms"] = TERMS
    db = await get_database()
    await db.update_task_data(task_id, {**task.proposal_data, "planned_actions": planned})
    task = await task_queue.get_task(task_id)

    ok = await ApprovalLoop().approve(task)
    assert ok
    # a phase change, not a new deal
    assert len(list_transactions()) == before
    envelope = load_transaction(slug)
    assert envelope.workflow["name"] == "under_contract"
    assert envelope.record.listing_status == "Pending"
    # the narration reached the thread
    task = await task_queue.get_task(task_id)
    assert "under_contract" in task.proposal_data["execution_results"][0]["side"]


@pytest.mark.asyncio
async def test_uc_buyer_side_adds_emd_list(offline_env: Path) -> None:
    from realtorai.workflows.buyer import start_buyer_workflow

    record = build_22_penobscot()
    record.representation_side = "Buyer"
    envelope = await start_buyer_workflow(record)

    await start_under_contract_workflow(envelope.slug, contract_terms=TERMS)

    updated = load_transaction(envelope.slug)
    names = [
        t["name"]
        for t in await rooms.get_room_task_lists(updated.record.docusign_room_id)
    ]
    assert "Under Contract — Buyer Side" in names
    assert "Earnest Money Deposit" in names  # held by "The Agency REALTORS"
