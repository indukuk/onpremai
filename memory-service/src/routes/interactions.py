from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models.interactions import Interaction
from src.repositories.audit_repo import AuditRepository

router = APIRouter(prefix="/interactions", tags=["interactions"])


class MessageItem(BaseModel):
    role: str
    content: str
    timestamp: str | None = None


class StoreInteractionBody(BaseModel):
    session_id: str
    messages: list[MessageItem]


def _interaction_to_dict(record: Interaction) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "tenant_id": record.tenant_id,
        "user_id": record.user_id,
        "session_id": record.session_id,
        "messages": record.messages,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.post("/{tenant_id}/{user_id}")
async def store_interaction(
    tenant_id: str,
    user_id: str,
    body: StoreInteractionBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Store a conversation interaction."""
    record = Interaction(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=body.session_id,
        messages=[m.model_dump() for m in body.messages],
    )
    session.add(record)
    await session.flush()

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="interaction_store",
        tenant_id=tenant_id,
        data={
            "user_id": user_id,
            "session_id": body.session_id,
            "message_count": len(body.messages),
        },
    )
    return _interaction_to_dict(record)


@router.get("/{tenant_id}/{user_id}")
async def get_user_interactions(
    tenant_id: str,
    user_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Get recent interactions for a user."""
    stmt = (
        select(Interaction)
        .where(
            Interaction.tenant_id == tenant_id,
            Interaction.user_id == user_id,
        )
        .order_by(Interaction.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = result.scalars().all()
    return [_interaction_to_dict(r) for r in records]


@router.get("/{tenant_id}")
async def get_tenant_interactions(
    tenant_id: str,
    since: str | None = Query(default=None, description="ISO datetime filter"),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Get all tenant interactions since a timestamp (for observer batch processing)."""
    stmt = (
        select(Interaction)
        .where(Interaction.tenant_id == tenant_id)
    )
    if since:
        since_dt = datetime.fromisoformat(since)
        stmt = stmt.where(Interaction.created_at >= since_dt)
    stmt = stmt.order_by(Interaction.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    records = result.scalars().all()
    return [_interaction_to_dict(r) for r in records]
