"""Failed verification BLOCKS downstream side effects; approval is atomic.

Both were real review findings: the verify step used WAITING (which by
design does not halt), so a failed audit still created rooms and MLS
drafts; and approve() updated status unconditionally, so a repeated
approval could execute the same work twice.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from realtorai.fixtures import build_22_penobscot
from realtorai.orchestration.approval import ApprovalLoop
from realtorai.orchestration.queue import task_queue
from realtorai.storage.database import get_database
from realtorai.storage.transaction_store import list_transactions
from realtorai.workflows import common
from realtorai.workflows.email_trigger import propose_new_client_workflow
from realtorai.workflows.intake import (
    PaperworkDocument,
    VerificationIssue,
    VerificationReport,
)
from realtorai.workflows.listing import start_listing_workflow

DOCS = [PaperworkDocument(name="signed_erts.txt", text="Exclusive Right to Sell …")]


def _pretend_engine_online(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        common, "get_claude_engine", lambda: SimpleNamespace(available=True)
    )


def _stub_verification(monkeypatch: pytest.MonkeyPatch, *, safe: bool) -> None:
    async def fake_verify(record, documents):
        if safe:
            return VerificationReport(issues=[], summary="clean", safe_to_proceed=True)
        return VerificationReport(
            issues=[
                VerificationIssue(
                    field="list_price",
                    issue="does not appear in the source documents",
                    severity="critical",
                )
            ],
            summary="hallucinated price",
            safe_to_proceed=False,
        )

    monkeypatch.setattr(common, "verify_transaction_record", fake_verify)


@pytest.mark.asyncio
async def test_failed_verification_blocks_all_side_effects(
    offline_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pretend_engine_online(monkeypatch)
    _stub_verification(monkeypatch, safe=False)

    envelope = await start_listing_workflow(build_22_penobscot(), documents=DOCS)

    assert envelope.workflow["status"] == "blocked"
    verify = next(s for s in envelope.workflow["steps"] if s["key"] == "verify_extraction")
    assert verify["status"] == "blocked"
    # nothing downstream happened: no room, no MLS draft, no artifacts filed
    assert envelope.record.docusign_room_id is None
    assert envelope.mls_listing_key is None
    later = [s["status"] for s in envelope.workflow["steps"][1:]]
    assert set(later) == {"pending"}


@pytest.mark.asyncio
async def test_resume_after_correction_completes(
    offline_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pretend_engine_online(monkeypatch)
    _stub_verification(monkeypatch, safe=False)
    record = build_22_penobscot()
    envelope = await start_listing_workflow(record, documents=DOCS)
    assert envelope.workflow["status"] == "blocked"

    # human reviewed / data corrected — verification now passes on resume
    _stub_verification(monkeypatch, safe=True)
    envelope = await start_listing_workflow(record, documents=DOCS)
    assert envelope.workflow["status"] == "waiting"  # disclosures, as normal
    assert envelope.record.docusign_room_id is not None
    assert envelope.mls_listing_key is not None


@pytest.mark.asyncio
async def test_double_approval_executes_once(offline_env: Path) -> None:
    task_id = await propose_new_client_workflow(
        "Fwd: new listing paperwork",
        "New listing for the Larsons — signed Exclusive Right to Sell attached.",
        [],
        source="test",
    )
    assert task_id is not None
    task = await task_queue.get_task(task_id)
    proposal = dict(task.proposal_data)
    proposal["record"] = build_22_penobscot().model_dump(mode="json")
    db = await get_database()
    await db.update_task_data(task_id, proposal)
    task = await task_queue.get_task(task_id)

    loop = ApprovalLoop()
    first = await loop.approve(task)
    second = await loop.approve(task)  # stale task object, double-click, retry…

    assert first is True
    assert second is False  # claim already taken — did not execute again
    assert len(list_transactions()) == 1
