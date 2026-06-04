from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.repositories.task_repo import TaskRepository
from src.repositories.audit_repo import AuditRepository

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTaskBody(BaseModel):
    type: str
    created_by: str
    control_id: str | None = None
    framework_id: str | None = None
    assignee_id: str | None = None
    status: str = "open"
    due_date: date | None = None
    note: str | None = None
    metadata: dict | None = None


class UpdateTaskBody(BaseModel):
    status: str | None = None
    note: str | None = None
    metadata: dict | None = None
    blocked_reason: str | None = None
    assignee_id: str | None = None


def _task_to_dict(task: Any) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "tenant_id": task.tenant_id,
        "type": task.type,
        "control_id": task.control_id,
        "framework_id": task.framework_id,
        "assignee_id": task.assignee_id,
        "status": task.status,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "note": task.note,
        "blocked_reason": task.blocked_reason,
        "metadata": task.metadata_,
        "created_by": task.created_by,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.post("/{tenant_id}")
async def create_task(
    tenant_id: str,
    body: CreateTaskBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new task."""
    repo = TaskRepository(session, tenant_id)
    task = await repo.create(
        type=body.type,
        created_by=body.created_by,
        control_id=body.control_id,
        framework_id=body.framework_id,
        assignee_id=body.assignee_id,
        status=body.status,
        due_date=body.due_date,
        note=body.note,
        metadata=body.metadata,
    )

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="task_create",
        tenant_id=tenant_id,
        agent=body.created_by,
        data={"task_id": str(task.id), "type": body.type},
    )
    return _task_to_dict(task)


@router.get("/{tenant_id}")
async def list_tasks(
    tenant_id: str,
    assignee: str | None = Query(default=None),
    status: str | None = Query(default=None),
    overdue: bool = Query(default=False),
    framework: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List tasks with optional filters."""
    repo = TaskRepository(session, tenant_id)
    tasks = await repo.list_tasks(
        assignee=assignee,
        status=status,
        overdue=overdue,
        framework=framework,
        limit=limit,
        offset=offset,
    )
    return [_task_to_dict(t) for t in tasks]


@router.put("/{tenant_id}/{task_id}")
async def update_task(
    tenant_id: str,
    task_id: uuid.UUID,
    body: UpdateTaskBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a task's status and/or metadata."""
    repo = TaskRepository(session, tenant_id)
    task = await repo.update(
        task_id=task_id,
        status=body.status,
        note=body.note,
        metadata=body.metadata,
        blocked_reason=body.blocked_reason,
        assignee_id=body.assignee_id,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="task_update",
        tenant_id=tenant_id,
        data={"task_id": str(task_id), "updates": body.model_dump(exclude_none=True)},
    )
    return _task_to_dict(task)


@router.get("/{tenant_id}/summary")
async def task_summary(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get task summary statistics."""
    repo = TaskRepository(session, tenant_id)
    return await repo.summary()


@router.get("/{tenant_id}/timeline")
async def task_timeline(
    tenant_id: str,
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Get upcoming deadlines in the next N days."""
    repo = TaskRepository(session, tenant_id)
    tasks = await repo.timeline(days=days)
    return [_task_to_dict(t) for t in tasks]
