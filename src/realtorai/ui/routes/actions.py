"""Action routes - approve, edit, reject tasks."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from realtorai.orchestration.approval import approval_loop
from realtorai.orchestration.queue import task_queue
from realtorai.schemas.tasks import TaskType

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
            request,
            "components/action_result.html",
            {
                "success": True,
                "message": "Task approved and executed",
                "task_id": task_id,
            },
        )
    else:
        return templates.TemplateResponse(
            request,
            "components/action_result.html",
            {
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
            request,
            "components/action_result.html",
            {
                "success": True,
                "message": "Task approved with edits and executed",
                "task_id": task_id,
            },
        )
    else:
        return templates.TemplateResponse(
            request,
            "components/action_result.html",
            {
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
        request,
        "components/action_result.html",
        {
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

    # Use extraction-specific form for extraction tasks
    if task.task_type in (TaskType.EXTRACTION_MLS, TaskType.EXTRACTION_TRANSACTION):
        return templates.TemplateResponse(
            request,
            "components/extraction_edit_form.html",
            {
                "task": task,
            },
        )

    return templates.TemplateResponse(
        request,
        "components/edit_form.html",
        {
            "task": task,
        },
    )


@router.get("/{task_id}/detail", response_class=HTMLResponse)
async def get_task_detail(request: Request, task_id: str) -> HTMLResponse:
    """Get the task detail view (used when canceling edit)."""
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


@router.post("/{task_id}/edit-extraction", response_class=HTMLResponse)
async def edit_extraction(request: Request, task_id: str) -> HTMLResponse:
    """Edit and approve an extraction task."""
    task = await task_queue.get_task(task_id)

    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    # Parse form data
    form_data = await request.form()

    # Build edited changes from form
    edited_changes = []
    original_changes = task.details.get("changes", [])

    for i, original_change in enumerate(original_changes):
        field_path = form_data.get(f"field_path_{i}")
        new_value = form_data.get(f"change_{i}")

        if field_path and new_value is not None:
            edited_changes.append({
                "field_path": field_path,
                "current_value": original_change.get("current_value"),
                "proposed_value": new_value,
                "source_snippet": original_change.get("source_snippet", ""),
            })

    # Collect selected milestones
    edited_milestones = []
    original_milestones = task.details.get("milestones_to_set", [])
    for i, milestone in enumerate(original_milestones):
        if form_data.get(f"milestone_{i}"):
            edited_milestones.append(milestone)

    # Collect selected documents
    edited_documents = []
    original_documents = task.details.get("documents_to_mark", [])
    for i, doc in enumerate(original_documents):
        if form_data.get(f"document_{i}"):
            edited_documents.append(doc)

    # Build edited content
    edited_content = {
        "changes": edited_changes,
        "milestones_to_set": edited_milestones,
        "documents_to_mark": edited_documents,
    }

    success = await approval_loop.approve_with_edits(task, edited_content)

    if success:
        return templates.TemplateResponse(
            request,
            "components/action_result.html",
            {
                "success": True,
                "message": "Extraction applied with edits",
                "task_id": task_id,
            },
        )
    else:
        return templates.TemplateResponse(
            request,
            "components/action_result.html",
            {
                "success": False,
                "message": "Extraction failed",
                "task_id": task_id,
            },
        )
