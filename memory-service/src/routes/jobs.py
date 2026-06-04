from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session

router = APIRouter(prefix="/jobs", tags=["jobs"])


# Inline model for jobs table
from sqlalchemy import DateTime, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base


class Job(Base):
    """Job status tracking for StateClient integration."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending", default="pending")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=datetime.utcnow
    )


class CreateJobBody(BaseModel):
    id: str
    status: str = "pending"


class UpdateJobBody(BaseModel):
    status: str | None = None
    result: dict | None = None
    error: str | None = None


def _job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.post("")
async def create_job(
    body: CreateJobBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new job entry."""
    job = Job(id=body.id, status=body.status)
    session.add(job)
    await session.flush()
    return _job_to_dict(job)


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get job status and result."""
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


@router.put("/{job_id}")
async def update_job(
    job_id: str,
    body: UpdateJobBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update job status and/or result."""
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if body.status is not None:
        job.status = body.status
    if body.result is not None:
        job.result = body.result
    if body.error is not None:
        job.error = body.error
    job.updated_at = datetime.utcnow()
    session.add(job)
    return _job_to_dict(job)
