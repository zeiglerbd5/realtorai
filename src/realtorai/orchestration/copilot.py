"""The scoping copilot — a tool-calling Sonnet agent behind each queue task.

The conversation on a WORKFLOW_KICKOFF task is a real agent chat, not a
one-shot classifier. The agent can look things up (transactions, MLS
readiness, the team playbook, intake documents) and SCOPE work by queueing planned
workflows — but it can never execute them. The permission split is structural:

  READ tools     -> run inline during the chat turn
  SCOPING tools  -> mutate only the task's planned work / intake bundle
  EXECUTION      -> does not exist here. Planned work runs only when the
                    operator gives the word (a regex-matched go in
                    conversation.handle_reply, or the Approve button) —
                    plain Python fires the machinery, never the model.

So "nothing runs without a human" is enforced by what the agent physically
cannot call, not by prompt obedience.
"""

import shutil
from pathlib import Path
from typing import Any

import structlog

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.schemas.mls_required import readiness
from realtorai.schemas.tasks import Task
from realtorai.storage.transaction_store import list_transactions, load_transaction

logger = structlog.get_logger()

MAX_AGENT_ITERATIONS = 8

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_active_transactions",
        "description": "List all transactions the system is tracking (slug, address, "
        "side, workflow status).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "transaction_status",
        "description": "Workflow status detail for one transaction: step states, "
        "artifacts produced, what it's waiting on.",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "mls_readiness",
        "description": "MLS-required-field readiness for a transaction: how many of "
        "the 49 required fields are filled and which are missing.",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "search_playbook",
        "description": "Search the team's policies & procedures manual and email "
        "templates for how the office handles something.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_intake_document",
        "description": "Read the text of a document in this task's intake bundle.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "File name"}},
            "required": ["name"],
        },
    },
    {
        "name": "attach_local_file",
        "description": "Copy a local file (paperwork the operator pointed at) into "
        "this task's intake bundle so extraction can use it.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "plan_workflow",
        "description": "Add a workflow to this task's plan. It does NOT run — "
        "planned work executes only when the operator gives the word.",
        "input_schema": {
            "type": "object",
            "properties": {
                "side": {"type": "string", "enum": ["listing", "buyer"]},
                "client_name": {"type": "string"},
                "property_address": {"type": "string"},
                "note": {
                    "type": "string",
                    "description": "Scoping notes for extraction (amendments, focus)",
                },
            },
            "required": ["side"],
        },
    },
    {
        "name": "unplan_workflow",
        "description": "Remove a planned workflow from the plan by its 1-based index.",
        "input_schema": {
            "type": "object",
            "properties": {"index": {"type": "integer"}},
            "required": ["index"],
        },
    },
]


SYSTEM_PROMPT = """You are the queue copilot for a Maine real-estate transaction \
coordinator (TC). A proposed piece of work is pending on the approval queue and you \
are talking it through with the TC — scoping exactly what should run.

The machinery you scope for: per-client workflows that create a DocuSign \
Transaction Rooms room + task list, file the paperwork, generate agency forms, \
pull public records (tax card, tax map, flood map, deed with restriction review), \
and draft the MLS listing.

Hard rules of this conversation:
- You CANNOT execute anything. Your plan_workflow tool only queues scope; the \
system runs the planned work when the TC explicitly gives the word (or clicks Approve). \
Never claim something ran.
- Plan one workflow per client/property. If the intake mentions several, plan \
each.
- Use your read tools instead of guessing — check transaction status, MLS \
readiness, the playbook, or the intake documents before answering questions about \
them.
- If the TC references local paperwork by path, attach it with attach_local_file.
- Capture amendments ("only do 12 Birch", "sellers are the Larsons") in the planned \
workflow's note field — extraction treats those notes as authoritative.
- Be brief and concrete, like a sharp colleague in a work chat. End with what \
you're waiting on when the plan is ready ("say the word and I'll run both").

Current task context:
{context}"""


