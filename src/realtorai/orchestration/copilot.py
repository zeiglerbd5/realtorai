"""The scoping copilot — a tool-calling Sonnet agent for queue tasks and chat.

Two modes share one agent core and one permission model:

  TASK mode      -> the thread on a WORKFLOW_KICKOFF queue task. Read tools
                    answer questions; plan_workflow only queues scope on the
                    task. Execution happens when the operator gives the word
                    (conversation.handle_reply) — plain code, never the model.
  DASHBOARD mode -> the Chat tab. Same read tools, no task pinned. Its only
                    mutation is propose_workflow, which files a NEW pending
                    task in the approval queue — so anything born in chat
                    still passes the same human gate before running.

The permission split is structural: execution tools do not exist in either
mode. "Nothing runs without a human" is enforced by what the agent physically
cannot call, not by prompt obedience.
"""

import inspect
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import structlog

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.schemas.mls_required import readiness
from realtorai.schemas.tasks import Task
from realtorai.storage.transaction_store import list_transactions, load_transaction

logger = structlog.get_logger()

MAX_AGENT_ITERATIONS = 8

# How much of an intake document the scoping agent may pull into the thread.
# Sized against the forms this bundle actually carries: a Maine ERTS runs ~18.5k
# characters, with compensation on page 2 and the term dates on page 3 — the old
# 4k cut off 255 characters into page 2, so the agent answered about commission
# and expiration from the page-1 disclosure boilerplate instead of the operative
# terms. 16k reaches the end of page 4 and stops inside the wire-fraud advisory,
# which carries nothing worth scoping. Extraction is unaffected either way; it
# reads the full text via workflows.intake._documents_block.
INTAKE_READ_LIMIT = 16_000

_READ_TOOL_SCHEMAS: list[dict[str, Any]] = [
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
        "name": "search_knowledge_base",
        "description": "Semantic search over the ingested knowledge base: Maine "
        "license law (Title 32 Ch. 114), Real Estate Commission rules, the NAR "
        "Code of Ethics, the team's policies manual, and email templates. Hits "
        "carry [source — section] citations; cite them in answers. Prefer "
        "kind=policies/templates day to day; kind=legal only for actual "
        "legal or compliance questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["legal", "templates", "policies"],
                    "description": "Optionally restrict to one source kind",
                },
            },
            "required": ["query"],
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
]

