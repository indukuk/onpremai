from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.repositories.user_memory_repo import UserMemoryRepository
from src.repositories.audit_repo import AuditRepository
from src.services.embedding import EmbeddingService

router = APIRouter(prefix="/user", tags=["user-memory"])

_embedding_service = EmbeddingService()


class RememberBody(BaseModel):
    fact: str
    category: str
    source: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


@router.post("/{tenant_id}/{user_id}/remember")
async def user_remember(
    tenant_id: str,
    user_id: str,
    body: RememberBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Store a user fact with deduplication."""
    embedding = await _embedding_service.embed(body.fact)

    repo = UserMemoryRepository(session, tenant_id, user_id)
    record, action = await repo.remember(
        fact=body.fact,
        category=body.category,
        source=body.source,
        confidence=body.confidence,
        embedding=embedding,
    )

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="user_remember",
        tenant_id=tenant_id,
        data={
            "user_id": user_id,
            "fact": body.fact,
            "category": body.category,
            "action": action,
        },
    )
    return {"action": action, "id": str(record.id)}


@router.get("/{tenant_id}/{user_id}/recall")
async def user_recall(
    tenant_id: str,
    user_id: str,
    query: str = Query(..., description="Search query text"),
    top_k: int = Query(default=5, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Semantic search over user facts."""
    embedding = await _embedding_service.embed(query)
    if embedding is None:
        raise HTTPException(
            status_code=503,
            detail="Embedding service unavailable",
        )

    repo = UserMemoryRepository(session, tenant_id, user_id)
    results = await repo.recall(query_embedding=embedding, top_k=top_k)
    return results


@router.get("/{tenant_id}/{user_id}/facts")
async def user_facts(
    tenant_id: str,
    user_id: str,
    category: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all facts for a user, optionally filtered by category."""
    repo = UserMemoryRepository(session, tenant_id, user_id)
    facts = await repo.facts(category=category)
    return [
        {
            "id": str(f.id),
            "fact": f.fact,
            "category": f.category,
            "source": f.source,
            "confidence": f.confidence,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        }
        for f in facts
    ]


@router.delete("/{tenant_id}/{user_id}/facts/{fact_id}")
async def delete_user_fact(
    tenant_id: str,
    user_id: str,
    fact_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Delete a user fact."""
    repo = UserMemoryRepository(session, tenant_id, user_id)
    deleted = await repo.delete_fact(fact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Fact not found")

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="user_delete_fact",
        tenant_id=tenant_id,
        data={"user_id": user_id, "fact_id": str(fact_id)},
    )
    return {"id": str(fact_id), "status": "deleted"}
