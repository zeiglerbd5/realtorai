"""Chat routes - conversational interface."""

from pathlib import Path
from typing import List, Dict

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from realtorai.inference.engine import get_engine
from realtorai.inference.prompts import get_conversation_prompt_with_rag
from realtorai.inference.tools import FULL_TOOL_SET
from realtorai.orchestration.dispatcher import dispatcher

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

# Conversation memory (single-user local app)
# Stores list of {"role": "user"|"assistant", "content": "..."}
_conversation_history: List[Dict[str, str]] = []
MAX_HISTORY_MESSAGES = 20  # Keep last N messages to manage context window


def add_to_history(role: str, content: str):
    """Add a message to conversation history."""
    _conversation_history.append({"role": role, "content": content})
    # Trim to max size (keep most recent)
    while len(_conversation_history) > MAX_HISTORY_MESSAGES:
        _conversation_history.pop(0)


def get_history_for_prompt() -> List[Dict[str, str]]:
    """Get conversation history formatted for the prompt."""
    return list(_conversation_history)


def clear_history():
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
async def clear_chat():
    """Clear conversation history."""
    clear_history()
    return JSONResponse({"status": "cleared"})


@router.post("/send", response_class=HTMLResponse)
async def send_message(
    request: Request,
    message: str = Form(...),
) -> HTMLResponse:
    """Send a chat message and get a response."""
    engine = await get_engine()

    # Get RAG-augmented prompt for knowledge-aware responses
    system_prompt, augmented_message = get_conversation_prompt_with_rag(message)

    # First, check if this looks like a task that needs tools
    tool_result = await engine.call_tool(
        prompt=augmented_message,
        tools=FULL_TOOL_SET,
        system_prompt=system_prompt,
    )

    if tool_result.get("tool"):
        # A tool was called - dispatch it
        tool_name = tool_result["tool"]
        tool_args = tool_result.get("arguments", {})

        dispatch_result = await dispatcher.dispatch_tool_call(tool_name, tool_args)

        if dispatch_result.get("status") == "queued":
            response_text = (
                f"I've added that to your approval queue. "
                f"Task ID: {dispatch_result.get('task_id')}"
            )
        else:
            response_text = f"I tried to {tool_name}, but: {dispatch_result.get('error', 'unknown error')}"

    else:
        # No tool call - just generate a response with RAG context
        response_text = await engine.generate(
            prompt=augmented_message,
            system_prompt=system_prompt,
        )

    return templates.TemplateResponse(
        request,
        "components/chat_message.html",
        {
            "user_message": message,
            "assistant_message": response_text,
        },
    )


@router.post("/stream")
async def stream_message(message: str = Form(...)):
    """Stream a chat response (Server-Sent Events)."""
    from mlx_lm import stream_generate
    from mlx_lm.sample_utils import make_sampler
    from realtorai.config.settings import get_settings

    # Add user message to history
    add_to_history("user", message)

    # Get RAG-augmented prompt (uses current message for retrieval)
    system_prompt, augmented_message = get_conversation_prompt_with_rag(message)

    # Get the cached engine (loads model once)
    engine = await get_engine()
    settings = get_settings()

    # Check if this needs a web search (simple heuristic)
    web_context = ""
    search_keywords = [
        "current", "right now", "today", "latest", "market",
        "homes for sale", "listings", "mortgage rate", "price",
        "what are", "how much", "find me", "search for", "look up",
        "find homes", "houses for sale", "properties", "for sale",
        "zillow", "redfin", "realtor", "mls",
        "selling for", "listed", "available",
        "homes in", "houses in", "home over", "homes over", "homes under",
        "real estate", "buy a home", "buy a house"
    ]
    needs_search = any(kw in message.lower() for kw in search_keywords)

    if needs_search:
        # Run web search and add results to context
        from realtorai.integrations.web import web_search
        import structlog
        log = structlog.get_logger()

        # Build a better search query for real estate
        search_query = message
        msg_lower = message.lower()

        # If it looks like a real estate search, append zillow to get better results
        if any(kw in msg_lower for kw in ["home", "house", "property", "listing", "for sale"]):
            search_query = f"{message} zillow"

        log.info("web_search_triggered", query=search_query[:80])

        results = web_search(search_query, max_results=5)
        log.info("web_search_results", count=len(results) if results else 0)

        if results:
            # Just grab the top result's URL directly
            top_url = results[0].get("href", results[0].get("url", ""))
            top_title = results[0].get("title", "Link")
            top_body = results[0].get("body", "")

            web_context = f"""

[I found this for you:]
{top_title}
{top_url}
{top_body}

Reply in 1-2 sentences summarizing what you found. End with: Check it out here: {top_url}"""

    # Collect full response for history
    full_response = []

    def generate_stream():
        """Sync generator that yields SSE events."""
        sampler = make_sampler(temp=settings.model_temperature)

        # Build messages with conversation history
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history (excluding the just-added user message)
        history = get_history_for_prompt()
        for msg in history[:-1]:  # All but the last (current) message
            messages.append(msg)

        # Add current message with RAG context + web results
        final_message = augmented_message + web_context
        messages.append({"role": "user", "content": final_message})

        prompt = engine._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

        # DEBUG: Log the actual prompt being sent
        import structlog
        debug_log = structlog.get_logger()
        debug_log.info("PROMPT_DEBUG", prompt_length=len(prompt), last_500_chars=prompt[-500:])

        in_thinking = False
        for response in stream_generate(engine._model, engine._tokenizer, prompt=prompt, max_tokens=settings.model_max_tokens, sampler=sampler):
            text = response.text
            full_response.append(text)

            # Filter out <think>...</think> blocks from Qwen3
            if "<think>" in text:
                in_thinking = True
            if in_thinking:
                if "</think>" in text:
                    in_thinking = False
                    # Get any text after </think>
                    text = text.split("</think>", 1)[-1]
                    if not text.strip():
                        continue
                else:
                    continue  # Skip thinking content

            # Convert newlines for HTML
            escaped = text.replace("\n", "<br>")
            yield f"data: {escaped}\n\n"

        # Add assistant response to history
        add_to_history("assistant", "".join(full_response))

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