def _tool_impls(task: Task, state: dict[str, Any]) -> dict[str, Any]:
    """Build tool implementations closed over this task's mutable state.

    `state` holds `planned_actions` (the plan), `attachments` (names added to
    the bundle), and is persisted by the caller after the turn.
    """
    intake_dir = (
        Path(task.proposal_data["intake_dir"])
        if task.proposal_data.get("intake_dir")
        else None
    )

    def list_active_transactions() -> str:
        envelopes = list_transactions()
        if not envelopes:
            return "No transactions tracked yet."
        lines = []
        for env in envelopes:
            status = (env.workflow or {}).get("status", "?")
            lines.append(
                f"- {env.slug}: {env.record.street_address}, "
                f"{env.record.city or '?'} ({env.record.representation_side}; "
                f"workflow {status})"
            )
        return "\n".join(lines)

    def transaction_status(slug: str) -> str:
        env = load_transaction(slug)
        if env is None:
            return f"No transaction with slug '{slug}'."
        lines = [f"{env.slug} — workflow {(env.workflow or {}).get('status', '?')}"]
        for step in (env.workflow or {}).get("steps", []):
            detail = f" — {step.get('detail')}" if step.get("detail") else ""
            lines.append(
                f"  [{step.get('status')}] {step.get('title') or step.get('key')}{detail}"
            )
        if env.artifacts:
            lines.append(f"Artifacts: {', '.join(a.name for a in env.artifacts)}")
        return "\n".join(lines)

    def mls_readiness_tool(slug: str) -> str:
        env = load_transaction(slug)
        if env is None:
            return f"No transaction with slug '{slug}'."
        ready, total, missing = readiness(env.record)
        head = f"{ready}/{total} MLS-required fields ready."
        return f"{head} Missing: {', '.join(missing)}" if missing else head

    def search_playbook(query: str) -> str:
        from realtorai.config.settings import get_settings

        docs_dir = get_settings().data_dir.parent / "docs"
        candidates = [
            Path("docs/policies_and_procedures.md"),
            Path("docs/email_templates.md"),
            docs_dir / "policies_and_procedures.md",
            docs_dir / "email_templates.md",
        ]
        terms = [t.lower() for t in query.split() if len(t) > 2]
        hits: list[str] = []
        seen: set[Path] = set()
        for doc in candidates:
            if not doc.exists() or doc.resolve() in seen:
                continue
            seen.add(doc.resolve())
            lines = doc.read_text().splitlines()
            for i, line in enumerate(lines):
                if any(t in line.lower() for t in terms):
                    window = "\n".join(lines[max(0, i - 2) : i + 3])
                    hits.append(f"[{doc.name}]\n{window}")
                if len(hits) >= 6:
                    break
        return "\n---\n".join(hits) if hits else "No playbook matches."

    def read_intake_document(name: str) -> str:
        from realtorai.workflows.intake import paperwork_from_bytes

        if intake_dir is None or not intake_dir.exists():
            return "This task has no intake bundle."
        path = intake_dir / Path(name).name
        if not path.exists():
            names = [p.name for p in intake_dir.iterdir()]
            return f"No file '{name}' in the bundle. Available: {', '.join(names)}"
        text = paperwork_from_bytes(path.name, path.read_bytes()).text
        return text[:4000] or "(no extractable text)"

    def attach_local_file(path: str) -> str:
        source = Path(path).expanduser()
        if not source.exists():
            return f"NOT FOUND: {path} — ask the operator to check the path."
        if intake_dir is None or not intake_dir.exists():
            return "This task has no intake bundle to attach into."
        shutil.copy2(source, intake_dir / source.name)
        state.setdefault("attachments", []).append(source.name)
        return f"Attached {source.name} to the intake bundle."

    def plan_workflow(
        side: str,
        client_name: str | None = None,
        property_address: str | None = None,
        note: str | None = None,
    ) -> str:
        planned = state.setdefault("planned_actions", [])
        planned.append(
            {
                "side": side,
                "client_name": client_name,
                "property_address": property_address,
                "note": note,
            }
        )
        return f"Planned #{len(planned)}: {side} workflow — {client_name or '?'}, " \
               f"{property_address or '?'}. Runs on the operator's word."

    def unplan_workflow(index: int) -> str:
        planned = state.setdefault("planned_actions", [])
        if not 1 <= index <= len(planned):
            return f"No planned workflow #{index}."
        removed = planned.pop(index - 1)
        return f"Removed planned {removed.get('side')} — {removed.get('client_name')}."

    return {
        "list_active_transactions": list_active_transactions,
        "transaction_status": transaction_status,
        "mls_readiness": mls_readiness_tool,
        "search_playbook": search_playbook,
        "read_intake_document": read_intake_document,
        "attach_local_file": attach_local_file,
        "plan_workflow": plan_workflow,
        "unplan_workflow": unplan_workflow,
    }


def _task_context(task: Task, state: dict[str, Any]) -> str:
    intake_dir = task.proposal_data.get("intake_dir")
    bundle = []
    if intake_dir and Path(intake_dir).exists():
        bundle = sorted(
            p.name for p in Path(intake_dir).iterdir() if p.name != "email.json"
        )
    planned = state.get("planned_actions", [])
    planned_lines = [
        f"  {i}. {s.get('side')} — {s.get('client_name') or '?'}, "
        f"{s.get('property_address') or '?'}"
        + (f" (note: {s['note']})" if s.get("note") else "")
        for i, s in enumerate(planned, 1)
    ]
    return (
        f"Task: {task.title}\n"
        f"Summary: {task.summary}\n"
        f"Details: {task.details}\n"
        f"Intake bundle files: {', '.join(bundle) or '(none — no paperwork yet)'}\n"
        f"Planned work:\n" + ("\n".join(planned_lines) if planned_lines else "  (empty)")
    )


def _conversation_messages(conversation: list[dict]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for msg in conversation:
        role = "assistant" if msg.get("role") == "agent" else "user"
        text = msg.get("text", "")
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += f"\n\n{text}"
        else:
            messages.append({"role": role, "content": text})
    return messages


async def run_copilot_turn(
    task: Task, conversation: list[dict]
) -> tuple[str, dict[str, Any]]:
    """One agent turn over the task's thread (last message = the operator's).

    Returns (reply_text, state) where state carries planned_actions /
    attachments mutations for the caller to persist. Raises ClaudeEngineError
    when the API is unavailable — callers fall back to the offline canned path.
    """
    engine = get_claude_engine()
    state: dict[str, Any] = {
        "planned_actions": list(task.proposal_data.get("planned_actions", [])),
    }
    impls = _tool_impls(task, state)
    messages = _conversation_messages(conversation)

    text = ""
    for _ in range(MAX_AGENT_ITERATIONS):
        system = SYSTEM_PROMPT.format(context=_task_context(task, state))
        response = await engine.chat_with_tools(
            messages, tools=TOOL_SCHEMAS, system_prompt=system
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for call in tool_uses:
            impl = impls.get(call.name)
            try:
                output = impl(**call.input) if impl else f"Unknown tool: {call.name}"
            except Exception as e:  # tool errors go back to the model, not the user
                logger.warning("copilot_tool_failed", tool=call.name, error=str(e))
                output = f"Tool error: {e}"
            logger.info("copilot_tool_call", tool=call.name, input=call.input)
            results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": str(output)}
            )
        messages.append({"role": "user", "content": results})

    return text or "…", state
