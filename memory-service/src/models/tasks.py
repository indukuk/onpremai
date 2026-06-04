from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class Task(Base, IdMixin, TenantMixin, TimestampMixin):
    """Task model tracking compliance work items per tenant."""

    __tablename__ = "tasks"

    type: Mapped[str] = mapped_column(Text, nullable=False)
    control_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    framework_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open", default="open")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata_", JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_tasks_tenant", "tenant_id"),
        Index("idx_tasks_assignee", "tenant_id", "assignee_id", "status"),
        Index("idx_tasks_control", "tenant_id", "control_id"),
    )
