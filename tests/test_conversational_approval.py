"""Conversational approval: the thread scopes, the go-word executes.

All offline. The gate (go / no-go) is plain regex + code, so it's fully
testable without the API; the chat layer degrades to a canned pointer at
the gate when no key is configured.
"""

from pathlib import Path

import pytest

from realtorai.fixtures import build_22_penobscot
from realtorai.orchestration.conversation import handle_reply
from realtorai.orchestration.queue import task_queue
from realtorai.schemas.tasks import ApprovalStatus
from realtorai.storage.database import get_database
from realtorai.storage.transaction_store import list_transactions
from realtorai.workflows.email_trigger import propose_new_client_workflow

SUBJECT = "Fwd: new listing paperwork"
BODY = "New listing for the Larsons at 12 Birch Lane — can you take it from here?"


async def _propose() -> str:
    task_id = await propose_new_client_workflow(SUBJECT, BODY, [], source="test")
    assert task_id is not None
    return task_id


async def _amend_proposal(task_id: str, **changes) -> None:
    """Inject proposal fields (offline stand-in for extraction / chat planning)."""
    task = await task_queue.get_task(task_id)
    assert task is not None
    proposal = {**task.proposal_data, **changes}
    db = await get_database()
    await db.update_task_data(task_id, proposal)


def _record_json() -> dict:
    return build_22_penobscot().model_dump(mode="json")


@pytest.mark.asyncio
async def test_proposal_opens_with_question_and_planned_work(offline_env: Path) -> None:
    task_id = await _propose()
    task = await task_queue.get_task(task_id)
    assert task is not None
    conversation = task.proposal_data["conversation"]
    assert conversation[0]["role"] == "agent"
    assert "Want me to start the listing workflow" in conversation[0]["text"]
    planned = task.proposal_data["planned_actions"]
    assert len(planned) == 1 and planned[0]["side"] == "listing"


@pytest.mark.asyncio
async def test_chat_reply_stays_pending(offline_env: Path) -> None:
    task_id = await _propose()
    outcome, message = await handle_reply(task_id, "what exactly will this do?")
    assert outcome == "answer"
    task = await task_queue.get_task(task_id)
    assert task is not None
    assert task.status == ApprovalStatus.PENDING
    conversation = task.proposal_data["conversation"]
    assert [m["role"] for m in conversation] == ["agent", "operator", "agent"]
    assert conversation[-1]["text"] == message
    assert list_transactions() == []


@pytest.mark.asyncio
async def test_go_with_path_attaches_and_runs(offline_env: Path, tmp_path: Path) -> None:
    erts = tmp_path / "signed_erts.txt"
    erts.write_text("Exclusive Right to Sell — 22 Penobscot Street, Orono")

    task_id = await _propose()
    await _amend_proposal(task_id, record=_record_json())
    outcome, narration = await handle_reply(task_id, f"yes — the signed ERTS is at {erts}")
    assert outcome == "approved"
    assert "Done — ran 1 workflow" in narration

    task = await task_queue.get_task(task_id)
    assert task is not None
    assert task.status == ApprovalStatus.APPROVED
    intake_dir = Path(task.proposal_data["intake_dir"])
    assert (intake_dir / "signed_erts.txt").exists()
    assert "signed_erts.txt" in task.details["attachments"]
    assert len(list_transactions()) == 1
    # the machinery's report landed in the thread
    assert task.proposal_data["conversation"][-1]["role"] == "agent"
    assert task.proposal_data["execution_results"][0]["slug"]


@pytest.mark.asyncio
async def test_go_runs_every_planned_workflow(offline_env: Path) -> None:
    """One approval fans out to N planned workflows — the multi-client email."""
    task_id = await _propose()
    await _amend_proposal(
        task_id,
        record=_record_json(),
        planned_actions=[
            {
                "side": "listing",
                "client_name": "Pat & Sam Larson",
                "property_address": "12 Birch Lane, Hampden",
                "note": None,
            },
            {
                "side": "buyer",
                "client_name": "Robin Carver",
                "property_address": None,
                "note": "buyer side only",
                # distinct record -> distinct slug (offline stand-in for the
                # per-workflow extraction the executor does when online)
                "record": {
                    **_record_json(),
                    "street_address": "12 Birch Lane",
                    "city": "Hampden",
                },
            },
        ],
    )
    outcome, narration = await handle_reply(task_id, "go ahead")
    assert outcome == "approved"
    assert "Done — ran 2 workflows" in narration
    task = await task_queue.get_task(task_id)
    assert task is not None
    results = task.proposal_data["execution_results"]
    assert [r["side"] for r in results] == ["listing", "buyer"]
    assert len(list_transactions()) == 2


@pytest.mark.asyncio
async def test_missing_path_blocks_execution(offline_env: Path) -> None:
    task_id = await _propose()
    await _amend_proposal(task_id, record=_record_json())
    outcome, message = await handle_reply(task_id, "yes — use /nowhere/erts.pdf")
    assert outcome == "answer"
    assert "/nowhere/erts.pdf" in message
    task = await task_queue.get_task(task_id)
    assert task is not None
    assert task.status == ApprovalStatus.PENDING
    assert list_transactions() == []


@pytest.mark.asyncio
async def test_no_rejects_and_runs_nothing(offline_env: Path) -> None:
    task_id = await _propose()
    outcome, _ = await handle_reply(task_id, "no, hold off on this one")
    assert outcome == "rejected"
    task = await task_queue.get_task(task_id)
    assert task is not None
    assert task.status == ApprovalStatus.REJECTED
    assert list_transactions() == []
