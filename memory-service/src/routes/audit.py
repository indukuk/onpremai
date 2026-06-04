from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.repositories.audit_repo import AuditRepository

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/{tenant_id}")
async def get_audit_trail(
    tenant_id: str,
    since: str | None = Query(default=None, description="ISO datetime filter"),
    operation: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Query audit trail for a tenant (read-only)."""
    since_dt: datetime | None = None
    if since:
        since_dt = datetime.fromisoformat(since)

    repo = AuditRepository(session)
    records = await repo.query(
        tenant_id=tenant_id,
        since=since_dt,
        operation=operation,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": str(r.id),
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "operation": r.operation,
            "tenant_id": r.tenant_id,
            "agent": r.agent,
            "trace_id": r.trace_id,
            "data": r.data,
        }
        for r in records
    ]
