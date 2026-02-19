"""Action routes - approve, edit, reject tasks."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from realtorai.orchestration.approval import approval_loop
from realtorai.orchestration.queue import task_queue

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.post("/{task_id}/approve", response_class=HTMLResponse)
async def approve_task(request: Request, task_id: str) -> HTMLResponse:
    """Approve a task as-is."""
    task = await task_queue.get_task(task_id)

    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    success = await approval_loop.approve(task)

    if success:
        return templates.TemplateResponse(
            "components/action_result.html",
            {
                "request": request,
                "success": True,
                "message": "Task approved and executed",
                "task_id": task_id,
            },
        )
    else:
        return templates.TemplateResponse(
            "components/action_result.html",
            {
                "request": request,
                "success": False,
                "message": "Task execution failed",
                "task_id": task_id,
            },
        )


@router.post("/{task_id}/edit", response_class=HTMLResponse)
async def edit_task(
    request: Request,
    task_id: str,
    subject: str = Form(None),
    body: str = Form(None),
) -> HTMLResponse:
    """Edit and approve a task."""
    task = await task_queue.get_task(task_id)

    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    # Build edited content
    edited_content: dict[str, Any] = {}
    if task.proposal_data.get("draft_response"):
        edited_draft = task.proposal_data["draft_response"].copy()
        if subject:
            edited_draft["subject"] = subject
        if body:
            edited_draft["body"] = body
        edited_content["draft_response"] = edited_draft

    success = await approval_loop.approve_with_edits(task, edited_content)

    if success:
        return templates.TemplateResponse(
            "components/action_result.html",
            {
                "request": request,
                "success": True,
                "message": "Task approved with edits and executed",
                "task_id": task_id,
            },
        )
    else:
        return templates.TemplateResponse(
            "components/action_result.html",
            {
                "request": request,
                "success": False,
                "message": "Task execution failed",
                "task_id": task_id,
            },
        )


@router.post("/{task_id}/reject", response_class=HTMLResponse)
async def reject_task(
    request: Request,
    task_id: str,
    reason: str = Form(None),
) -> HTMLResponse:
    """Reject a task."""
    task = await task_queue.get_task(task_id)

    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    await approval_loop.reject(task, reason)

    return templates.TemplateResponse(
        "components/action_result.html",
        {
            "request": request,
            "success": True,
            "message": "Task rejected",
            "task_id": task_id,
        },
    )


@router.get("/{task_id}/edit-form", response_class=HTMLResponse)
async def get_edit_form(request: Request, task_id: str) -> HTMLResponse:
    """Get the edit form for a task."""
    task = await task_queue.get_task(task_id)

    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    return templates.TemplateResponse(
        "components/edit_form.html",
        {
            "request": request,
            "task": task,
        },
    )
