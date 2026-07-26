"""Approval-gated workflow kickoff — propose, approve, execute (offline)."""

from realtorai.fixtures import build_22_penobscot
from realtorai.workflows.email_trigger import propose_new_client_workflow

PAPERWORK = [
    ("Exclusive Right to Sell - SIGNED.pdf", b"%PDF-1.4 signed listing agreement"),
    ("Property Disclosure.pdf", b"%PDF-1.4 disclosure"),
]


async def test_propose_creates_pending_task_and_nothing_runs(offline_env):
    from realtorai.orchestration.queue import task_queue
    from realtorai.storage.transaction_store import list_transactions

    task_id = await propose_new_client_workflow(
        "FW: New listing client — signed listing agreement attached",
        "Here's the new client's paperwork.",
        PAPERWORK,
    )
    assert task_id is not None

    task = await task_queue.get_task(task_id)
    assert task is not None
    assert task.task_type.value == "workflow_kickoff"
    assert task.proposal_data["side"] == "listing"
    # THE GATE: proposing must not run anything
    assert list_transactions() == []

    # Intake bundle persisted for post-approval execution
    from pathlib import Path

    intake_dir = Path(task.proposal_data["intake_dir"])
    assert (intake_dir / "email.json").exists()
    assert (intake_dir / "Exclusive Right to Sell - SIGNED.pdf").exists()


async def test_non_intake_email_proposes_nothing(offline_env):
    task_id = await propose_new_client_workflow(
        "Fw: House tour feedback",
        "Agents suggested raising rents.",
        [],
    )
    assert task_id is None


async def test_approve_executes_the_workflow(offline_env):
    from realtorai.integrations.docusign import rooms
    from realtorai.orchestration.approval import ApprovalLoop
    from realtorai.orchestration.queue import task_queue
    from realtorai.storage.transaction_store import list_transactions

    task_id = await propose_new_client_workflow(
        "FW: New listing client — signed listing agreement attached",
        "Here's the new client's paperwork.",
        PAPERWORK,
    )
    task = await task_queue.get_task(task_id)
    # Offline there's no Claude extraction — supply the record (demo path);
    # in production the executor extracts from the saved attachments.
    task.proposal_data["record"] = build_22_penobscot().model_dump(mode="json")

    ok = await ApprovalLoop().approve(task)
    assert ok

    envelopes = list_transactions()
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope.record.docusign_room_id is not None
    # The signed paperwork from the intake bundle was filed to the room
    docs = {d["name"] for d in await rooms.get_room_documents(envelope.record.docusign_room_id)}
    assert "Exclusive Right to Sell - SIGNED.pdf" in docs


async def test_reject_runs_nothing(offline_env):
    from realtorai.orchestration.approval import ApprovalLoop
    from realtorai.orchestration.queue import task_queue
    from realtorai.storage.transaction_store import list_transactions

    task_id = await propose_new_client_workflow(
        "FW: New buyer client — buyer representation agreement",
        "New buyer client paperwork attached.",
        [("EBRA.pdf", b"%PDF-1.4 signed")],
    )
    task = await task_queue.get_task(task_id)
    await ApprovalLoop().reject(task, reason="not a real client")
    assert list_transactions() == []
