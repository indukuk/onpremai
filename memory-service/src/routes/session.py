from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.config import settings

router = APIRouter(prefix="/session", tags=["session"])


class SessionPutBody(BaseModel):
    data: dict[str, Any]


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request) -> dict[str, Any]:
    """Get session data from Redis."""
    redis = request.app.state.redis
    raw = await redis.get(f"session:{session_id}")
    if raw is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "data": json.loads(raw)}


@router.put("/{session_id}")
async def put_session(session_id: str, body: SessionPutBody, request: Request) -> dict[str, Any]:
    """Store session data in Redis with TTL."""
    redis = request.app.state.redis
    payload = json.dumps(body.data)

    if len(payload.encode("utf-8")) > settings.SESSION_MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large (max 256KB)")

    ttl_seconds = settings.SESSION_TTL_HOURS * 3600
    await redis.set(f"session:{session_id}", payload, ex=ttl_seconds)
    return {"session_id": session_id, "status": "stored", "ttl_seconds": ttl_seconds}


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict[str, str]:
    """Delete session data from Redis."""
    redis = request.app.state.redis
    deleted = await redis.delete(f"session:{session_id}")
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "status": "deleted"}
