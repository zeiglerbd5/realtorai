"""Chat routes — the dashboard copilot (Claude tool-calling agent).

The chat tab is the same agent that runs queue-task threads, minus a pinned
task: it reads live state (transactions, MLS readiness, the approval queue,
the playbook) and its only write is propose_workflow, which files a pending
task for human approval. See orchestration/copilot.py for the permission
model.
"""

import html
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.orchestration.copilot import run_dashboard_turn

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

# Conversation memory (single-user local app)
_conversation_history: list[dict[str, str]] = []
MAX_HISTORY_MESSAGES = 20  # Keep last N messages to manage context window

_OFFLINE_MESSAGE = (
    "The dashboard copilot runs on the Claude API — set ANTHROPIC_API_KEY to chat."
)


def add_to_history(role: str, content: str) -> None:
    """Add a message to conversation history."""
    _conversation_history.append({"role": role, "content": content})
    while len(_conversation_history) > MAX_HISTORY_MESSAGES:
        _conversation_history.pop(0)


def clear_history() -> None:
    """Clear conversation history."""
    _conversation_history.clear()


@router.get("/", response_class=HTMLResponse)
async def get_chat(request: Request) -> HTMLResponse:
    """Get the chat interface."""
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"request": request},
    )


@router.post("/clear")
async def clear_chat() -> JSONResponse:
    """Clear conversation history."""
    clear_history()
    return JSONResponse({"status": "cleared"})


@router.post("/send", response_class=HTMLResponse)
async def send_message(
    request: Request,
    message: str = Form(...),
) -> HTMLResponse:
    """Send a chat message and get a complete response (non-streaming)."""
    if not get_claude_engine().available:
        response_text = _OFFLINE_MESSAGE
    else:
        add_to_history("user", message)
        response_text = "…"
        async for kind, payload in run_dashboard_turn(list(_conversation_history)):
            if kind == "text":
                response_text = payload
        add_to_history("assistant", response_text)

    return templates.TemplateResponse(
        request,
        "components/chat_message.html",
        {
            "user_message": message,
            "assistant_message": response_text,
        },
    )


@router.post("/stream")
async def stream_message(message: str = Form(...)) -> StreamingResponse:
    """Stream a chat response (Server-Sent Events).

    Tool calls stream as status lines while the agent works, then the final
    reply. Protocol matches the existing front-end: `data: <html chunk>` lines
    terminated by `data: [DONE]`.
    """

    async def event_stream():
        if not get_claude_engine().available:
            yield f"data: {_OFFLINE_MESSAGE}\n\n"
            yield "data: [DONE]\n\n"
            return

        add_to_history("user", message)
        final_text = "…"
        try:
            async for kind, payload in run_dashboard_turn(list(_conversation_history)):
                if kind == "tool":
                    label = payload.replace("_", " ")
                    yield f"data: <em class='tool-note'>· {label}…</em><br>\n\n"
                else:
                    final_text = payload
                    escaped = html.escape(payload).replace("\n", "<br>")
                    yield f"data: {escaped}\n\n"
        except Exception as e:
            final_text = f"Copilot error: {e}"
            yield f"data: {html.escape(final_text)}\n\n"
        add_to_history("assistant", final_text)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
