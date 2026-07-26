"""End-to-end demo: new buyer client -> DTR room with buyer agreement filed.

Buyer clients get a Transaction Room and task list but no MLS activity.
Runs fully offline against the mock backends (the defaults).

Usage:
    python scripts/demo_buyer_workflow.py
"""

import asyncio
import sys

from realtorai.integrations.docusign import rooms
from realtorai.schemas.transaction import Party, TransactionRecord
from realtorai.workflows.buyer import start_buyer_workflow

SIGNED_PAPERWORK: list[tuple[str, bytes]] = [
    (
        "Exclusive Buyer Representation Agreement - SIGNED.txt",
        b"Exclusive Buyer Representation Agreement\n"
        b"Buyer: Jordan Smith\nAgent: Agent One, The Agency\n"
        b"Search area: Greater Bangor\nTerm: 2026-07-01 through 2027-01-01",
    ),
    (
        "Brokerage Relationship Form - SIGNED.txt",
        b"Maine Real Estate Commission Brokerage Relationship Form (Form #3)\n"
        b"Licensee: Agent One\nClient: Jordan Smith (Buyer Client)",
    ),
]


def build_record() -> TransactionRecord:
    return TransactionRecord(
        representation_side="Buyer",
        buyer_1=Party(
            name="Jordan Smith",
            email="jordan.smith@example.com",
            cell_phone="207-555-0111",
            city="Bangor",
            state="ME",
        ),
        buyer_agent_1=Party(
            name="Agent One",
            company="The Agency REALTORS",
            business_phone="207-555-0101",
        ),
    )


async def main() -> int:
    print("=== Buyer workflow: Jordan Smith ===\n")
    envelope = await start_buyer_workflow(
        build_record(),
        paperwork_files=SIGNED_PAPERWORK,
        client_name="Jordan Smith",
    )

    state = envelope.workflow or {}
    print(f"\nWorkflow status: {state.get('status', '?').upper()}\n")
    icons = {"done": "✓", "waiting": "⏳", "skipped": "–", "failed": "✗", "pending": "·"}
    for step in state.get("steps", []):
        icon = icons.get(step["status"], "?")
        print(f"  {icon} {step['title']}")
        if step.get("detail"):
            print(f"      {step['detail']}")

    room_id = envelope.record.docusign_room_id
    if room_id:
        print(f"\n=== Transaction Room {room_id} ===")
        for task_list in await rooms.get_room_task_lists(room_id):
            print(f"  Task list: {task_list['name']} ({len(task_list['tasks'])} tasks)")
        for form in await rooms.get_room_forms(room_id):
            print(
                f"  Form: {form['name']} — "
                f"{form.get('prefilledFieldCount', 0)}/{form.get('expectedFieldCount', 0)} "
                "fields auto-filled"
            )
        for doc in await rooms.get_room_documents(room_id):
            print(f"  Document: {doc['name']} ({doc['size']} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