TASK_TOOL_SCHEMAS: list[dict[str, Any]] = _READ_TOOL_SCHEMAS + [
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
        "planned work executes only when the operator gives the word. "
        "kind=intake (default) starts a new client workflow; "
        "kind=under_contract / kind=closing run those phase changes on an "
        "EXISTING transaction and require transaction_slug (find it via "
        "list_active_transactions).",
        "input_schema": {
            "type": "object",
            "properties": {
                "side": {"type": "string", "enum": ["listing", "buyer"]},
                "kind": {"type": "string", "enum": ["intake", "under_contract", "closing"]},
                "transaction_slug": {"type": "string"},
                "client_name": {"type": "string"},
                "property_address": {"type": "string"},
                "note": {
                    "type": "string",
                    "description": "Scoping notes for extraction (amendments, focus)",
                },
            },
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

DASHBOARD_TOOL_SCHEMAS: list[dict[str, Any]] = _READ_TOOL_SCHEMAS + [
    {
        "name": "list_pending_tasks",
        "description": "List the tasks currently waiting in the approval queue.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "propose_workflow",
        "description": "File a NEW workflow proposal in the approval queue. It does "
        "NOT run — the TC reviews and approves it on the Queue tab like any other "
        "proposal.",
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
]


TASK_SYSTEM_PROMPT = """You are the queue copilot for a Maine real-estate transaction \
coordinator (TC). A proposed piece of work is pending on the approval queue and you \
are talking it through with the TC — scoping exactly what should run.

The machinery you scope for: per-client workflows that create a DocuSign \
Transaction Rooms room + task list, file the paperwork, generate agency forms, \
pull public records (tax card, tax map, flood map, deed with restriction review), \
and draft the MLS listing.

Hard rules of this conversation:
- You CANNOT execute anything. Your plan_workflow tool only queues scope; the \
system runs the planned work when the TC explicitly gives the word (or clicks \
Approve). Never claim something ran.
- Plan one workflow per client/property. If the intake mentions several, plan \
each.
- Use your read tools instead of guessing — check transaction status, MLS \
readiness, the playbook, or the intake documents before answering questions about \
them.
- If the TC references local paperwork by path, attach it with attach_local_file.
- Capture amendments ("only do 12 Birch", "sellers are the Larsons") in the \
planned workflow's note field — extraction treats those notes as authoritative.
- Be brief and concrete, like a sharp colleague in a work chat. End with what \
you're waiting on when the plan is ready ("say the word and I'll run both").

Current task context:
{context}"""

DASHBOARD_SYSTEM_PROMPT = """You are the dashboard copilot for a Maine real-estate \
transaction coordinator (TC) — the chat tab of their workflow console.

You can look up live state (transactions, workflow steps, MLS readiness, the \
approval queue) and search the team playbook. Use tools instead of guessing.

You CANNOT execute anything. Your only write tool, propose_workflow, files a new \
proposal in the approval queue — the TC approves it there before anything runs. \
When you propose, say so and point them at the Queue tab.

Be brief and concrete, like a sharp colleague in a work chat."""


def _read_tool_impls() -> dict[str, Any]:
    """Read-only lookups shared by both modes."""

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

    def search_knowledge_base(query: str, kind: str | None = None) -> str:
        from realtorai.rag.retrieval import search_knowledge

        return search_knowledge(query, kind=kind)

    return {
        "list_active_transactions": list_active_transactions,
        "transaction_status": transaction_status,
        "mls_readiness": mls_readiness_tool,
        "search_playbook": search_playbook,
        "search_knowledge_base": search_knowledge_base,
    }


def _task_tool_impls(task: Task, state: dict[str, Any]) -> dict[str, Any]:
    """Task-mode tools closed over this task's mutable state.

    `state` holds `planned_actions` (the plan) and `attachments` (names added
    to the bundle); the caller persists it after the turn.
    """
    intake_dir = (
        Path(task.proposal_data["intake_dir"])
        if task.proposal_data.get("intake_dir")
        else None
    )

    def read_intake_document(name: str) -> str:
        from realtorai.workflows.intake import paperwork_from_bytes

        if intake_dir is None or not intake_dir.exists():
            return "This task has no intake bundle."
        path = intake_dir / Path(name).name
        if not path.exists():
            names = [p.name for p in intake_dir.iterdir()]
            return f"No file '{name}' in the bundle. Available: {', '.join(names)}"
        text = paperwork_from_bytes(path.name, path.read_bytes()).text
        if not text:
            return "(no extractable text)"
        if len(text) <= INTAKE_READ_LIMIT:
            return text
        # Say so explicitly — a silent cut lets the agent answer confidently
        # from a partial document without knowing anything is missing.
        return (
            text[:INTAKE_READ_LIMIT]
            + f"\n\n[truncated: showing the first {INTAKE_READ_LIMIT:,} of "
            f"{len(text):,} characters]"
        )

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
        side: str | None = None,
        kind: str = "intake",
        transaction_slug: str | None = None,
        client_name: str | None = None,
        property_address: str | None = None,
        note: str | None = None,
    ) -> str:
        planned = state.setdefault("planned_actions", [])
        if kind in ("under_contract", "closing"):
            if not transaction_slug:
                return f"{kind} needs transaction_slug — check " \
                       "list_active_transactions for the deal."
            from realtorai.storage.transaction_store import load_transaction

            if load_transaction(transaction_slug) is None:
                return f"No transaction '{transaction_slug}' — check " \
                       "list_active_transactions."
        elif side not in ("listing", "buyer"):
            return "intake needs side='listing' or 'buyer'."
        planned.append(
            {
                "kind": kind,
                "side": side,
                "transaction_slug": transaction_slug,
                "client_name": client_name,
                "property_address": property_address,
                "note": note,
            }
        )
        what = (
            f"{kind.replace('_', '-')} phase on {transaction_slug}"
            if kind in ("under_contract", "closing")
            else f"{side} workflow — {client_name or '?'}, {property_address or '?'}"
        )
        return f"Planned #{len(planned)}: {what}. Runs on the operator's word."

    def unplan_workflow(index: int) -> str:
        planned = state.setdefault("planned_actions", [])
        if not 1 <= index <= len(planned):
            return f"No planned workflow #{index}."
        removed = planned.pop(index - 1)
        return f"Removed planned {removed.get('side')} — {removed.get('client_name')}."

    return {
        **_read_tool_impls(),
        "read_intake_document": read_intake_document,
        "attach_local_file": attach_local_file,
        "plan_workflow": plan_workflow,
        "unplan_workflow": unplan_workflow,
    }


def _dashboard_tool_impls() -> dict[str, Any]:
    """Dashboard-mode tools: read everything, propose into the queue only."""

    async def list_pending_tasks() -> str:
        from realtorai.orchestration.queue import task_queue

        tasks = await task_queue.get_pending()
        if not tasks:
            return "The approval queue is empty."
        return "\n".join(
            f"- [{t.task_type.value}] {t.title} ({t.summary})" for t in tasks
        )

    async def propose_workflow(
        side: str,
        client_name: str | None = None,
        property_address: str | None = None,
        note: str | None = None,
    ) -> str:
        import uuid

        from realtorai.config.settings import get_settings
        from realtorai.orchestration.queue import task_queue
        from realtorai.schemas.tasks import TaskType

        intake_dir = (
            get_settings().data_dir / "intake" / f"intake_{uuid.uuid4().hex[:10]}"
        )
        intake_dir.mkdir(parents=True, exist_ok=True)
        who = client_name or "client TBD"
        where = property_address or "address TBD"
        task_id = await task_queue.add_custom_task(
            task_type=TaskType.WORKFLOW_KICKOFF,
            title=f"New {side} client — start intake workflow?",
            summary=f"{who} — {where} (proposed from dashboard chat)",
            details={
                "client_name": client_name,
                "property_address": property_address,
                "source": "dashboard_chat",
            },
            proposal_data={
                "action": "run_intake_workflow",
                "side": side,
                "intake_dir": str(intake_dir),
                "client_name": client_name,
                "conversation": [
                    {
                        "role": "agent",
                        "text": f"Proposed from dashboard chat: {side} workflow for "
                        f"{who} — {where}."
                        + (f" Note: {note}" if note else "")
                        + " Attach paperwork by path here, then give the word.",
                    }
                ],
                "planned_actions": [
                    {
                        "side": side,
                        "client_name": client_name,
                        "property_address": property_address,
                        "note": note,
                    }
                ],
            },
            confidence="high",
        )
        return (
            f"Proposed: task {task_id} is now pending in the approval queue. "
            "Nothing runs until the TC approves it there."
        )

    return {
        **_read_tool_impls(),
        "list_pending_tasks": list_pending_tasks,
        "propose_workflow": propose_workflow,
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
        role = "assistant" if msg.get("role") in ("agent", "assistant") else "user"
        text = msg.get("text") or msg.get("content") or ""
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += f"\n\n{text}"
        else:
            messages.append({"role": role, "content": text})
    return messages


async def _agent_loop(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    impls: dict[str, Any],
    system: str,
) -> AsyncIterator[tuple[str, str]]:
    """Drive the tool-use loop, yielding ("tool", name) per call and
    ("text", final_reply) once the model stops calling tools."""
    engine = get_claude_engine()
    text = ""
    for _ in range(MAX_AGENT_ITERATIONS):
        response = await engine.chat_with_tools(
            messages, tools=tools, system_prompt=system
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for call in tool_uses:
            yield "tool", call.name
            impl = impls.get(call.name)
            try:
                output = impl(**call.input) if impl else f"Unknown tool: {call.name}"
                if inspect.isawaitable(output):
                    output = await output
            except Exception as e:  # tool errors go back to the model, not the user
                logger.warning("copilot_tool_failed", tool=call.name, error=str(e))
                output = f"Tool error: {e}"
            logger.info("copilot_tool_call", tool=call.name, input=call.input)
            results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": str(output)}
            )
        messages.append({"role": "user", "content": results})
    yield "text", text or "…"


async def run_copilot_turn(
    task: Task, conversation: list[dict]
) -> tuple[str, dict[str, Any]]:
    """One task-mode agent turn (last message = the operator's).

    Returns (reply_text, state) where state carries planned_actions /
    attachments mutations for the caller to persist. Raises ClaudeEngineError
    when the API is unavailable — callers fall back to the offline canned path.
    """
    state: dict[str, Any] = {
        "planned_actions": list(task.proposal_data.get("planned_actions", [])),
    }
    impls = _task_tool_impls(task, state)
    messages = _conversation_messages(conversation)
    system = TASK_SYSTEM_PROMPT.format(context=_task_context(task, state))

    text = "…"
    async for kind, payload in _agent_loop(messages, TASK_TOOL_SCHEMAS, impls, system):
        if kind == "text":
            text = payload
    return text, state


async def run_dashboard_turn(
    history: list[dict],
) -> AsyncIterator[tuple[str, str]]:
    """One dashboard-mode agent turn as an event stream.

    Yields ("tool", name) as the agent works and ("text", reply) at the end —
    the chat route streams these to the browser.
    """
    impls = _dashboard_tool_impls()
    messages = _conversation_messages(history)
    async for event in _agent_loop(
        messages, DASHBOARD_TOOL_SCHEMAS, impls, DASHBOARD_SYSTEM_PROMPT
    ):
        yield event
