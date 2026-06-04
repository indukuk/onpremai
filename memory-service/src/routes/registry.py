from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session

router = APIRouter(prefix="/registry", tags=["registry"])


# Inline model since agent_registry is a simple operational table
from sqlalchemy import DateTime, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base


class AgentRegistry(Base):
    """Agent service registry for discovery and heartbeat."""

    __tablename__ = "agent_registry"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    metadata_: Mapped[dict | None] = mapped_column("metadata_", JSON, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=datetime.utcnow
    )
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=datetime.utcnow
    )


class RegisterAgentBody(BaseModel):
    id: str
    name: str
    url: str
    capabilities: list[str] = []
    metadata: dict | None = None


def _agent_to_dict(agent: AgentRegistry) -> dict[str, Any]:
    return {
        "id": agent.id,
        "name": agent.name,
        "url": agent.url,
        "capabilities": agent.capabilities,
        "status": agent.status,
        "metadata": agent.metadata_,
        "registered_at": agent.registered_at.isoformat() if agent.registered_at else None,
        "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
    }


@router.post("/agents")
async def register_agent(
    body: RegisterAgentBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register a new agent or update existing registration."""
    result = await session.execute(
        select(AgentRegistry).where(AgentRegistry.id == body.id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.name = body.name
        existing.url = body.url
        existing.capabilities = body.capabilities
        existing.metadata_ = body.metadata
        existing.status = "active"
        existing.last_heartbeat = datetime.utcnow()
        session.add(existing)
        return _agent_to_dict(existing)

    agent = AgentRegistry(
        id=body.id,
        name=body.name,
        url=body.url,
        capabilities=body.capabilities,
        metadata_=body.metadata,
    )
    session.add(agent)
    await session.flush()
    return _agent_to_dict(agent)


@router.put("/agents/{agent_id}/heartbeat")
async def heartbeat(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update agent heartbeat timestamp."""
    result = await session.execute(
        select(AgentRegistry).where(AgentRegistry.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.last_heartbeat = datetime.utcnow()
    agent.status = "active"
    session.add(agent)
    return _agent_to_dict(agent)


@router.get("/agents")
async def list_agents(
    capability: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List registered agents, optionally filtered by capability."""
    stmt = select(AgentRegistry).where(AgentRegistry.status == "active")
    result = await session.execute(stmt)
    agents = list(result.scalars().all())

    if capability:
        agents = [a for a in agents if capability in (a.capabilities or [])]

    return [_agent_to_dict(a) for a in agents]


@router.delete("/agents/{agent_id}")
async def deregister_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Remove an agent from the registry."""
    result = await session.execute(
        select(AgentRegistry).where(AgentRegistry.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    await session.delete(agent)
    return {"id": agent_id, "status": "deregistered"}
