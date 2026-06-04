from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.eval_history import EvalHistory
from src.repositories.base import TenantScopedRepository


class EvalRepository(TenantScopedRepository):
    """Repository for evaluation history records."""

    async def store(
        self,
        framework: str,
        control_id: str,
        status: str,
        result: dict,
        confidence: float | None = None,
        evidence_hash: str | None = None,
        model_used: str | None = None,
        tier_used: str | None = None,
        latency_ms: int | None = None,
    ) -> EvalHistory:
        """Store a new evaluation record."""
        await self._set_tenant_context()
        record = EvalHistory(
            tenant_id=self._tenant_id,
            framework=framework,
            control_id=control_id,
            status=status,
            confidence=confidence,
            evidence_hash=evidence_hash,
            result=result,
            model_used=model_used,
            tier_used=tier_used,
            latency_ms=latency_ms,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_last(
        self,
        framework: str,
        control_id: str,
        evidence_hash: str | None = None,
    ) -> EvalHistory | None:
        """Get the most recent evaluation, optionally filtered by evidence hash."""
        await self._set_tenant_context()
        stmt = (
            select(EvalHistory)
            .where(
                EvalHistory.tenant_id == self._tenant_id,
                EvalHistory.framework == framework,
                EvalHistory.control_id == control_id,
            )
        )
        if evidence_hash:
            stmt = stmt.where(EvalHistory.evidence_hash == evidence_hash)
        stmt = stmt.order_by(EvalHistory.created_at.desc()).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_history(
        self,
        framework: str,
        control_id: str,
        limit: int = 20,
    ) -> list[EvalHistory]:
        """Get evaluation history for a control."""
        await self._set_tenant_context()
        stmt = (
            select(EvalHistory)
            .where(
                EvalHistory.tenant_id == self._tenant_id,
                EvalHistory.framework == framework,
                EvalHistory.control_id == control_id,
            )
            .order_by(EvalHistory.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
