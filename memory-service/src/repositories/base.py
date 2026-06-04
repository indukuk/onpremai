from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import Base

T = TypeVar("T", bound=Base)


class TenantScopedRepository:
    """Base repository that sets RLS tenant context and scopes all queries to tenant_id."""

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def _set_tenant_context(self) -> None:
        """Set the RLS application-level tenant context variable."""
        await self._session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": self._tenant_id},
        )

    async def _get_by_id(self, model: type[T], record_id: uuid.UUID) -> T | None:
        """Fetch a single record by ID, scoped to tenant."""
        await self._set_tenant_context()
        result = await self._session.execute(
            select(model).where(
                model.id == record_id,  # type: ignore[attr-defined]
                model.tenant_id == self._tenant_id,  # type: ignore[attr-defined]
            )
        )
        return result.scalar_one_or_none()

    async def _delete_by_id(self, model: type[T], record_id: uuid.UUID) -> bool:
        """Delete a record by ID, scoped to tenant. Returns True if deleted."""
        await self._set_tenant_context()
        result = await self._session.execute(
            select(model).where(
                model.id == record_id,  # type: ignore[attr-defined]
                model.tenant_id == self._tenant_id,  # type: ignore[attr-defined]
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return False
        await self._session.delete(obj)
        return True
