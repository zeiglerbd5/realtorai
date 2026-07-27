"""Demo: the under-contract and closing phases on the reference listing.

Runs the listing intake first if needed, then applies demo contract terms
(the offline stand-in for P&S extraction) and runs the UC workflow: UC task
list, Transaction Worksheet, MLS to Pending, deadline tracking.

    python scripts/demo_lifecycle.py
"""

import asyncio

from realtorai.fixtures import build_22_penobscot
from realtorai.integrations.docusign import rooms
from realtorai.storage.database import close_database
from realtorai.storage.transaction_store import load_transaction, slug_for
from realtorai.workflows.listing import start_listing_workflow
from realtorai.workflows.under_contract import start_under_contract_workflow

DEMO_TERMS = {
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


async def main() -> None:
    record = build_22_penobscot()
    slug = slug_for(record)
    if load_transaction(slug) is None:
        print("No existing transaction — running the listing intake first…")
        await start_listing_workflow(record)

    envelope = await start_under_contract_workflow(slug, contract_terms=DEMO_TERMS)

    print(f"\n=== Under contract: {envelope.slug} ===")
    for step in envelope.workflow["steps"]:
        detail = f" — {step['detail']}" if step.get("detail") else ""
        print(f"  [{step['status']:7s}] {step['title']}{detail}")

    task_lists = await rooms.get_room_task_lists(envelope.record.docusign_room_id)
    print("\nRoom task lists:", ", ".join(t["name"] for t in task_lists))
    print(f"Listing status: {envelope.record.listing_status}")

    from realtorai.workflows.closing import start_closing_workflow

    envelope = await start_closing_workflow(
        slug,
        closing_terms={
            "final_sale_price": "310000",
            "closing_date": "2026-09-15",
            "total_commission": "18600",
        },
    )
    print(f"\n=== Closing: {envelope.slug} ===")
    for step in envelope.workflow["steps"]:
        detail = f" — {step['detail']}" if step.get("detail") else ""
        print(f"  [{step['status']:7s}] {step['title']}{detail}")

    room = await rooms.get_room(envelope.record.docusign_room_id)
    print(f"\nRoom status: {room['roomStatus']} ({room.get('closedDate')})")
    print(f"Listing status: {envelope.record.listing_status}")
    print(f"Phases: {[w['name'] for w in envelope.workflow_history]} -> "
          f"{envelope.workflow['name']}")
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
