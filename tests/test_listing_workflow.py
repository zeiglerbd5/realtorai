"""End-to-end workflow tests — fully offline against the mock backends."""

from realtorai.fixtures import build_22_penobscot
from realtorai.integrations.docusign import rooms
from realtorai.storage.transaction_store import load_transaction
from realtorai.workflows.buyer import start_buyer_workflow
from realtorai.workflows.listing import start_listing_workflow

PAPERWORK = [
    ("Exclusive Right to Sell - SIGNED.txt", b"signed listing agreement"),
    ("Brokerage Relationship Form - SIGNED.txt", b"signed brokerage relationship form"),
]


async def test_listing_workflow_offline(offline_env):
    envelope = await start_listing_workflow(
        build_22_penobscot(), paperwork_files=PAPERWORK, client_name="Morgan Rowe"
    )

    state = envelope.workflow
    assert state is not None
    # Disclosures wait on the client; LLM steps skip offline; nothing fails
    assert state["status"] == "waiting"
    by_key = {s["key"]: s for s in state["steps"]}
    assert by_key["verify_extraction"]["status"] == "skipped"  # offline
    assert by_key["create_room"]["status"] == "done"
    assert by_key["task_list"]["status"] == "done"
    assert by_key["agency_forms"]["status"] == "done"
    assert by_key["disclosures"]["status"] == "waiting"
    assert by_key["mls_draft"]["status"] == "done"
    assert by_key["public_records"]["status"] == "done"
    assert by_key["deed_review"]["status"] == "skipped"  # no deed doc offline

    # Room contents
    room_id = envelope.record.docusign_room_id
    assert room_id is not None
    task_lists = await rooms.get_room_task_lists(room_id)
    assert [t["name"] for t in task_lists] == ["New Listing"]
    form_names = {f["name"] for f in await rooms.get_room_forms(room_id)}
    assert "Exclusive Right to Sell Listing Agreement" in form_names
    # 1920 build year -> lead paint disclosure attached
    assert "Lead Based Paint Hazard Disclosure" in form_names
    doc_names = {d["name"] for d in await rooms.get_room_documents(room_id)}
    assert "Exclusive Right to Sell - SIGNED.txt" in doc_names
    assert "tax_map.md" in doc_names and "flood_map.md" in doc_names

    # MLS draft created with the record's list price
    assert envelope.mls_listing_key is not None
    from realtorai.integrations.spark.submission import get_listing_status

    status = await get_listing_status(envelope.mls_listing_key)
    assert status is not None
    assert status["status"] == "Draft"
    assert status["price"] == 325000

    # Master doc rendered, never uploaded to the room
    master = next(a for a in envelope.artifacts if a.name == "Master Information Document")
    assert master.uploaded_to_room is False
    from pathlib import Path

    text = Path(master.path).read_text()
    assert "22 Penobscot Street" in text
    assert "Lead paint disclosure required" in text  # pre-1978 trigger


async def test_listing_workflow_resume_is_idempotent(offline_env):
    first = await start_listing_workflow(build_22_penobscot(), paperwork_files=PAPERWORK)
    room_id = first.record.docusign_room_id

    second = await start_listing_workflow(build_22_penobscot(), paperwork_files=PAPERWORK)
    # Same transaction, same room — no duplicates created
    assert second.record.docusign_room_id == room_id
    assert len(await rooms.get_room_task_lists(room_id)) == 1
    forms = await rooms.get_room_forms(room_id)
    assert len(forms) == len({f["name"] for f in forms})
    docs = await rooms.get_room_documents(room_id)
    assert len(docs) == len({d["name"] for d in docs})

    # Persisted envelope reflects the latest run
    stored = load_transaction(first.slug)
    assert stored is not None
    assert stored.workflow["status"] == "waiting"


async def test_buyer_workflow_offline(offline_env):
    from realtorai.schemas.transaction import Party, TransactionRecord

    record = TransactionRecord(
        representation_side="Buyer",
        buyer_1=Party(name="Jordan Smith", email="jordan@example.com"),
        buyer_agent_1=Party(name="Agent One", company="The Agency"),
    )
    envelope = await start_buyer_workflow(
        record,
        paperwork_files=[("EBRA - SIGNED.txt", b"signed buyer agreement")],
        client_name="Jordan Smith",
    )

    state = envelope.workflow
    assert state is not None
    assert state["status"] == "done"

    room_id = envelope.record.docusign_room_id
    assert room_id is not None
    room = await rooms.get_room(room_id)
    assert room["transactionSideId"] == "buy"
    assert [t["name"] for t in await rooms.get_room_task_lists(room_id)] == ["Buyer Agreement"]
    form_names = {f["name"] for f in await rooms.get_room_forms(room_id)}
    assert "Exclusive Buyer Representation Agreement" in form_names
    # No MLS activity on buyer side
    assert envelope.mls_listing_key is None
