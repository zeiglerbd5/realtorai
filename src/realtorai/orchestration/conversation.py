"""Conversational approval — the operator's thread on a pending queue task.

The thread has two layers with very different trust models:

  1. THE CHAT is a real tool-calling agent (orchestration/copilot.py). It
     answers questions with live lookups and scopes work by queueing
     planned workflows — but it has no execution tools at all.
  2. THE GATE is plain code. Only an explicit go-word from the operator
     ("yes", "go ahead", "run it", or the Approve button) fires the planned
     work, and only a no-word rejects. The model never decides to execute.

So the conversation queues up the scope of the task at hand; when the human
gives the word, the system kicks off and reports back what the machinery did.
"""

import re
from pathlib import Path
from typing import Any

import structlog

from realtorai.orchestration.approval import approval_loop
from realtorai.orchestration.queue import task_queue
from realtorai.schemas.tasks import ApprovalStatus, Task
from realtorai.storage.database import get_database

logger = structlog.get_logger()

_PATH_RE = re.compile(r"(?:~/|/)[^\s'\",;]+")
_GO_RE = re.compile(
    r"^\s*(yes|yep|yeah|approve[d]?|go ahead|go for it|go|run it|do it|ship it|"
    r"kick it off|send it|make it so)\b",
    re.IGNORECASE,
)
_NO_RE = re.compile(
    r"^\s*(no|nope|reject|don't|do not|hold off|stop|cancel|kill it)\b",
    re.IGNORECASE,
)

_OFFLINE_ANSWER = (
    "The chat copilot needs the Claude API (no key configured). "
    "Reply 'yes' to run the planned workflows or 'no' to reject the task."
)


def _extract_paths(reply: str) -> list[str]:
    return [p.rstrip(".!?)") for p in _PATH_RE.findall(reply)]


async def _persist(task: Task, proposal: dict[str, Any]) -> None:
    db = await get_database()
    await db.update_task_data(task.id, proposal, details=task.details)


def _attach_paths(
    task: Task, proposal: dict[str, Any], reply: str
) -> tuple[list[str], list[str]]:
    """Copy files the operator referenced into the intake bundle.

    Returns (attached_names, missing_raw_paths).
    """
    import shutil

    attached: list[str] = []
    missing: list[str] = []
    intake_dir = (
        Path(proposal["intake_dir"]) if proposal.get("intake_dir") else None
    )
    for raw in _extract_paths(reply):
        path = Path(raw).expanduser()
        if not path.exists():
            missing.append(raw)
        elif intake_dir and intake_dir.exists():
            shutil.copy2(path, intake_dir / path.name)
            attached.append(path.name)
    if attached:
        details = dict(task.details)
        details["attachments"] = sorted(set(details.get("attachments", []) + attached))
        task.details = details
    return attached, missing


async def handle_reply(task_id: str, reply: str) -> tuple[str, str]:
    """Process an operator reply on a pending task.

    Returns (outcome, message): outcome is "approved", "rejected", "answer",
    "failed", or "error"; message is the copilot's response for the thread.
    """
    task = await task_queue.get_task(task_id)
    if task is None:
        return "error", "Task not found."
    if task.status != ApprovalStatus.PENDING:
        return "error", f"Task is {task.status.value} — replies only work on pending tasks."

    proposal = dict(task.proposal_data)
    conversation = list(proposal.get("conversation", []))
    conversation.append({"role": "operator", "text": reply})
    proposal["conversation"] = conversation

    # ---- THE GATE: explicit go / no-go, matched by code, never by the model
    if _NO_RE.match(reply):
        response = "Understood — rejected. Nothing was run."
        conversation.append({"role": "agent", "text": response})
        await _persist(task, proposal)
        await approval_loop.reject(task, reason=reply)
        return "rejected", response

    if _GO_RE.match(reply):
        attached, missing = _attach_paths(task, proposal, reply)
        if missing:
            response = (
                f"I couldn't find {', '.join(missing)} — double-check the path and "
                "resend, and I'll run it."
            )
            conversation.append({"role": "agent", "text": response})
            await _persist(task, proposal)
            return "answer", response
        # anything beyond the bare go-word rides into extraction as amendments
        stripped = _GO_RE.sub("", reply).strip(" -—,.!")
        if stripped:
            existing = proposal.get("operator_instructions")
            proposal["operator_instructions"] = (
                f"{existing}\n{stripped}" if existing else stripped
            )
        await _persist(task, proposal)

        updated = await task_queue.get_task(task_id)
        assert updated is not None
        ok = await approval_loop.approve(updated)
        if not ok:
            return "failed", "Execution failed — see the log."
        after = await task_queue.get_task(task_id)
        narration = ""
        if after is not None:
            thread = after.proposal_data.get("conversation", [])
            if thread and thread[-1].get("role") == "agent":
                narration = thread[-1]["text"]
        return "approved", narration or "Done — workflow executed."

    # ---- THE CHAT: everything else goes to the scoping copilot
    from realtorai.inference.claude_engine import get_claude_engine
    from realtorai.orchestration.copilot import run_copilot_turn

    if not get_claude_engine().available:
        conversation.append({"role": "agent", "text": _OFFLINE_ANSWER})
        await _persist(task, proposal)
        return "answer", _OFFLINE_ANSWER

    try:
        text, state = await run_copilot_turn(task, conversation)
    except Exception as e:
        logger.warning("copilot_turn_failed", task_id=task_id, error=str(e))
        text = (
            "I hit an error talking to the model — try again, or reply 'yes' to "
            "run the planned workflows / 'no' to reject."
        )
        state = {}

    if state.get("planned_actions") is not None:
        proposal["planned_actions"] = state["planned_actions"]
    if state.get("attachments"):
        details = dict(task.details)
        details["attachments"] = sorted(
            set(details.get("attachments", []) + state["attachments"])
        )
        task.details = details
    conversation.append({"role": "agent", "text": text})
    await _persist(task, proposal)
    return "answer", text
