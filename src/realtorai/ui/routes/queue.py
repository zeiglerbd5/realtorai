"""Queue routes - viewing pending tasks."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from realtorai.orchestration.queue import task_queue

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def get_queue(request: Request) -> HTMLResponse:
    """Get the full queue page."""
    tasks = await task_queue.get_pending(limit=50)

    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "tasks": tasks,
            "count": len(tasks),
        },
    )


@router.get("/items", response_class=HTMLResponse)
async def get_queue_items(request: Request) -> HTMLResponse:
    """Get queue items partial (for HTMX refresh)."""
    tasks = await task_queue.get_pending(limit=50)

    return templates.TemplateResponse(
        request,
        "components/queue_items.html",
        {
            "tasks": tasks,
        },
    )


@router.get("/count", response_class=HTMLResponse)
async def get_queue_count() -> HTMLResponse:
    """Get pending task count badge."""
    count = await task_queue.count_pending()
    # Return full span with HTMX attributes for outerHTML swap
    badge_class = ' class="badge"' if count > 0 else ''
    badge_content = str(count) if count > 0 else ''
    return HTMLResponse(
        content=f'<span id="queue-badge" hx-get="/queue/count" '
                f'hx-trigger="load, every 30s" hx-swap="outerHTML"'
                f'{badge_class}>{badge_content}</span>'
    )


@router.get("/{task_id}", response_class=HTMLResponse)
async def get_task_detail(request: Request, task_id: str) -> HTMLResponse:
    """Get detailed view of a single task."""
    task = await task_queue.get_task(task_id)

    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "components/task_detail.html",
        {
            "task": task,
        },
    )
