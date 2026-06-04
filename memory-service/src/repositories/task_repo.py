from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tasks import Task
from src.repositories.base import TenantScopedRepository


class TaskRepository(TenantScopedRepository):
    """Repository for task CRUD with filtering and summary aggregation."""

    async def create(
        self,
        type: str,
        created_by: str,
        control_id: str | None = None,
        framework_id: str | None = None,
        assignee_id: str | None = None,
        status: str = "open",
        due_date: date | None = None,
        note: str | None = None,
        metadata: dict | None = None,
    ) -> Task:
        """Create a new task."""
        await self._set_tenant_context()
        task = Task(
            tenant_id=self._tenant_id,
            type=type,
            control_id=control_id,
            framework_id=framework_id,
            assignee_id=assignee_id,
            status=status,
            due_date=due_date,
            note=note,
            metadata_=metadata,
            created_by=created_by,
        )
        self._session.add(task)
        await self._session.flush()
        return task

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        """Get a task by ID."""
        return await self._get_by_id(Task, task_id)

    async def update(
        self,
        task_id: uuid.UUID,
        status: str | None = None,
        note: str | None = None,
        metadata: dict | None = None,
        blocked_reason: str | None = None,
        assignee_id: str | None = None,
    ) -> Task | None:
        """Update a task's status and/or metadata."""
        await self._set_tenant_context()
        task = await self._get_by_id(Task, task_id)
        if task is None:
            return None
        if status is not None:
            task.status = status
            if status == "completed":
                task.completed_at = datetime.utcnow()
        if note is not None:
            task.note = note
        if metadata is not None:
            task.metadata_ = metadata
        if blocked_reason is not None:
            task.blocked_reason = blocked_reason
        if assignee_id is not None:
            task.assignee_id = assignee_id
        task.updated_at = datetime.utcnow()
        self._session.add(task)
        return task

    async def list_tasks(
        self,
        assignee: str | None = None,
        status: str | None = None,
        overdue: bool = False,
        framework: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional filters."""
        await self._set_tenant_context()
        stmt = select(Task).where(Task.tenant_id == self._tenant_id)

        if assignee:
            stmt = stmt.where(Task.assignee_id == assignee)
        if status:
            stmt = stmt.where(Task.status == status)
        if overdue:
            stmt = stmt.where(
                Task.status.in_(["open", "in_progress", "blocked"]),
                Task.due_date < date.today(),
            )
        if framework:
            stmt = stmt.where(Task.framework_id == framework)

        stmt = stmt.order_by(Task.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def summary(self) -> dict[str, Any]:
        """Get task summary statistics for the tenant."""
        await self._set_tenant_context()

        # Total count
        total_result = await self._session.execute(
            select(func.count(Task.id)).where(Task.tenant_id == self._tenant_id)
        )
        total = total_result.scalar() or 0

        # Open count
        open_result = await self._session.execute(
            select(func.count(Task.id)).where(
                Task.tenant_id == self._tenant_id,
                Task.status == "open",
            )
        )
        open_count = open_result.scalar() or 0

        # Overdue count
        overdue_result = await self._session.execute(
            select(func.count(Task.id)).where(
                Task.tenant_id == self._tenant_id,
                Task.status.in_(["open", "in_progress", "blocked"]),
                Task.due_date < date.today(),
            )
        )
        overdue_count = overdue_result.scalar() or 0

        # Blocked count
        blocked_result = await self._session.execute(
            select(func.count(Task.id)).where(
                Task.tenant_id == self._tenant_id,
                Task.status == "blocked",
            )
        )
        blocked_count = blocked_result.scalar() or 0

        # By assignee
        assignee_result = await self._session.execute(
            select(Task.assignee_id, func.count(Task.id)).where(
                Task.tenant_id == self._tenant_id,
                Task.status.in_(["open", "in_progress", "blocked"]),
            ).group_by(Task.assignee_id)
        )
        by_assignee = {
            row[0] or "unassigned": row[1] for row in assignee_result.all()
        }

        # By framework
        framework_result = await self._session.execute(
            select(Task.framework_id, func.count(Task.id)).where(
                Task.tenant_id == self._tenant_id,
                Task.status.in_(["open", "in_progress", "blocked"]),
            ).group_by(Task.framework_id)
        )
        by_framework = {
            row[0] or "none": row[1] for row in framework_result.all()
        }

        return {
            "total": total,
            "open": open_count,
            "overdue": overdue_count,
            "blocked": blocked_count,
            "by_assignee": by_assignee,
            "by_framework": by_framework,
        }

    async def timeline(self, days: int = 30) -> list[Task]:
        """Get tasks with due dates in the next N days."""
        await self._set_tenant_context()
        today = date.today()
        end_date = date.fromordinal(today.toordinal() + days)

        stmt = (
            select(Task)
            .where(
                Task.tenant_id == self._tenant_id,
                Task.due_date >= today,
                Task.due_date <= end_date,
                Task.status.in_(["open", "in_progress", "blocked"]),
            )
            .order_by(Task.due_date.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
