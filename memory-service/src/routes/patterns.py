from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.repositories.pattern_repo import PatternRepository
from src.repositories.audit_repo import AuditRepository
from src.services.embedding import EmbeddingService

router = APIRouter(prefix="/patterns", tags=["patterns"])

_embedding_service = EmbeddingService()


class RecordPatternBody(BaseModel):
    pattern: str
    context: dict | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str


def _pattern_to_dict(p: Any) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "pattern": p.pattern,
        "context": p.context,
        "confidence": p.confidence,
        "hit_count": p.hit_count,
        "source": p.source,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None,
    }


@router.post("/record")
async def record_pattern(
    body: RecordPatternBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record a new cross-tenant pattern."""
    embedding = await _embedding_service.embed(body.pattern)

    repo = PatternRepository(session)
    record = await repo.record(
        pattern=body.pattern,
        context=body.context,
        confidence=body.confidence,
        source=body.source,
        embedding=embedding,
    )

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="pattern_record",
        data={"pattern_id": str(record.id), "source": body.source},
    )
    return _pattern_to_dict(record)


@router.get("/query")
async def query_patterns(
    task: str = Query(..., description="Task description for semantic search"),
    top_k: int = Query(default=5, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Semantic search over patterns."""
    embedding = await _embedding_service.embed(task)
    if embedding is None:
        raise HTTPException(
            status_code=503,
            detail="Embedding service unavailable",
        )

    repo = PatternRepository(session)
    results = await repo.query(query_embedding=embedding, top_k=top_k)
    return results


@router.get("/list")
async def list_patterns(
    source: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List patterns with optional filters."""
    repo = PatternRepository(session)
    patterns = await repo.list_patterns(
        source=source,
        min_confidence=min_confidence,
        limit=limit,
    )
    return [_pattern_to_dict(p) for p in patterns]


@router.put("/{pattern_id}/boost")
async def boost_pattern(
    pattern_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Boost a pattern (increment hit_count, reset last_used_at)."""
    repo = PatternRepository(session)
    pattern = await repo.boost(pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="pattern_boost",
        data={"pattern_id": str(pattern_id)},
    )
    return _pattern_to_dict(pattern)


@router.delete("/{pattern_id}")
async def delete_pattern(
    pattern_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Delete a pattern."""
    repo = PatternRepository(session)
    deleted = await repo.delete(pattern_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pattern not found")

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="pattern_delete",
        data={"pattern_id": str(pattern_id)},
    )
    return {"id": str(pattern_id), "status": "deleted"}
