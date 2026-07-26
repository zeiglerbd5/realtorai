"""End-to-end demo: new listing client -> DTR room + MLS draft, fully offline.

Runs the listing workflow against the 22 Penobscot St record with the mock
DocuSign Rooms and mock MLS backends (the defaults). With ANTHROPIC_API_KEY
set, the verification, deed-review, and remarks-drafting steps run live on
the Claude API; without it they degrade gracefully and everything else still
runs.

Usage:
    python scripts/demo_listing_workflow.py            # run / resume
    python scripts/demo_listing_workflow.py --fresh    # wipe mock state first
"""

import asyncio
import sys

from realtorai.fixtures import build_22_penobscot as build_penobscot_record
from realtorai.integrations.docusign import rooms
from realtorai.workflows.intake import PaperworkDocument
from realtorai.workflows.listing import start_listing_workflow

# Simulated signed-paperwork attachments (stand-ins for the scanned PDFs the
# realtor would attach to the intake email).
SIGNED_PAPERWORK: list[tuple[str, bytes]] = [
    (
        "Exclusive Right to Sell - 22 Penobscot St - SIGNED.txt",
        b"Exclusive Right to Sell Listing Agreement\n"
        b"Seller: Brett D. Zeigler\nProperty: 22 Penobscot Street, Orono, ME 04473\n"
        b"List price: $325,000  Commission: 1%\nTerm: 2026-06-01 through 2026-12-01\n"
        b"Deed reference: Book 16601, Pages 156-157\nSigned: Brett D. Zeigler, Agent One",
    ),
    (
        "Brokerage Relationship Form - SIGNED.txt",
        b"Maine Real Estate Commission Brokerage Relationship Form (Form #3)\n"
        b"Licensee: Agent One, The Agency\n"
        b"Client: Brett D. Zeigler (Seller Client)\nDated: 2026-05-31",
    ),
    (
        "22 penobscot deed.txt",
        b"QUITCLAIM DEED WITH COVENANT\n"
        b"Penobscot County Registry of Deeds, Book 16601, Pages 156-157\n"
        b"A certain lot or parcel of land situated on the westerly side of "
        b"Penobscot Street in Orono, Penobscot County, Maine; being the same "
        b"premises conveyed to Daniel Moor by Ard Godfrey et al. by deed dated "
        b"April 29, 1836 (Vol 101, Pg 84); EXCEPTING AND RESERVING that portion "
        b"of the premises conveyed to the European & North American Railway "
        b"Company, its successors and assigns, for railroad purposes, together "
        b"with any rights of way appurtenant thereto.",
    ),
]


async def main() -> int:
    if "--fresh" in sys.argv:
        from realtorai.integrations.docusign.mock import MockRoomsAPI
        from realtorai.integrations.spark.mock import MockSparkMLS

        MockRoomsAPI().reset()
        MockSparkMLS().reset()
        print("(mock backends reset)\n")

    record = build_penobscot_record()
    documents = [
        PaperworkDocument(name=name, text=content.decode()) for name, content in SIGNED_PAPERWORK
    ]

    print("=== Listing workflow: 22 Penobscot Street, Orono ===\n")
    envelope = await start_listing_workflow(
        record,
        documents=documents,
        paperwork_files=SIGNED_PAPERWORK,
        client_name="Brett Zeigler",
    )

    # ---- timeline ----------------------------------------------------------
    state = envelope.workflow or {}
    print(f"\nWorkflow status: {state.get('status', '?').upper()}\n")
    icons = {"done": "✓", "waiting": "⏳", "skipped": "–", "failed": "✗", "pending": "·"}
    for step in state.get("steps", []):
        icon = icons.get(step["status"], "?")
        print(f"  {icon} {step['title']}")
        if step.get("detail"):
            print(f"      {step['detail']}")

    # ---- room summary ------------------------------------------------------
    room_id = envelope.record.docusign_room_id
    if room_id:
        print(f"\n=== Transaction Room {room_id} ===")
        task_lists = await rooms.get_room_task_lists(room_id)
        for task_list in task_lists:
            print(f"  Task list: {task_list['name']} ({len(task_list['tasks'])} tasks)")
        forms = await rooms.get_room_forms(room_id)
        for form in forms:
            print(
                f"  Form: {form['name']} — "
                f"{form.get('prefilledFieldCount', 0)}/{form.get('expectedFieldCount', 0)} "
                "fields auto-filled from room data"
            )
        docs = await rooms.get_room_documents(room_id)
        for doc in docs:
            print(f"  Document: {doc['name']} ({doc['size']} bytes)")

    # ---- artifacts ---------------------------------------------------------
    print("\n=== Artifacts ===")
    for artifact in envelope.artifacts:
        marker = " → filed to room" if artifact.uploaded_to_room else " (internal only)"
        print(f"  {artifact.name}{marker}\n      {artifact.path}")

    if envelope.mls_listing_key:
        from realtorai.integrations.spark.submission import get_listing_status

        status = await get_listing_status(envelope.mls_listing_key)
        if status:
            print(
                f"\n=== MLS === \n  Draft #{status['listing_id']} — {status['mls_status']}"
                f" — ${status['price']:,}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
