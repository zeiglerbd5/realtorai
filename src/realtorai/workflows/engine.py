"""Resumable step-based workflow engine.

A workflow is an ordered list of steps run against a WorkflowContext. After
every step the full state is persisted into the transaction envelope, so a
workflow can be stopped and resumed (e.g. while waiting for a client to
complete property disclosures).

Step semantics:
  - DONE / SKIPPED steps are not re-run on resume.
  - WAITING marks a step held up by an external party but does NOT halt the
    run — later steps continue (the TC pulls tax maps while the client fills
    out disclosures). WAITING steps re-run on resume so they can clear.
  - BLOCKED halts the run — nothing downstream executes (e.g. verification
    found critical issues; filing forms or drafting the MLS listing on bad
    data must not happen). The blocked step re-runs on resume.
  - FAILED halts the run; the failed step re-runs on resume.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from realtorai.storage.transaction_store import (
    Artifact,
    TransactionEnvelope,
    save_transaction,
)
from realtorai.workflows.intake import PaperworkDocument

logger = structlog.get_logger()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    WAITING = "waiting"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    FAILED = "failed"


class StepResult(BaseModel):
    """What a step function returns."""

    status: Literal[
        StepStatus.DONE, StepStatus.WAITING, StepStatus.BLOCKED, StepStatus.SKIPPED
    ] = StepStatus.DONE
    detail: str | None = None


class StepState(BaseModel):
    key: str
    title: str
    status: StepStatus = StepStatus.PENDING
    detail: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkflowState(BaseModel):
    name: str
    status: Literal["running", "waiting", "blocked", "done", "failed"] = "running"
    steps: list[StepState] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def step(self, key: str) -> StepState:
        for s in self.steps:
            if s.key == key:
                return s
        raise KeyError(key)


class WorkflowContext:
    """Everything the steps need, plus persistence helpers."""

    def __init__(
        self,
        envelope: TransactionEnvelope,
        *,
        documents: list[PaperworkDocument] | None = None,
        paperwork_files: list[tuple[str, bytes]] | None = None,
    ):
        self.envelope = envelope
        self.documents = documents or []
        # (file_name, content) pairs of the signed paperwork to file into the room
        self.paperwork_files = paperwork_files or []
        self.state: WorkflowState | None = None

    @property
    def record(self):
        return self.envelope.record

    def save(self) -> None:
        if self.state is not None:
            self.state.updated_at = _now()
            self.envelope.workflow = self.state.model_dump(mode="json")
        save_transaction(self.envelope)

    def add_artifact(self, name: str, path: str, kind: str, uploaded: bool = False) -> None:
        # Replace a previous artifact of the same name on re-runs
        self.envelope.artifacts = [a for a in self.envelope.artifacts if a.name != name]
        self.envelope.artifacts.append(
            Artifact(name=name, path=path, kind=kind, uploaded_to_room=uploaded)
        )


StepFn = Callable[[WorkflowContext], Awaitable[StepResult]]


class Step(BaseModel):
    key: str
    title: str

    model_config = {"arbitrary_types_allowed": True}


async def run_workflow(
    name: str,
    steps: list[tuple[Step, StepFn]],
    ctx: WorkflowContext,
) -> WorkflowState:
    """Run (or resume) a workflow. Returns the final state."""
    # Load prior state from the envelope, or initialize
    if ctx.envelope.workflow and ctx.envelope.workflow.get("name") == name:
        state = WorkflowState.model_validate(ctx.envelope.workflow)
        # New steps added since last run get appended
        known = {s.key for s in state.steps}
        for step, _ in steps:
            if step.key not in known:
                state.steps.append(StepState(key=step.key, title=step.title))
    else:
        state = WorkflowState(
            name=name,
            steps=[StepState(key=step.key, title=step.title) for step, _ in steps],
        )
    ctx.state = state
    state.status = "running"
    ctx.save()

    failed = False
    for step, fn in steps:
        step_state = state.step(step.key)
        if step_state.status in (StepStatus.DONE, StepStatus.SKIPPED):
            continue

        step_state.status = StepStatus.RUNNING
        step_state.started_at = step_state.started_at or _now()
        ctx.save()
        logger.info("workflow_step_start", workflow=name, step=step.key)

        try:
            result = await fn(ctx)
        except Exception as e:
            step_state.status = StepStatus.FAILED
            step_state.detail = str(e)
            step_state.finished_at = _now()
            logger.error("workflow_step_failed", workflow=name, step=step.key, error=str(e))
            failed = True
            ctx.save()
            break

        step_state.status = result.status
        step_state.detail = result.detail
        step_state.finished_at = _now()
        ctx.save()
        logger.info(
            "workflow_step_end",
            workflow=name,
            step=step.key,
            status=result.status.value,
            detail=result.detail,
        )
        if result.status == StepStatus.BLOCKED:
            break

    if failed:
        state.status = "failed"
    elif any(s.status == StepStatus.BLOCKED for s in state.steps):
        state.status = "blocked"
    elif any(s.status == StepStatus.WAITING for s in state.steps):
        state.status = "waiting"
    else:
        state.status = "done"
    ctx.save()
    logger.info("workflow_finished", workflow=name, status=state.status)
    return state
