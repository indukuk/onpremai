from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit_trail import AuditTrail


class AuditRepository:
    """Repository for the audit trail. INSERT only - no update or delete methods."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        operation: str,
        tenant_id: str | None = None,
        agent: str | None = None,
        trace_id: str | None = None,
        data: dict | None = None,
    ) -> AuditTrail:
        """Append a new audit record. This is the only write operation."""
        record = AuditTrail(
            operation=operation,
            tenant_id=tenant_id,
            agent=agent,
            trace_id=trace_id,
            data=data,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def query(
        self,
        tenant_id: str,
        since: datetime | None = None,
        operation: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditTrail]:
        """Query audit trail records for a tenant."""
        stmt = select(AuditTrail).where(AuditTrail.tenant_id == tenant_id)

        if since:
            stmt = stmt.where(AuditTrail.timestamp >= since)
        if operation:
            stmt = stmt.where(AuditTrail.operation == operation)

        stmt = stmt.order_by(AuditTrail.timestamp.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
