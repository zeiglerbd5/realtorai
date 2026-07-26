"""Dashboard copilot: chat can read everything, but can only PROPOSE work.

The agent loop itself needs the API; these tests exercise the tool
implementations directly — the layer where the permission split lives.
"""

from pathlib import Path

import pytest

from realtorai.orchestration.copilot import (
    DASHBOARD_TOOL_SCHEMAS,
    _dashboard_tool_impls,
)
from realtorai.orchestration.queue import task_queue
from realtorai.schemas.tasks import TaskType
from realtorai.storage.transaction_store import list_transactions


def test_no_execution_tools_exist() -> None:
    """The structural gate: no dashboard tool can run a workflow."""
    names = {t["name"] for t in DASHBOARD_TOOL_SCHEMAS}
    assert "propose_workflow" in names
    mutating = names - {
        "list_active_transactions",
        "transaction_status",
        "mls_readiness",
        "search_playbook",
        "list_pending_tasks",
    }
    assert mutating == {"propose_workflow"}


@pytest.mark.asyncio
async def test_propose_workflow_only_files_a_pending_task(offline_env: Path) -> None:
    impls = _dashboard_tool_impls()
    result = await impls["propose_workflow"](
        side="listing",
        client_name="Pat Larson",
        property_address="12 Birch Lane, Hampden",
        note="pre-1978 build, expect lead paint disclosure",
    )
    assert "pending in the approval queue" in result

    tasks = await task_queue.get_pending()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_type == TaskType.WORKFLOW_KICKOFF
    planned = task.proposal_data["planned_actions"]
    assert planned[0]["client_name"] == "Pat Larson"
    assert Path(task.proposal_data["intake_dir"]).exists()
    # the whole point: proposing runs NOTHING
    assert list_transactions() == []


@pytest.mark.asyncio
async def test_list_pending_tasks_reads_the_queue(offline_env: Path) -> None:
    impls = _dashboard_tool_impls()
    assert "queue is empty" in await impls["list_pending_tasks"]()
    await impls["propose_workflow"](side="buyer", client_name="Robin Carver")
    listing = await impls["list_pending_tasks"]()
    assert "workflow_kickoff" in listing and "Robin Carver" in listing
