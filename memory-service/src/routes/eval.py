from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.repositories.eval_repo import EvalRepository
from src.repositories.audit_repo import AuditRepository

router = APIRouter(prefix="/eval", tags=["eval-history"])


class StoreEvalBody(BaseModel):
    status: str
    result: dict
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_hash: str | None = None
    model_used: str | None = None
    tier_used: str | None = None
    latency_ms: int | None = None


def _eval_to_dict(record: Any) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "tenant_id": record.tenant_id,
        "framework": record.framework,
        "control_id": record.control_id,
        "status": record.status,
        "confidence": record.confidence,
        "evidence_hash": record.evidence_hash,
        "result": record.result,
        "model_used": record.model_used,
        "tier_used": record.tier_used,
        "latency_ms": record.latency_ms,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.post("/{tenant_id}/{framework}/{control_id}")
async def store_eval(
    tenant_id: str,
    framework: str,
    control_id: str,
    body: StoreEvalBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Store a new evaluation result."""
    repo = EvalRepository(session, tenant_id)
    record = await repo.store(
        framework=framework,
        control_id=control_id,
        status=body.status,
        result=body.result,
        confidence=body.confidence,
        evidence_hash=body.evidence_hash,
        model_used=body.model_used,
        tier_used=body.tier_used,
        latency_ms=body.latency_ms,
    )

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="eval_store",
        tenant_id=tenant_id,
        data={
            "framework": framework,
            "control_id": control_id,
            "status": body.status,
            "evidence_hash": body.evidence_hash,
        },
    )
    return _eval_to_dict(record)


@router.get("/{tenant_id}/{framework}/{control_id}/last")
async def get_last_eval(
    tenant_id: str,
    framework: str,
    control_id: str,
    evidence_hash: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the most recent evaluation, optionally filtered by evidence hash."""
    repo = EvalRepository(session, tenant_id)
    record = await repo.get_last(
        framework=framework,
        control_id=control_id,
        evidence_hash=evidence_hash,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="No evaluation found")
    return _eval_to_dict(record)


@router.get("/{tenant_id}/{framework}/{control_id}/history")
async def get_eval_history(
    tenant_id: str,
    framework: str,
    control_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Get evaluation history for a control."""
    repo = EvalRepository(session, tenant_id)
    records = await repo.get_history(
        framework=framework,
        control_id=control_id,
        limit=limit,
    )
    return [_eval_to_dict(r) for r in records]
